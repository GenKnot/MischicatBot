"""事件循环不被阻塞的回归测试。

bot 和 uvicorn 共用一个事件循环（main.py 的 asyncio.gather），
web 路由要是写成 async def，函数体就跑在事件循环上，那段时间 Discord 完全无响应。
实测 5000 名玩家时 /players 要 243ms，其中 SQL 只占 108ms，剩下是模板渲染 ——
所以"把查询改异步"只能解决一半，得让整个函数体都离开事件循环。

FastAPI 对同步 def 会自动丢线程池，所以页面路由刻意写成 def。
"""

import ast
import os

import pytest

_WEB_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "web", "main.py")

# 探针和中间件保持 async：它们不查库、不渲染模板，放在事件循环上更省一次线程切换
ASYNC_ALLOWED = {"access_control", "health", "ready", "robots", "service_worker"}


def _route_functions():
    tree = ast.parse(open(_WEB_MAIN, encoding="utf-8").read())
    for node in tree.body:
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        if not any("app" in ast.dump(d) for d in node.decorator_list):
            continue
        yield node


def test_页面路由必须是同步_def():
    offenders = [
        n.name for n in _route_functions()
        if isinstance(n, ast.AsyncFunctionDef) and n.name not in ASYNC_ALLOWED
    ]
    assert not offenders, (
        f"这些路由是 async def，函数体会阻塞事件循环：{offenders}。"
        "页面路由请写成同步 def，FastAPI 会丢进线程池。")


def test_同步路由里不能有_await():
    """写成 def 之后如果还需要 await，说明这个路由改错了。"""
    for node in _route_functions():
        if isinstance(node, ast.FunctionDef):
            assert "Await(" not in ast.dump(node), f"{node.name} 是同步的却含 await"


def test_探针仍然是异步的():
    names = {n.name for n in _route_functions() if isinstance(n, ast.AsyncFunctionDef)}
    assert "health" in names and "ready" in names


# --- 主菜单的事件提示 --------------------------------------------------------

def test_事件提示会被缓存(db):
    import utils.views.menu as menu

    menu._event_hint_cache = None
    first = menu._get_event_hint()
    second = menu._get_event_hint()

    assert first == second
    assert menu._event_hint_cache is not None, "应当缓存下来，主菜单是最常打开的界面"


def test_缓存过期后会重新查询(db, monkeypatch):
    import utils.views.menu as menu

    menu._event_hint_cache = None
    menu._get_event_hint()
    stamp, _hint = menu._event_hint_cache

    monkeypatch.setattr(menu, "_EVENT_HINT_TTL", -1)   # 立刻过期
    menu._get_event_hint()

    assert menu._event_hint_cache[0] > stamp


def test_查询失败时回落到默认文案(db, monkeypatch):
    """拿不到锁或表不存在时，宁可显示默认文案也不能把 bot 卡住。"""
    import sqlite3

    import utils.views.menu as menu

    menu._event_hint_cache = None

    def _boom(*a, **kw):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(sqlite3, "connect", _boom)

    assert menu._get_event_hint() == menu._DEFAULT_EVENT_HINT
