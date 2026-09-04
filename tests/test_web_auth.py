"""Web 面板访问控制测试。

面板会显示玩家的 discord_id 和作息，还挂着 cloudflared 隧道对外。
没有写接口，所以是信息泄露而不是接管，但 discord_id 被索引了就收不回来。
"""

import base64

import pytest
from fastapi.testclient import TestClient

import web.main as web_main


@pytest.fixture
def client(db):
    """db 夹具保证表已建好，页面路由能正常查询。"""
    return TestClient(web_main.app)


@pytest.fixture
def auth_mode(monkeypatch):
    """把访问控制切到指定档位。"""
    def _set(password: str = "", in_k8s: bool = False, user: str = "admin"):
        monkeypatch.setattr(web_main, "WEB_PASS", password)
        monkeypatch.setattr(web_main, "WEB_USER", user)
        monkeypatch.setattr(web_main, "IN_KUBERNETES", in_k8s)
    return _set


def _basic(user: str, password: str) -> dict:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


# --- 模式 2：本地运行，未设密码 --------------------------------------------

def test_本地未设密码时放行(client, auth_mode):
    """单机/本地跑的用户不该被密码挡住。"""
    auth_mode(password="", in_k8s=False)
    assert client.get("/").status_code == 200
    assert client.get("/players").status_code == 200


# --- 模式 3：k8s 内未设密码 → fail-closed ----------------------------------

def test_k8s内未设密码时停用面板(client, auth_mode):
    """生产是对外暴露的，漏配环境变量不能导致裸奔。"""
    auth_mode(password="", in_k8s=True)
    assert client.get("/").status_code == 503
    assert client.get("/players").status_code == 503


def test_停用状态下探针仍然可用(client, auth_mode):
    """探针若被一并挡住，k8s 会一直判定 pod 不健康。"""
    auth_mode(password="", in_k8s=True)
    assert client.get("/health").status_code == 200


# --- 模式 1：设了密码 → 强制 Basic ------------------------------------------

def test_无凭证被拒并带认证质询(client, auth_mode):
    auth_mode(password="s3cret", in_k8s=True)
    response = client.get("/")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="Mischicat"'


@pytest.mark.parametrize("headers, expected, label", [
    ({}, 401, "无凭证"),
    ({"Authorization": "Basic !!!notbase64"}, 401, "畸形 base64"),
    ({"Authorization": "Bearer xyz"}, 401, "非 Basic 方案"),
    ({"Authorization": "Basic " + base64.b64encode(b"noseparator").decode()}, 401, "缺少冒号"),
])
def test_异常凭证一律拒绝(client, auth_mode, headers, expected, label):
    auth_mode(password="s3cret", in_k8s=True)
    assert client.get("/", headers=headers).status_code == expected, label


def test_密码或用户名错误都被拒(client, auth_mode):
    auth_mode(password="s3cret", user="admin", in_k8s=True)
    assert client.get("/", headers=_basic("admin", "wrong")).status_code == 401
    assert client.get("/", headers=_basic("root", "s3cret")).status_code == 401


def test_凭证正确时放行(client, auth_mode):
    auth_mode(password="s3cret", user="admin", in_k8s=True)
    assert client.get("/", headers=_basic("admin", "s3cret")).status_code == 200
    assert client.get("/players", headers=_basic("admin", "s3cret")).status_code == 200


def test_玩家数据在无凭证时不可读(client, auth_mode):
    """回归重点：discord_id 不能在未鉴权状态下泄露。"""
    auth_mode(password="s3cret", in_k8s=True)
    for path in ("/players", "/stats", "/dead", "/players/12345"):
        assert client.get(path).status_code == 401, path


def test_鉴权开启时静态资源与探针不受影响(client, auth_mode):
    auth_mode(password="s3cret", in_k8s=True)
    assert client.get("/health").status_code == 200
    assert client.get("/static/style.css").status_code == 200


# --- 爬虫防护 ---------------------------------------------------------------

def test_robots_禁止全站抓取(client, auth_mode):
    """面板每一页都从导航链得到，没有 robots.txt 会被整站抓走。"""
    auth_mode(password="", in_k8s=False)
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert "Disallow: /" in response.text


def test_响应带_noindex_头(client, auth_mode):
    """即便鉴权被关掉，也不希望玩家数据进搜索引擎索引。"""
    auth_mode(password="", in_k8s=False)
    assert client.get("/").headers["x-robots-tag"] == "noindex, nofollow"


# --- 排序参数 ---------------------------------------------------------------

@pytest.mark.parametrize("payload", [
    "cultivation; DROP TABLE players--",
    "1) UNION SELECT 1,2,3--",
    "name--",
    "(SELECT 1)",
    "",
])
def test_排序参数注入无效(client, auth_mode, payload):
    """sort 不再被拼进 SQL，而是拿去查列名表，命不中就回落默认。"""
    auth_mode(password="", in_k8s=False)

    assert client.get("/players", params={"sort": payload}).status_code == 200
    assert client.get("/stats", params={"sort": payload}).status_code == 200

    from utils.db import get_conn
    with get_conn() as conn:
        assert conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE name='players'"
        ).fetchone()[0] == 1, "表被删了"


@pytest.mark.parametrize("column", [
    "cultivation", "lifespan", "spirit_stones", "realm", "name", "last_active",
])
def test_players_支持的排序都能用(client, auth_mode, column):
    auth_mode(password="", in_k8s=False)
    assert client.get("/players", params={"sort": column}).status_code == 200


@pytest.mark.parametrize("column", [
    "cultivation", "reputation", "comprehension", "bone", "soul",
    "rebirth_count", "stat_total",
])
def test_stats_支持的排序都能用(client, auth_mode, column):
    auth_mode(password="", in_k8s=False)
    for order in ("asc", "desc"):
        r = client.get("/stats", params={"sort": column, "order": order})
        assert r.status_code == 200, f"{column} {order}"


def test_order_参数只认_asc(client, auth_mode):
    """order 不做白名单，只判断是否等于 asc，其余一律 DESC。"""
    auth_mode(password="", in_k8s=False)
    assert client.get("/stats", params={"order": "asc; DROP TABLE players--"}).status_code == 200
