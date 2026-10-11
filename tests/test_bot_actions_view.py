"""玩家与机器人互动面板：搭话 / 送礼 / 同城列表（utils/views/bot_actions.py、city_players.py、combat.py）。

· 机器人资料页出现「搭话」「送礼」，真人没有；对机器人的「发起攻击」不可用（PvP 对机器人还没设计）；
· 搭话：当天第一次涨好感 + 打招呼，之后「明天再来」；送礼：按反应说台词、显示好感变化与今日剩余份数；
· 同城列表：机器人带 🤖，真人排前，超过一页分页；机器人资料页显示性格与交情；
· 组队 / 双修的答应与拒绝带台词。
"""

import json
from types import SimpleNamespace

import pytest

from tests.conftest import make_player
from tests.discord_fakes import FakeInteraction
from utils import bot_social as bs
from utils.views import bot_actions as ba
from utils.views import city_players as cp
from utils.views.combat import PlayerActionView
from utils.views.party import PartyInviteButton

HUMAN, BOT, CITY = "1001", "bot_00001", "灵虚城"
PERSONA = {"archetype": "豪爽", "tier": "正常", "kindness": 50, "greed": 30, "pride": 40, "talk": 30,
           "likes": {"categories": ["丹药"], "items": ["筑基丹"]},
           "dislikes": {"categories": ["矿石"], "items": ["黄泉铁"]}}


async def _add(db, uid, city=CITY, **kw):
    D = db["db_async"]
    p = make_player(D, uid)
    p.name, p.current_city, p.lifespan = f"道友{uid}", city, 80
    p.is_bot = uid.startswith("bot_")
    for k, v in kw.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def world(db, favor=None, **bot_kw):
    await _add(db, HUMAN)
    await _add(db, BOT, **bot_kw)
    await bs.save_personality(BOT, PERSONA)
    if favor is not None:
        await bs.adjust_favor(HUMAN, BOT, favor)


async def row(uid):
    from utils.player import get_player
    return await get_player(uid)


def inter(uid=HUMAN, client=None):
    i = FakeInteraction(uid)
    i.message = SimpleNamespace(id=1)
    i.client = client or SimpleNamespace(cogs={}, fetch_user=None)
    return i


def labels(view):
    return [getattr(c, "label", None) for c in view.children]


async def action_view(db, in_pvp=True, target=BOT):
    return PlayerActionView(inter().user, await row(HUMAN), await row(target), in_pvp)


def set_text(modal, value):
    modal.item._value = value


# ---- 面板上的按钮 -----------------------------------------------------------

async def test_机器人资料页有搭话和送礼_真人没有(db):
    await world(db)
    await _add(db, "1002")
    bot_view = await action_view(db)
    assert {"💬 搭话", "🎁 送礼"} <= set(labels(bot_view))
    human_view = await action_view(db, target="1002")
    assert not {"💬 搭话", "🎁 送礼"} & set(labels(human_view))


async def test_对机器人的攻击_秘地里可用_城里不可用(db):
    """机器人和真人一样：只有在秘地（PvP 区）才能攻击；城里的机器人只能聊天送礼。"""
    await world(db)
    atk = lambda v: next(c for c in v.children if c.label == "⚔️ 发起攻击")      # noqa: E731
    assert atk(await action_view(db, in_pvp=True)).disabled is False
    assert atk(await action_view(db, in_pvp=False)).disabled is True


async def test_城里不能攻击机器人_旧面板也不行(db):
    await world(db)
    v = await action_view(db, in_pvp=True)
    i = inter()
    await v._attack_callback(i)                       # 两人都在灵虚城（安全区）
    assert "安全区域" in i.last and i.last.ephemeral


# ---- 搭话 -------------------------------------------------------------------

async def test_搭话_第一次涨好感_打招呼(db):
    await world(db)
    i = inter()
    await ba.BotChatButton({"discord_id": BOT, "name": "某"}).callback(i)
    assert i.last.ephemeral and "好感 +1 → 陌生（1）" in i.last.embed.footer.text
    assert i.last.embed.description.startswith("「") and "{" not in i.last.embed.description
    assert await bs.get_favor(HUMAN, BOT) == 1


async def test_搭话_当天第二次_明天再来(db):
    await world(db)
    btn = ba.BotChatButton({"discord_id": BOT, "name": "某"})
    await btn.callback(inter())
    i = inter()
    await btn.callback(i)
    assert "好感不变" in i.last.embed.footer.text and await bs.get_favor(HUMAN, BOT) == 1


async def test_搭话_用对应档位的台词(db):
    await world(db, favor=50)
    i = inter()
    await ba.BotChatButton({"discord_id": BOT, "name": "某"}).callback(i)
    assert i.last.embed.description in {f"「{t.format(player=f'道友{HUMAN}', bot=f'道友{BOT}')}」"
                                        for t in json.loads(open("data/bot_dialogues/豪爽.json", encoding="utf-8").read())
                                        ["lines"]["greet"]["至交"]}


async def test_搭话_不在同城被拒(db):
    await world(db, current_city="别处")
    i = inter()
    await ba.BotChatButton({"discord_id": BOT, "name": "某"}).callback(i)
    assert "不在此地" in i.last and i.last.view is None and await bs.get_favor(HUMAN, BOT) == 0


# ---- 送礼 -------------------------------------------------------------------

async def test_送礼按钮_背包空时提示(db):
    await world(db)
    i = inter()
    await ba.BotGiftButton({"discord_id": BOT, "name": "某"}).callback(i)
    assert "没有可以送的物品" in i.last and i.modal is None


async def test_送礼按钮_弹出表单并提示背包里有什么(db):
    await world(db)
    await db["inventory"].add_item(HUMAN, "筑基丹", 1)
    i = inter()
    await ba.BotGiftButton({"discord_id": BOT, "name": "某"}).callback(i)
    assert isinstance(i.modal, ba.GiftModal) and "筑基丹" in i.modal.item.placeholder


async def test_送礼_喜欢的东西_台词与好感变化(db):
    await world(db)
    await db["inventory"].add_item(HUMAN, "筑基丹", 1)
    m = ba.GiftModal({"discord_id": BOT, "name": "某"})
    set_text(m, " 筑基丹 ")
    i = inter()
    await m.on_submit(i)
    foot = i.last.embed.footer.text
    assert i.last.ephemeral and "好感 +" in foot and "今日还能送 2 份" in foot
    assert i.last.embed.description.startswith("「") and "{" not in i.last.embed.description
    assert await db["inventory"].get_inventory(BOT) == {"筑基丹": 1}


async def test_送礼_讨厌的东西_好感下降(db):
    await world(db, favor=10)
    await db["inventory"].add_item(HUMAN, "黄泉铁", 1)
    m = ba.GiftModal({"discord_id": BOT, "name": "某"})
    set_text(m, "黄泉铁")
    i = inter()
    await m.on_submit(i)
    assert "好感 -8 → 陌生（2）" in i.last.embed.footer.text


async def test_送礼_失败给出原因_什么都不改(db):
    await world(db)
    for text, words in [("筑基丹", "背包里没有"), ("不存在的东西", "没有这种物品")]:
        m = ba.GiftModal({"discord_id": BOT, "name": "某"})
        set_text(m, text)
        i = inter()
        await m.on_submit(i)
        assert words in i.last and i.last.ephemeral
    assert await bs.get_favor(HUMAN, BOT) == 0


async def test_送礼_当天上限_婉拒台词(db):
    await world(db)
    await db["inventory"].add_item(HUMAN, "筑基丹", 4)
    for _ in range(3):
        m = ba.GiftModal({"discord_id": BOT, "name": "某"})
        set_text(m, "筑基丹")
        await m.on_submit(inter())
    m = ba.GiftModal({"discord_id": BOT, "name": "某"})
    set_text(m, "筑基丹")
    i = inter()
    await m.on_submit(i)
    assert "今日不能再送了" in i.last.embed.footer.text
    assert await db["inventory"].get_inventory(HUMAN) == {"筑基丹": 1}


# ---- 同城列表 ---------------------------------------------------------------

def players(n_humans, n_bots):
    base = {"realm": "炼气期1层", "cultivation": 0}
    return ([{"discord_id": f"{2000 + i}", "name": f"真人{i}", **base} for i in range(n_humans)]
            + [{"discord_id": f"bot_{i:05d}", "name": f"机器人{i}", **base} for i in range(n_bots)])


VIEWER = {"realm": "炼气期5层", "cultivation": 0}


def test_列表_机器人带标记_真人排前():
    ps = players(2, 2)[::-1]                                  # 乱序给
    embed = cp._city_players_embed(ps, VIEWER)
    lines = embed.description.split("\n")
    assert [("🤖" in l) for l in lines] == [False, False, True, True]
    assert embed.footer.text is None


def test_列表_超过一页分页():
    ps = players(3, 22)                                       # 25 人 → 3 页
    assert cp._page_count(ps) == 3
    e0, e2 = cp._city_players_embed(ps, VIEWER, 0), cp._city_players_embed(ps, VIEWER, 2)
    assert len(e0.description.split("\n")) == 10 and len(e2.description.split("\n")) == 5
    assert "第 1/3 页 · 共 25 人" in e0.footer.text and "第 3/3 页" in e2.footer.text


async def test_列表_视图分页按钮(db):
    ps = players(3, 22)
    v = cp.CityPlayersView(inter().user, ps, VIEWER)
    assert labels(v).count("◀ 上一页") == 1 and v.children[-3].disabled is True and v.children[-2].disabled is False
    i = inter()
    await v.children[-2].callback(i)                          # 下一页
    assert "第 2/3 页" in i.last.embed.footer.text and i.last.view.page == 1
    last = cp.CityPlayersView(inter().user, ps, VIEWER, page=99)
    assert last.page == 2 and last.children[-2].disabled is True


async def test_列表_不满一页没有翻页按钮(db):
    v = cp.CityPlayersView(inter().user, players(3, 2), VIEWER)
    assert "◀ 上一页" not in labels(v) and len(v.children) == 5 + 1


async def test_点机器人_资料页显示性格交情_没有安全区提示(db):
    await world(db, favor=25)
    target = {"discord_id": BOT, "name": f"道友{BOT}", "realm": "炼气期1层", "cultivation": 0}
    i = inter()
    await cp.CityPlayerButton(target, 0).callback(i)
    desc = i.last.embed.description
    assert "性格：豪爽" in desc and "交情：熟识（25）" in desc and "安全区域" not in desc
    assert "🤖" in i.last.embed.title and "💬 搭话" in labels(i.last.view)


async def test_点真人_资料页照旧有安全区提示(db):
    await _add(db, HUMAN)
    await _add(db, "1002")
    i = inter()
    await cp.CityPlayerButton({"discord_id": "1002", "name": "道友1002", "realm": "炼气期1层", "cultivation": 0}, 0).callback(i)
    assert "安全区域" in i.last.embed.description and "性格" not in i.last.embed.description


# ---- 组队 / 双修的台词 ------------------------------------------------------

async def test_组队_答应与拒绝都带台词(db):
    await world(db, favor=5)
    btn = PartyInviteButton(await row(HUMAN), await row(BOT))
    i = inter()
    await btn.callback(i)
    assert i.last.content.startswith("「") and "5/20" in i.last.content
    await bs.adjust_favor(HUMAN, BOT, 20)
    i = inter()
    await btn.callback(i)
    assert "「" in i.last.embed.description and "欣然应允" in i.last.embed.description


async def test_双修_拒绝带台词_答应前先说话(db):
    await world(db, favor=10)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, HUMAN)).techniques = json.dumps(["双修功法"])
        await s.commit()
    v = await action_view(db)
    i = inter()
    await v._dual_cultivate_callback(i)
    assert "「" in i.last.content and "10/50" in i.last.content
    await bs.adjust_favor(HUMAN, BOT, 60)
    done = []

    class Cog:
        async def do_dual_cultivate(self, *a):
            done.append(a)

    i = inter(client=SimpleNamespace(cogs={"Cultivation": Cog()}, fetch_user=None))
    v = await action_view(db)
    await v._dual_cultivate_callback(i)
    assert done and any("「" in (m.content or "") for m in i.messages)


# ---- 用的是哪个场景的台词 ---------------------------------------------------

@pytest.fixture
def scenes(monkeypatch):
    seen = []

    def fake(archetype, scene, tier, rng=None, **fmt):
        seen.append((archetype, scene, tier))
        return f"<{scene}|{tier}>"
    monkeypatch.setattr(bs, "get_line", fake)
    return seen


async def test_搭话_第一次用greet_第二次用chat_again(db, scenes):
    await world(db)
    btn = ba.BotChatButton({"discord_id": BOT, "name": "某"})
    await btn.callback(inter())
    await btn.callback(inter())
    assert scenes == [("豪爽", "greet", "陌生"), ("豪爽", "chat_again", "陌生")]


@pytest.mark.parametrize("item,scene", [("筑基丹", "gift_love"), ("黄泉铁", "gift_hate")])
async def test_送礼_按反应选场景(db, scenes, item, scene):
    await world(db)
    await db["inventory"].add_item(HUMAN, item, 1)
    m = ba.GiftModal({"discord_id": BOT, "name": "某"})
    set_text(m, item)
    await m.on_submit(inter())
    assert scenes[-1][1] == scene


async def test_送礼_场景档位取送礼之后的好感(db, scenes):
    """对话里的语气跟着『现在』的交情走：送完礼好感过线了，用新档位说话。"""
    await world(db, favor=15)
    await db["inventory"].add_item(HUMAN, "筑基丹", 1)
    m = ba.GiftModal({"discord_id": BOT, "name": "某"})
    set_text(m, "筑基丹")
    await m.on_submit(inter())
    assert scenes[-1][2] == "熟识"
