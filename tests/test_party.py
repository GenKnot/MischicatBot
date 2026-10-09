"""组队（utils/party.py、utils/views/party.py）。

B67 —— 接受组队邀请 `PartyInviteResponseView.accept` 是一串没有保护的读 → 判断 → 写：
  · `add_to_party` 的返回值被无视：队伍已满 / 玩家不存在时照样显示『组队成功』；
  · 邀请发出后，被邀请者可能已经加入了别的队伍 —— `add_to_party` 无条件覆盖 `party_id`，等于悄悄退出原队伍，
    若他是原队长，原队伍就剩下一群没有队长的人；
  · 邀请者没有队伍时 `create_party` 再拉人：两个被邀请者同时接受，各自建一个队伍，邀请者只属于后建的那个，
    先接受的人留在一个没有队长在场的队伍里；
  · 队伍人数检查与写入之间没有保护：同时接受可以超过 4 人。
  现在『建队 / 入队』是 `accept_invite` 一个事务（先拿写锁再校验），入队的 UPDATE 自带『未在队伍』和『人数 < 4』条件。
B68 —— 发出邀请的按钮 `PartyInviteButton` 对已不存在的玩家直接 TypeError、不检查对方是否坐化 / 是不是自己；
  接受按钮没核对点击者就是被邀请者（`public = True` 的注释写着『校验在回调里』，实际没写）。
"""

import asyncio
import time

from tests.conftest import make_player
from tests.discord_fakes import FakeInteraction
from utils.party import (accept_invite, add_to_party, create_party, disband_party, get_party, get_party_members,
                         remove_from_party)
from utils.views import party as pv
from utils.views.party import (PartyInviteButton, PartyInviteResponseView, PartyView, disband_party_func, leave_party,
                               party_info_embed)

CITY = "灵虚城"


async def _add(db, uid, city=CITY, **kw):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid, stones=0)
        p.name = f"道友{uid}"
        p.current_city, p.lifespan = city, 80
        for k, v in kw.items():
            setattr(p, k, v)
        s.add(p)
        await s.commit()


async def pid(db, uid):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return (await s.get(D.Player, uid)).party_id


async def players(db, *uids):
    for u in uids:
        await _add(db, u)


# --- 数据层 -------------------------------------------------------------------

async def test_建队_队长入队_查询(db):
    await players(db, "1")
    party_id = await create_party("1", CITY)
    assert await pid(db, "1") == party_id
    p = await get_party(party_id)
    assert p["leader_id"] == "1" and p["city"] == CITY and p["created_at"] <= time.time()
    assert [m["discord_id"] for m in await get_party_members(party_id)] == ["1"]
    assert await get_party("nope") is None and await get_party_members("nope") == []


async def test_入队_满4人拒绝_不存在的玩家拒绝(db):
    await players(db, "1", "2", "3", "4", "5")
    party_id = await create_party("1", CITY)
    for u in "234":
        assert await add_to_party(party_id, u) is True
    assert await add_to_party(party_id, "5") is False and await pid(db, "5") is None
    assert await add_to_party(party_id, "nope") is False


async def test_入队_已在别的队伍里不能被覆盖(db):
    await players(db, "1", "2", "3")
    a = await create_party("1", CITY)
    b = await create_party("2", CITY)
    assert await add_to_party(a, "2") is False and await pid(db, "2") == b
    assert await add_to_party(a, "3") is True
    assert await add_to_party(a, "3") is False                          # 已经在这个队里，也不重复算入队


async def test_入队_坐化的不能入队(db):
    await _add(db, "1")
    await _add(db, "2", is_dead=1)
    party_id = await create_party("1", CITY)
    assert await add_to_party(party_id, "2") is False


async def test_B67_并发入队不超过4人(db):
    await players(db, *"123456789")
    party_id = await create_party("1", CITY)
    results = await asyncio.gather(*[add_to_party(party_id, u) for u in "23456789"])
    assert len([r for r in results if r]) == 3 and len(await get_party_members(party_id)) == 4


async def test_退队_普通成员_队长移交_最后一人解散(db):
    await players(db, "1", "2", "3")
    party_id = await create_party("1", CITY)
    await add_to_party(party_id, "2")
    await add_to_party(party_id, "3")
    assert await remove_from_party("2") == "已退出队伍。" and await pid(db, "2") is None
    assert (await get_party(party_id))["leader_id"] == "1"
    await remove_from_party("1")                                           # 队长退出 → 移交给剩下的人
    assert (await get_party(party_id))["leader_id"] == "3"
    await remove_from_party("3")
    assert await get_party(party_id) is None                               # 没人了，队伍记录一并删除


async def test_退队_不在队伍里_队伍记录已不存在(db):
    await players(db, "1")
    assert await remove_from_party("1") == "你不在任何队伍中。" and await remove_from_party("nope") == "你不在任何队伍中。"
    D = db["db_async"]
    from sqlalchemy import update
    async with D.AsyncSessionLocal() as s:
        await s.execute(update(D.Player).values(party_id="GHOST"))
        await s.commit()
    assert await remove_from_party("1") == "已退出队伍。" and await pid(db, "1") is None


async def test_解散_队长才能解散_成员全部退出(db):
    await players(db, "1", "2")
    party_id = await create_party("1", CITY)
    await add_to_party(party_id, "2")
    assert (await disband_party("2"))[0] == "只有队长才能解散队伍。" and await pid(db, "2") == party_id
    assert (await disband_party("nope")) == ("你不在任何队伍中。", [])
    msg, ids = await disband_party("1")
    assert msg == "队伍已解散，所有成员已退出。" and sorted(ids) == ["1", "2"]
    assert await pid(db, "1") is None and await pid(db, "2") is None and await get_party(party_id) is None
    assert (await disband_party("1"))[0] == "你不在任何队伍中。"


# --- accept_invite（B67） -----------------------------------------------------

async def test_接受邀请_邀请者没有队伍_建队并入队(db):
    await players(db, "1", "2")
    r = await accept_invite("1", "2")
    assert r["ok"] and r["party_id"] and await pid(db, "1") == r["party_id"] == await pid(db, "2")
    assert (await get_party(r["party_id"]))["leader_id"] == "1"


async def test_接受邀请_邀请者已有队伍_直接加入(db):
    await players(db, "1", "2", "3")
    first = (await accept_invite("1", "2"))["party_id"]
    r = await accept_invite("1", "3")
    assert r["party_id"] == first and len(await get_party_members(first)) == 3


async def test_接受邀请_各种拒绝(db):
    await _add(db, "1")
    await _add(db, "2", city="天京城")
    await _add(db, "3", is_dead=1)
    await _add(db, "4")
    assert not (await accept_invite("nope", "1"))["ok"] and not (await accept_invite("1", "nope"))["ok"]
    assert "离开原城市" in (await accept_invite("1", "2"))["reason"]
    assert "坐化" in (await accept_invite("1", "3"))["reason"]
    assert "不能" in (await accept_invite("1", "1"))["reason"]
    await _add(db, "5", is_dead=1)
    assert "坐化" in (await accept_invite("5", "4"))["reason"]
    assert await pid(db, "1") is None and await pid(db, "4") is None        # 失败不会留下半个队伍


async def test_B67_被邀请者已加入别的队伍_不能被悄悄带走(db):
    await players(db, "1", "2", "3")
    other = (await accept_invite("2", "3"))["party_id"]                    # 2 是队长，3 在 2 的队里
    r = await accept_invite("1", "2")                                      # 1 之前邀请过 2，现在 2 才接受
    assert not r["ok"] and "已在" in r["reason"]
    assert await pid(db, "2") == other and (await get_party(other))["leader_id"] == "2"
    assert await pid(db, "1") is None                                       # 失败时不建空队


async def test_B67_队伍已满不能再进_不留空队(db):
    await players(db, "1", "2", "3", "4", "5")
    for u in "234":
        await accept_invite("1", u)
    r = await accept_invite("1", "5")
    assert not r["ok"] and "已满" in r["reason"] and await pid(db, "5") is None


async def test_B67_两人同时接受同一个无队伍邀请者_只建一个队(db):
    await players(db, "1", "2", "3", "4")
    results = await asyncio.gather(*[accept_invite("1", u) for u in "234"])
    assert all(r["ok"] for r in results) and len({r["party_id"] for r in results}) == 1
    p = await pid(db, "1")
    assert {await pid(db, u) for u in "1234"} == {p}
    D = db["db_async"]
    from sqlalchemy import func, select
    async with D.AsyncSessionLocal() as s:
        assert (await s.scalar(select(func.count()).select_from(D.Party))) == 1


async def test_B67_并发接受不超过4人(db):
    await players(db, *"123456789")
    results = await asyncio.gather(*[accept_invite("1", u) for u in "23456789"])
    assert len([r for r in results if r["ok"]]) == 3
    p = await pid(db, "1")
    assert len(await get_party_members(p)) == 4


# --- 文案 / 纯函数 ------------------------------------------------------------

def test_队伍文案_标出队长():
    members = [{"discord_id": "1", "name": "甲", "realm": "炼气期1层", "lifespan": 80},
               {"discord_id": "2", "name": "乙", "realm": "筑基期1层", "lifespan": 90}]
    e = party_info_embed(members, "2")
    assert e.description.splitlines()[0].startswith("· **甲**") and e.description.splitlines()[1].startswith("👑 **乙**")
    assert "共 2 人" in e.footer.text


async def test_面板基类():
    v = PartyView(FakeInteraction("1").user, None)
    assert v.author.id == 1


# --- 退队 / 解散的消息封装 ----------------------------------------------------

class Client:
    def __init__(self, fail_for=()):
        self.sent, self.fail_for = [], set(fail_for)

    async def fetch_user(self, n):
        if n in self.fail_for:
            raise RuntimeError("找不到用户")
        client = self

        class U:
            async def send(self_inner, text=None, **kw):
                client.sent.append((n, text, kw))
        return U()


async def test_退队封装(db):
    await players(db, "1")
    assert await leave_party("1", None) == "你不在任何队伍中。"


async def test_解散封装_私信成员_不发给队长_私信失败不影响(db):
    await players(db, "1", "2", "3")
    party_id = await create_party("1", CITY)
    await add_to_party(party_id, "2")
    await add_to_party(party_id, "3")
    client = Client(fail_for={3})
    msg = await disband_party_func("1", client)
    assert msg == "队伍已解散，所有成员已退出。" and [n for n, *_ in client.sent] == [2]
    assert (await disband_party_func("2", client)) == "你不在任何队伍中。"


# --- 邀请按钮（B68） ----------------------------------------------------------

def inter(uid, client=None):
    i = FakeInteraction(uid)
    i.client = client or Client()
    return i


async def get(db, uid):
    return await pv.get_player(uid)


async def invite(db, inviter, target, client=None):
    btn = PartyInviteButton(await get(db, inviter), await get(db, target))
    i = inter(inviter, client)
    await btn.callback(i)
    return i


async def test_邀请_成功私信被邀请者(db):
    await players(db, "1", "2")
    client = Client()
    i = await invite(db, "1", "2", client)
    assert "已向 **道友2** 发送组队邀请" in i.last and i.last.ephemeral
    n, _, kw = client.sent[0]
    assert n == 2 and "组队邀请" in kw["embed"].title and isinstance(kw["view"], PartyInviteResponseView)


async def test_邀请_各种拒绝(db):
    await _add(db, "1")
    await _add(db, "2", city="天京城")
    await _add(db, "3")
    await _add(db, "4", is_dead=1)
    assert "已离开此地" in (await invite(db, "1", "2")).last
    await accept_invite("1", "3")
    await _add(db, "5")
    assert "已在其他队伍中" in (await invite(db, "5", "3")).last
    assert "坐化" in (await invite(db, "1", "4")).last
    assert "不能邀请自己" in (await invite(db, "1", "1")).last


async def test_邀请_队伍满了(db):
    await players(db, "1", "2", "3", "4", "5")
    for u in "234":
        await accept_invite("1", u)
    assert "队伍已满" in (await invite(db, "1", "5")).last


async def test_B68_对方玩家已不存在_不崩(db):
    await players(db, "1", "2")
    btn = PartyInviteButton(await get(db, "1"), await get(db, "2"))
    D = db["db_async"]
    from sqlalchemy import delete
    async with D.AsyncSessionLocal() as s:
        await s.execute(delete(D.Player).where(D.Player.discord_id == "2"))
        await s.commit()
    i = inter("1")
    await btn.callback(i)
    assert i.last.ephemeral and "不存在" in i.last


async def test_邀请_私信失败(db):
    await players(db, "1", "2")
    i = await invite(db, "1", "2", Client(fail_for={2}))
    assert "无法发送邀请" in i.last


# --- 接受 / 拒绝按钮 ----------------------------------------------------------

class Inviter:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    async def send(self, *a, **kw):
        if self.fail:
            raise RuntimeError("关了私信")
        self.sent.append((a, kw))


async def response_view(db, inviter="1", target="2", user=None):
    return PartyInviteResponseView(await get(db, inviter), await get(db, target), user or Inviter())


async def test_接受_成功_广播队伍(db):
    await players(db, "1", "2")
    user = Inviter()
    v = await response_view(db, user=user)
    i = inter("2")
    await v.accept.callback(i)
    assert "组队成功" in i.last.embed.title and "道友1" in i.last.embed.description and "👑 **道友1**" in i.last.embed.description
    assert await pid(db, "1") == await pid(db, "2") and v.is_finished() and user.sent


async def test_接受_邀请者私信失败也不影响(db):
    await players(db, "1", "2")
    v = await response_view(db, user=Inviter(fail=True))
    i = inter("2")
    await v.accept.callback(i)
    assert "组队成功" in i.last.embed.title


async def test_接受_失败原因如实转述_不显示组队成功(db):
    await _add(db, "1")
    await _add(db, "2", city="天京城")
    v = await response_view(db)
    i = inter("2")
    await v.accept.callback(i)
    assert "离开原城市" in i.last and await pid(db, "2") is None


async def test_B67_接受时对方已在别的队伍(db):
    await players(db, "1", "2", "3")
    other = (await accept_invite("2", "3"))["party_id"]
    v = await response_view(db, "1", "2")
    i = inter("2")
    await v.accept.callback(i)
    assert "已在" in i.last and await pid(db, "2") == other and not v.is_finished()
    assert (await get_party(other))["leader_id"] == "2"


async def test_B68_只有被邀请者能点接受或拒绝(db):
    """discord.py 在派发按钮回调前会先调 interaction_check：别人点不到。"""
    await players(db, "1", "2", "3")
    v = await response_view(db)
    i = inter("3")
    assert await v.interaction_check(i) is False and "不是你的邀请" in i.last and i.last.ephemeral
    assert await v.interaction_check(inter("2")) is True
    assert await pid(db, "3") is None and await pid(db, "2") is None


async def test_拒绝_通知邀请者(db):
    await players(db, "1", "2")
    user = Inviter()
    v = await response_view(db, user=user)
    i = inter("2")
    await v.decline.callback(i)
    assert "已拒绝组队邀请" in i.last and v.is_finished() and "拒绝了你的组队邀请" in user.sent[0][0][0]
    v = await response_view(db, user=Inviter(fail=True))
    await v.decline.callback(inter("2"))                                  # 私信失败不抛


async def test_入队_队伍不存在不能入(db):
    await players(db, "1")
    assert await add_to_party("不存在的队伍", "1") is False and await pid(db, "1") is None
