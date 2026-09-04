"""日志与审计测试。

业务层原先 logging 出现 0 次、7 处 print、16 处静默吞异常，线上出事没有任何线索。
"""

import logging
import os
import re

import pytest

from utils.config import is_master
from utils.logging_setup import audit, configure_logging


class _User:
    id = 123

    def __str__(self):
        return "GenKnot"


def test_审计日志带上操作者和对象(caplog):
    with caplog.at_level(logging.WARNING, logger="mischicat.audit"):
        audit("reset_gamble", _User(), target="456")

    text = caplog.text
    assert "reset_gamble" in text
    assert "GenKnot" in text and "123" in text      # 谁做的
    assert "target=456" in text                     # 对谁做的


def test_审计走_warning_级别(caplog):
    """审计不能是 debug/info —— 默认级别下必须看得见。"""
    with caplog.at_level(logging.WARNING, logger="mischicat.audit"):
        audit("reset_job", _User())
    assert caplog.records and caplog.records[0].levelno >= logging.WARNING


def test_日志级别可用环境变量控制(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    configure_logging()
    assert logging.getLogger().level == logging.DEBUG

    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    configure_logging()
    assert logging.getLogger().level == logging.WARNING


def test_无效的日志级别回落到_info(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "不存在的级别")
    configure_logging()
    assert logging.getLogger().level == logging.INFO


# --- 管理员判定 --------------------------------------------------------------

def test_默认管理员可用():
    assert is_master("304758476448595970")
    assert not is_master("999")


def test_管理员可由环境变量配置(monkeypatch):
    import importlib

    from utils import config
    monkeypatch.setenv("MASTER_IDS", "111, 222")
    importlib.reload(config)
    try:
        assert config.is_master(111) and config.is_master("222")
        assert not config.is_master("304758476448595970")
    finally:
        monkeypatch.delenv("MASTER_IDS")
        importlib.reload(config)


# --- 代码层面的约束 -----------------------------------------------------------

def _source_files():
    for root in ("utils", "cogs", "web"):
        for dirpath, _dirs, names in os.walk(root):
            if "__pycache__" in dirpath:
                continue
            for name in sorted(names):
                if name.endswith(".py"):
                    yield os.path.join(dirpath, name)


def test_业务代码里不再用_print():
    """print 在容器里没有级别、没有时间戳，也过滤不掉。"""
    offenders = [
        f"{path}:{i}"
        for path in _source_files()
        for i, line in enumerate(open(path, encoding="utf-8"), 1)
        if re.match(r"\s*print\(", line)
    ]
    assert not offenders, f"这些地方还在用 print：{offenders}"


def test_管理员_id_不再硬编码():
    """权限判断统一走 utils.config.is_master。"""
    offenders = [p for p in _source_files()
                 if "304758476448595970" in open(p, encoding="utf-8").read()
                 and not p.endswith("config.py")]
    assert not offenders, f"这些文件里还有硬编码的管理员 ID：{offenders}"
