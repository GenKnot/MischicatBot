"""AI 润色层：默认关闭；开启后任何失败都退回模板台词；日限额；两家 provider 的配置都合法。"""

import pytest

from utils import llm_polish as lp


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    lp._usage.update(day=None, calls=0)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "k")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")


def on(monkeypatch, **over):
    cfg = {**lp.load(), "enabled": True, **over}
    monkeypatch.setattr(lp, "load", lambda: cfg)
    return cfg


def fake(text, calls=None):
    async def req(cfg, key, messages):
        if calls is not None:
            calls.append(messages)
        return text
    return req


def test_配置合法_且默认关闭():
    assert lp.validate(lp.load()) == []
    assert lp.load()["enabled"] is False
    assert {"qwen", "deepseek"} <= set(lp.load()["providers"])


@pytest.mark.parametrize("name", ["qwen", "deepseek"])
def test_两家provider都通过校验(monkeypatch, name):
    assert lp.validate({**lp.load(), "provider": name}) == []


def test_校验报错():
    assert lp.validate({**lp.load(), "provider": "nope"})
    assert lp.validate({**lp.load(), "system_prompt": "无占位"})


async def test_默认关闭_原样返回():
    assert await lp.polish("chatter_arrive", "原句", request=fake("改写")) == "原句"


async def test_开启后返回润色结果_并带人设(monkeypatch):
    on(monkeypatch)
    calls = []
    assert await lp.polish("chatter_arrive", "原句", "豪爽·熟识", request=fake("「改写」", calls)) == "改写"
    assert "豪爽·熟识" in calls[0][1]["content"] and "原句" in calls[0][1]["content"]


async def test_场景不在名单_原样返回(monkeypatch):
    on(monkeypatch)
    assert await lp.polish("request_dun", "原句", request=fake("改写")) == "原句"


async def test_没有密钥_原样返回(monkeypatch):
    on(monkeypatch)
    monkeypatch.delenv("DASHSCOPE_API_KEY")
    assert await lp.polish("chatter_arrive", "原句") == "原句"


@pytest.mark.parametrize("bad", ["", "   ", "太长" * 50, "两行\n内容"])
async def test_输出不合格_原样返回(monkeypatch, bad):
    on(monkeypatch)
    assert await lp.polish("chatter_arrive", "原句", request=fake(bad)) == "原句"


async def test_网络出错_原样返回(monkeypatch):
    on(monkeypatch)

    async def boom(cfg, key, messages):
        raise TimeoutError

    assert await lp.polish("chatter_arrive", "原句", request=boom) == "原句"


async def test_日限额_超了就不再调用_次日重置(monkeypatch):
    on(monkeypatch, daily_call_limit=2)
    calls = []
    out = [await lp.polish("chatter_arrive", "原", now=1000.0, request=fake("新", calls)) for _ in range(3)]
    assert out == ["新", "新", "原"] and len(calls) == 2
    assert await lp.polish("chatter_arrive", "原", now=1000.0 + 86400 * 2, request=fake("新", calls)) == "新"
