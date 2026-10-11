"""排行榜与 Web 面板里的机器人（U1「江湖百态」，用户 2026-10-09 决定「显示但带标记」）。

· 游戏内排行榜：机器人照常上榜，名字前带 🤖，榜上有机器人时页脚说明；
· Web 总览：在世修士只数真人，机器人单独一格；活跃类数字、最近活跃、已坐化只算真人；富豪 / 属性前五带机器人标记；
· Web 修士列表 / 属性榜：默认只看真人，勾选「含机器人」才出现；机器人带标记；
· Web 世界 / 境界页：人口统计含机器人（这是『世界』的人口），境界页另给出其中机器人数；
· 修士详情页：机器人带徽章。
"""

import time

import pytest
from fastapi.testclient import TestClient

import web.main as web_main
from tests.conftest import make_player
from tests.discord_fakes import FakeInteraction
from utils.views import leaderboard as lb

H, B = "1001", "bot_00001"


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(web_main, "WEB_PASS", "")
    monkeypatch.setattr(web_main, "IN_KUBERNETES", False)
    lb.reset_power_cache()
    return TestClient(web_main.app)


async def _add(db, uid, **kw):
    D = db["db_async"]
    p = make_player(D, uid, stones=kw.pop("stones", 100))
    p.name = kw.pop("name", f"道友{uid}")
    p.is_bot = uid.startswith("bot_")
    p.lifespan, p.current_city = 80, "灵虚城"
    for k, v in kw.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def both(db, **bot_kw):
    await _add(db, H, name="真人甲")
    await _add(db, B, name="机器人乙", **bot_kw)


# ---- 游戏内排行榜 -----------------------------------------------------------

BOARDS = ["境界榜", "战力榜", "寿元榜", "声望榜", "炼丹榜", "富豪榜"]


@pytest.mark.parametrize("board", BOARDS)
async def test_榜单_机器人带标记_真人不带(db, board):
    lb.reset_power_cache()
    await _add(db, H, name="真人甲", alchemy_level=1, spirit_stones=500, reputation=5, realm="炼气期3层", lifespan=99)
    await _add(db, B, name="机器人乙", alchemy_level=1, spirit_stones=400, reputation=4, realm="炼气期2层", lifespan=98)
    embed = await lb._BOARDS[board]()
    lines = embed.description.split("\n")
    human = next(l for l in lines if "真人甲" in l)
    bot = next(l for l in lines if "机器人乙" in l)
    assert "🤖" not in human and "🤖" in bot and bot.index("🤖") < bot.index("机器人乙")


async def test_榜单_页脚说明标记含义(db):
    await both(db)
    i = FakeInteraction(1)
    v = lb.LeaderboardView(i.user)
    await v._show(i, "富豪榜")
    assert "🤖 = 机器人" in i.last.embed.footer.text


async def test_榜单_没有机器人时页脚不提(db):
    await _add(db, H)
    i = FakeInteraction(1)
    await lb.LeaderboardView(i.user)._show(i, "富豪榜")
    assert "🤖" not in i.last.embed.footer.text


async def test_战力榜缓存里也带机器人标记(db):
    await both(db)
    ranked = await lb._get_power_ranking()
    assert {r["name"]: r["is_bot"] for r in ranked} == {"真人甲": False, "机器人乙": True}


def card(html: str, label: str) -> str:
    """总览页上标签为 label 的统计卡片里的数字。"""
    import re
    return re.search(r'<div class="num"[^>]*>(\d+)</div>\s*<div class="label">' + label, html).group(1)


# ---- Web 总览 ---------------------------------------------------------------

async def test_总览_在世修士只数真人_机器人单独一格(db, client):
    await both(db)
    await _add(db, "bot_00002", name="机器人丙")
    html = client.get("/").text
    assert card(html, "在世修士") == "1" and card(html, "机器人") == "2"


async def test_总览_活跃数字与最近活跃只算真人(db, client):
    now = time.time()
    await _add(db, H, name="真人甲", cultivating_until=now + 999)
    await _add(db, B, name="机器人乙", cultivating_until=now + 999, last_active=now + 5)
    html = client.get("/").text
    assert card(html, "闭关中") == "1"                       # 只有真人
    recent = html.split("最近活跃")[1].split("</table>")[0]
    assert "真人甲" in recent and "机器人乙" not in recent


async def test_总览_境界分布与已坐化只算真人(db, client):
    await _add(db, H, realm="炼气期1层")
    await _add(db, B, realm="筑基期5层")
    await _add(db, "bot_00002", is_dead=True)
    await _add(db, "1002", is_dead=True)
    html = client.get("/").text
    assert "筑基期5层" not in html.split("境界分布")[1].split("最近活跃")[0]
    assert card(html, "已坐化") == "1" and card(html, "机器人") == "1"   # 已坐化只算真人那个；活着的机器人 1 个


async def test_总览_前五榜带机器人标记(db, client):
    await _add(db, H, name="真人甲", spirit_stones=10)
    await _add(db, B, name="机器人乙", spirit_stones=999)
    html = client.get("/").text
    assert html.count("机器人乙") == 2 and html.count("机器人</span>") == 2        # 富豪前五、属性前五各一处


# ---- Web 修士列表 / 属性榜 --------------------------------------------------

async def test_修士列表_默认不含机器人(db, client):
    await both(db)
    html = client.get("/players").text
    assert "真人甲" in html and "机器人乙" not in html and "修士列表（1 人）" in html
    assert 'name="bots"' in html and "含机器人" in html


async def test_修士列表_勾选含机器人才出现_且带标记(db, client):
    await both(db)
    html = client.get("/players?bots=1").text
    assert "机器人乙" in html and "修士列表（2 人）" in html and "badge-gray\">机器人" in html
    assert 'name="bots" value="1" checked' in html


async def test_修士列表_城市下拉与结果一致(db, client):
    await _add(db, H, current_city="灵虚城")
    await _add(db, B, current_city="落云城")
    assert "落云城" not in client.get("/players").text
    assert "落云城" in client.get("/players?bots=1").text


async def test_修士列表_搜索也遵守开关(db, client):
    await both(db)
    assert "机器人乙" not in client.get("/players?q=乙").text
    assert "机器人乙" in client.get("/players?q=乙&bots=1").text


async def test_属性榜_同样的开关(db, client):
    await both(db)
    assert "机器人乙" not in client.get("/stats").text
    html = client.get("/stats?bots=1").text
    assert "机器人乙" in html and "badge-gray\">机器人" in html
    assert "bots=1" in html.split("</thead>")[0], "排序链接要带着开关"


# ---- 其他页面 ---------------------------------------------------------------

async def test_详情页_机器人有徽章_真人没有(db, client):
    await both(db)
    assert "badge-gray\" style=\"margin-left:4px\">机器人" in client.get(f"/players/{B}").text
    assert "机器人" not in client.get(f"/players/{H}").text


async def test_已坐化页只列真人(db, client):
    await _add(db, "1002", name="亡者甲", is_dead=True)
    await _add(db, "bot_00002", name="亡者机器人", is_dead=True)
    html = client.get("/dead").text
    assert "亡者甲" in html and "亡者机器人" not in html


async def test_境界页_人口含机器人_另给机器人数(db, client):
    await both(db)
    html = client.get("/realms").text
    assert "在世修士（其中机器人 1）" in html and card(html, "在世修士（其中机器人 1）") == "2"


async def test_世界页_城市人数含机器人(db, client):
    await _add(db, H, current_city="灵虚城")
    await _add(db, B, current_city="灵虚城")
    html = client.get("/world").text
    assert '<span class="world-mini-name">灵虚城</span>\n        <span class="world-mini-badge">2人</span>' in html
