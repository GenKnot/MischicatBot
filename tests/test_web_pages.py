"""Web 面板的页面路由与辅助函数（web/main.py）。访问控制见 test_web_auth.py。

B73 —— 认证用 `secrets.compare_digest(str, str)`，而它对非 ASCII 字符串直接抛 TypeError：
  · 任何带中文 / 非 ASCII 的 Basic 凭证（哪怕是攻击者随便发的）都会让中间件抛 500，而不是 401；
  · 管理员要是把 `WEB_USER` / `WEB_PASS` 设成中文，正确的凭证也永远登不进去（一律 500）。
  改成按 UTF-8 字节比较。
B74 —— `/equipment-preview` 把用户传的 `slot` / `quality` 原样交给 `generate_equipment`，不认识的值直接 KeyError → 500；
  `tier` 也没有夹取。非法值改成「随机」，`tier` 夹到合法范围。
"""

import base64
import json
import time

import pytest
from fastapi.testclient import TestClient

import web.main as web_main
from tests.conftest import make_player

U = "1001"


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(web_main, "WEB_PASS", "")
    monkeypatch.setattr(web_main, "IN_KUBERNETES", False)
    return TestClient(web_main.app)


async def _add(db, uid=U, **kw):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid, stones=kw.pop("stones", 100))
        p.name = kw.pop("name", f"道友{uid}")
        for k, v in kw.items():
            setattr(p, k, v)
        s.add(p)
        await s.commit()


# --- B73：非 ASCII 凭证 -------------------------------------------------------

def basic(user, password):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


def test_B73_非ASCII凭证是401而不是500(db, monkeypatch):
    monkeypatch.setattr(web_main, "WEB_PASS", "secret")
    monkeypatch.setattr(web_main, "WEB_USER", "admin")
    c = TestClient(web_main.app, raise_server_exceptions=False)
    for headers in (basic("用户", "密码"), basic("admin", "密码"), basic("用户", "secret")):
        r = c.get("/players", headers=headers)
        assert r.status_code == 401, headers


def test_B73_管理员用中文凭证也能登录(db, monkeypatch):
    monkeypatch.setattr(web_main, "WEB_PASS", "密码123")
    monkeypatch.setattr(web_main, "WEB_USER", "管理员")
    c = TestClient(web_main.app, raise_server_exceptions=False)
    assert c.get("/players", headers=basic("管理员", "密码123")).status_code == 200
    assert c.get("/players", headers=basic("管理员", "错")).status_code == 401


def test_基本认证解析():
    web_main_ok = web_main._basic_auth_ok
    assert web_main_ok(None) is False and web_main_ok("") is False and web_main_ok("Bearer x") is False
    assert web_main_ok("Basic !!!不是base64") is False
    assert web_main_ok("Basic " + base64.b64encode("没有冒号".encode()).decode()) is False
    assert web_main_ok("Basic " + base64.b64encode(b"\xff\xfe:x").decode()) is False          # 不是 UTF-8


# --- 辅助函数 -----------------------------------------------------------------

def test_时间格式():
    assert web_main.ts(None) == "—" and web_main.ts(0) == "—" and web_main.ts("不是数字") == "—"
    assert len(web_main.ts(time.time())) == len("2026-10-09 12:00")


def test_剩余时间():
    assert web_main.duration_left(None) is None and web_main.duration_left(0) is None
    assert web_main.duration_left(time.time() - 5) == "已结束"
    assert web_main.duration_left(time.time() + 3600 * 2 + 60 * 30 + 5) == "2h 30m"


def test_模板全局():
    g = web_main.templates.env.globals
    assert g["ts"] is web_main.ts and g["duration_left"] is web_main.duration_left and callable(g["now"])


# --- 探针 ---------------------------------------------------------------------

def test_health_ready_robots_sw(client):
    assert client.get("/health").json() == {"status": "ok"}
    r = client.get("/ready")
    assert r.status_code == 503 and r.json() == {"status": "starting", "discord": False}
    assert client.get("/robots.txt").text.startswith("User-agent: *") and "Disallow: /" in client.get("/robots.txt").text
    r = client.get("/sw.js")
    assert r.status_code == 200 and r.headers["service-worker-allowed"] == "/" and "javascript" in r.headers["content-type"]


def test_ready随bot状态变化(client, monkeypatch):
    class Bot:
        def __init__(self, ready, closed):
            self._r, self._c = ready, closed

        def is_ready(self):
            return self._r

        def is_closed(self):
            return self._c
    monkeypatch.setattr(web_main, "_bot", None)
    assert client.get("/ready").status_code == 503
    web_main.set_bot(Bot(True, False))
    assert client.get("/ready").json() == {"status": "ok", "discord": True}
    web_main.set_bot(Bot(False, False))
    assert client.get("/ready").status_code == 503
    web_main.set_bot(Bot(True, True))
    assert client.get("/ready").status_code == 503
    web_main.set_bot(None)


# --- 首页 ---------------------------------------------------------------------

async def test_首页统计(db, client):
    now = time.time()
    await _add(db, "1", cultivating_until=now + 3600)
    await _add(db, "2", gathering_until=now + 3600)
    await _add(db, "3", active_quest="{}", quest_due=now + 3600)
    await _add(db, "4", is_dead=1)
    r = client.get("/")
    assert r.status_code == 200
    html = r.text
    assert "道友1" in html and "noindex" in r.headers["x-robots-tag"]


def test_首页空库也能渲染(client):
    assert client.get("/").status_code == 200


# --- 玩家列表 -----------------------------------------------------------------

async def test_玩家列表_默认只列活人_按修为排(db, client):
    await _add(db, "1", name="低", cultivation=10)
    await _add(db, "2", name="高", cultivation=999)
    await _add(db, "3", name="死人", is_dead=1)
    html = client.get("/players").text
    assert html.index("高") < html.index("低") and "死人" not in html


async def test_玩家列表_搜索_城市_境界过滤(db, client):
    await _add(db, "111", name="青玄", current_city="天京城", realm="筑基期1层")
    await _add(db, "222", name="云游", current_city="灵虚城", realm="炼气期1层")
    assert "青玄" in client.get("/players", params={"q": "青"}).text and "云游" not in client.get("/players", params={"q": "青"}).text
    assert "云游" in client.get("/players", params={"q": "222"}).text                    # 也能搜 discord_id
    assert "青玄" in client.get("/players", params={"city": "天京城"}).text and "云游" not in client.get("/players", params={"city": "天京城"}).text
    assert "青玄" in client.get("/players", params={"realm": "筑基"}).text and "云游" not in client.get("/players", params={"realm": "筑基"}).text


@pytest.mark.parametrize("sort", ["cultivation", "lifespan", "spirit_stones", "realm", "name", "last_active", "不存在", "name; DROP TABLE players"])
async def test_玩家列表_排序白名单(db, client, sort):
    await _add(db, "1")
    assert client.get("/players", params={"sort": sort}).status_code == 200
    assert client.get("/players").status_code == 200                                    # 表还在


async def test_玩家列表_搜索参数不能注入(db, client):
    await _add(db, "1", name="正常")
    r = client.get("/players", params={"q": "' OR '1'='1"})
    assert r.status_code == 200 and "正常" not in r.text


async def test_玩家列表_名字里的HTML被转义(db, client):
    await _add(db, "1", name="<script>alert(1)</script>")
    html = client.get("/players").text
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


# --- 玩家详情 -----------------------------------------------------------------

async def test_玩家详情(db, client):
    await _add(db, U, name="青玄", techniques=json.dumps([{"name": "青云心法", "stage": "入门", "equipped": True}]),
               active_quest=json.dumps({"title": "剿匪", "id": "q"}))
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.Inventory(discord_id=U, item_id="灵芝草", quantity=3))
        s.add(D.Equipment(equip_id="e1", discord_id=U, name="青锋剑", slot="武器", quality="稀有", tier=1, tier_req=0,
                          stats=json.dumps({"physique": 2}), flavor="寒", equipped=True))
        s.add(D.Residence(discord_id=U, city="灵虚城", purchased_at=time.time()))
        await s.commit()
    r = client.get(f"/players/{U}")
    assert r.status_code == 200
    for word in ("青玄", "灵芝草", "青锋剑", "剿匪"):
        assert word in r.text


async def test_玩家详情_不存在是404(db, client):
    assert client.get("/players/不存在").status_code == 404


async def test_玩家详情_路径里的注入字符无效(db, client):
    await _add(db, U)
    assert client.get("/players/1' OR '1'='1").status_code == 404


async def test_玩家详情_名字里的HTML被转义(db, client):
    await _add(db, U, name="<img src=x onerror=alert(1)>")
    html = client.get(f"/players/{U}").text
    assert "<img src=x" not in html and "&lt;img" in html


# --- 事件 ---------------------------------------------------------------------

async def _event(db, n, started):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.PublicEvent(event_id=f"E{n}", event_type="spirit_rain", title=f"灵雨{n}", started_at=started,
                            ends_at=started + 600, status="settled", data=json.dumps({"k": n})))
        s.add(D.PublicEventParticipant(event_id=f"E{n}", discord_id=U, activity="defense", joined_at=started, contribution=n))
        s.add(D.PublicEventParticipant(event_id=f"E{n}", discord_id=U, activity="gather", joined_at=started, contribution=n * 2))
        await s.commit()


async def test_事件页_参与者合并_含拍卖(db, client):
    await _add(db, U, name="青玄")
    now = time.time()
    await _event(db, 1, now - 100)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.WanbaoAuction(auction_id="A1", date_str="2026-10-09", status="done", started_at=now - 50, ends_at=now))
        s.add(D.WanbaoLot(lot_id="L1", auction_id="A1", lot_index=0, item_name="九转玄功", start_price=100,
                          current_bid=500, bidder_id=U, status="sold"))
        await s.commit()
    r = client.get("/events")
    assert r.status_code == 200 and "灵雨1" in r.text and "万宝楼大型拍卖会" in r.text and "九转玄功" in r.text and "青玄" in r.text
    assert r.text.index("万宝楼大型拍卖会") < r.text.index("灵雨1")                       # 新的在前


async def test_事件页_分页(db, client):
    now = time.time()
    for n in range(25):
        await _event(db, n, now - n * 1000)
    p1, p2, p3, p99 = (client.get("/events", params={"page": p}).text for p in (1, 2, 3, 99))
    assert "灵雨0" in p1 and "灵雨24" not in p1 and "灵雨24" in p3 and p99 == p3
    assert "灵雨10" in p2
    assert client.get("/events", params={"page": 0}).text == p1 and client.get("/events", params={"page": -5}).text == p1


def test_事件页_空库(client):
    assert client.get("/events").status_code == 200


# --- 物品 / 功法 / 统计 -------------------------------------------------------

def test_物品页_过滤(client):
    r = client.get("/items")
    assert r.status_code == 200 and "聚灵丹" in r.text
    assert "聚灵丹" in client.get("/items", params={"q": "聚灵"}).text
    only_pill = client.get("/items", params={"type_filter": "pill"}).text
    assert "聚灵丹" in only_pill and "铜矿石" not in only_pill
    assert "铜矿石" not in client.get("/items", params={"rarity": "绝世"}).text
    assert client.get("/items", params={"q": "绝对不存在的东西"}).status_code == 200


def test_功法页_过滤(client):
    assert "青云心法" in client.get("/techniques").text
    assert "青云心法" in client.get("/techniques", params={"q": "青云"}).text
    r = client.get("/techniques", params={"type_filter": "攻击"})
    assert r.status_code == 200 and "御剑术" in r.text and "青云心法" not in r.text
    r = client.get("/techniques", params={"grade": "黄级上品"})
    assert r.status_code == 200 and "青云心法" in r.text
    assert client.get("/techniques", params={"grade": "不存在"}).status_code == 200


@pytest.mark.parametrize("sort", ["cultivation", "stat_total", "name", "rebirth_count", "bogus", "name; DROP TABLE players"])
@pytest.mark.parametrize("order", ["asc", "desc", "随便"])
async def test_统计页_排序白名单(db, client, sort, order):
    await _add(db, "1")
    assert client.get("/stats", params={"sort": sort, "order": order}).status_code == 200
    assert client.get("/players").status_code == 200


async def test_统计页_按属性总和排序(db, client):
    await _add(db, "1", name="弱", comprehension=1, physique=1, fortune=1, bone=1, soul=1)
    await _add(db, "2", name="强", comprehension=9, physique=9, fortune=9, bone=9, soul=9)
    desc = client.get("/stats", params={"sort": "stat_total"}).text
    asc = client.get("/stats", params={"sort": "stat_total", "order": "asc"}).text
    assert desc.index("强") < desc.index("弱") and asc.index("弱") < asc.index("强")


# --- 装备预览（B74） ----------------------------------------------------------

def test_装备预览_不带参数不抽卡(client):
    r = client.get("/equipment-preview")
    assert r.status_code == 200


def test_装备预览_指定品质部位(client):
    r = client.get("/equipment-preview", params={"slot": "武器", "quality": "传说", "tier": 2, "count": 3})
    assert r.status_code == 200 and r.text.count("传说") >= 3


def test_装备预览_数量被夹到1到10(client):
    for count in (0, -3, 999):
        assert client.get("/equipment-preview", params={"count": count}).status_code == 200


@pytest.mark.parametrize("params", [{"slot": "不存在的部位"}, {"quality": "不存在的品质"}, {"tier": -5}, {"tier": 99999},
                                    {"slot": "x", "quality": "y", "tier": -1}])
def test_B74_非法参数不会500(db, params):
    c = TestClient(web_main.app, raise_server_exceptions=False)
    assert c.get("/equipment-preview", params=params).status_code == 200


# --- 其余页面 -----------------------------------------------------------------

async def test_已故页(db, client):
    await _add(db, "1", name="活人")
    await _add(db, "2", name="亡者", is_dead=1)
    html = client.get("/dead").text
    assert "亡者" in html and "活人" not in html


async def test_世界页_统计城市人数与宗门人数(db, client):
    await _add(db, "1", current_city="灵虚城", sect="青云宗")
    await _add(db, "2", current_city="灵虚城")
    r = client.get("/world")
    assert r.status_code == 200 and "灵虚城" in r.text and "青云宗" in r.text and "昆仑秘境" in r.text


def test_所有页面都带noindex头(client):
    for path in ("/", "/players", "/events", "/items", "/stats", "/techniques", "/equipment-preview", "/dead", "/realms", "/world"):
        r = client.get(path)
        assert r.status_code == 200 and r.headers["x-robots-tag"] == "noindex, nofollow", path


# --- 同步连接（B76） ----------------------------------------------------------

def test_B76_get_conn离开后连接已关闭(db):
    import sqlite3
    from utils.db import get_conn
    with get_conn() as conn:
        conn.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")                                  # Cannot operate on a closed database


def test_B76_get_conn出错时回滚并关闭(db):
    import sqlite3
    from utils.db import get_conn
    holder = {}
    with pytest.raises(RuntimeError):
        with get_conn() as conn:
            holder["conn"] = conn
            conn.execute("CREATE TABLE IF NOT EXISTS _tmp_b76 (x INTEGER)")
            conn.execute("INSERT INTO _tmp_b76 VALUES (1)")
            raise RuntimeError("中途出错")
    with pytest.raises(sqlite3.ProgrammingError):
        holder["conn"].execute("SELECT 1")
    with get_conn() as conn:                                       # DDL 不在事务里（建表已生效），插入的那一行被回滚了
        assert conn.execute("SELECT COUNT(*) FROM _tmp_b76").fetchone()[0] == 0
        conn.execute("DROP TABLE _tmp_b76")


def test_B76_get_conn正常离开会提交(db):
    from utils.db import get_conn
    with get_conn() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS _tmp_b76b (x INTEGER)")
        conn.execute("INSERT INTO _tmp_b76b VALUES (7)")
    with get_conn() as conn:
        assert conn.execute("SELECT x FROM _tmp_b76b").fetchone()[0] == 7
        conn.execute("DROP TABLE _tmp_b76b")


def test_页面请求不再留下ResourceWarning(client, recwarn):
    import gc
    for path in ("/", "/players", "/dead", "/realms", "/world", "/events", "/stats"):
        assert client.get(path).status_code == 200
    gc.collect()
    leaked = [w for w in recwarn if issubclass(w.category, ResourceWarning) and "unclosed database" in str(w.message)]
    assert not leaked, [str(w.message) for w in leaked]
