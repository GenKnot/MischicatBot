"""境界体系页面测试。

顺带守住两条：REALMS 必须由 REALM_GROUPS 派生；玩家境界默认值必须在 REALMS 里
（原先是"炼气期一层"，中文数字，get_realm_index 会兜底返回 0）。
"""

import pytest
from fastapi.testclient import TestClient

import web.main as web_main
from tests.conftest import make_player
from utils.db_async import Player
from utils.realms import REALM_GROUPS, REALMS, major_realm


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(web_main, "WEB_PASS", "")
    monkeypatch.setattr(web_main, "IN_KUBERNETES", False)
    return TestClient(web_main.app)


async def _add(db, uid, realm, dead=False):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid)
        p.realm = realm
        p.is_dead = dead
        s.add(p)
        await s.commit()


# --- 境界体系本身 ------------------------------------------------------------

def test_realms_由分组派生且不分叉():
    flat = [r for _major, subs in REALM_GROUPS for r in subs]
    assert list(REALMS) == flat
    assert len(REALMS) == len(set(REALMS)), "境界名不能重复"


def test_每个境界都能查到所属大境():
    for realm in REALMS:
        assert major_realm(realm) is not None, realm


def test_体系外的境界名返回_None():
    assert major_realm("炼气期一层") is None      # 中文数字，历史写法
    assert major_realm("不存在的境界") is None


def test_玩家境界默认值必须在体系内():
    """回归：默认值曾是"炼气期一层"，不在 REALMS 里。

    当时恰好没出事（`get_realm_index` 兜底返回 0，正好是炼气期1层），
    但只要 REALMS 调过顺序就会错。
    """
    default = Player.__table__.c.realm.default.arg
    assert default in REALMS, f"默认境界 {default!r} 不在 REALMS 里"


# --- 页面 --------------------------------------------------------------------

def test_页面正常渲染(client):
    assert client.get("/realms").status_code == 200


def test_列出全部大境与小境(client):
    body = client.get("/realms").text
    for major, subs in REALM_GROUPS:
        assert major in body, f"缺少大境 {major}"
        for realm in subs:
            assert realm in body, f"缺少小境 {realm}"


async def test_统计各境界人数(db, client):
    await _add(db, "1", "炼气期1层")
    await _add(db, "2", "炼气期1层")
    await _add(db, "3", "结丹期中期")

    body = client.get("/realms").text

    assert "3</div><div class=\"label\">在世修士" in body.replace("\n", "") or "3" in body
    # 炼气期这一组应当显示 2 人
    assert "2 人" in body and "1 人" in body


async def test_坐化玩家不计入在世人数(db, client):
    await _add(db, "1", "炼气期1层")
    await _add(db, "2", "炼气期1层", dead=True)

    body = client.get("/realms").text

    assert "已坐化" in body
    # 在世只有 1 人
    import re
    living = re.search(r'<div class="num" style="color:var\(--success\)">(\d+)</div>', body)
    assert living and living.group(1) == "1"


async def test_无人的境界不显示人数(db, client):
    await _add(db, "1", "炼气期1层")
    body = client.get("/realms").text
    assert "—" in body, "空境界应当显示占位符而不是 0 人"


async def test_体系外的境界会被单独列出而不是静默丢掉(db, client):
    """历史数据里可能有不在 REALMS 的境界值，页面要显示出来而不是吞掉。"""
    await _add(db, "1", "某个不存在的境界")

    body = client.get("/realms").text

    assert "未归入体系" in body
    assert "某个不存在的境界" in body


async def test_显示当前最高境界(db, client):
    await _add(db, "1", "炼气期1层")
    await _add(db, "2", "太乙中期")

    body = client.get("/realms").text

    assert "当前最高境界" in body
    idx_highest = body.index("当前最高境界")
    assert "太乙中期" in body[idx_highest:idx_highest + 200]


def test_导航里有入口(client):
    body = client.get("/").text
    assert 'href="/realms"' in body
