"""可选的 AI 润色层：把模板台词交给小模型改写得更生动，默认关闭。

DeepSeek 和通义千问都提供 OpenAI 兼容的 `/chat/completions` 接口，所以一套客户端两家通用，换家只改 `data/llm_polish.json` 里的 `provider`。
密钥只从环境变量读（`api_key_env`）。`polish` 永远不抛异常：关闭、没密钥、场景不在名单、超日限额、超时、出错、输出不合格，都原样返回模板台词。
"""

import logging
import os
import time
from functools import lru_cache
from pathlib import Path

import aiohttp

from utils import settings_hub

log = logging.getLogger(__name__)

_PATH = Path(__file__).resolve().parent.parent / "data" / "llm_polish.json"
_usage = {"day": None, "calls": 0}


@lru_cache(maxsize=1)
def _load() -> dict:
    return settings_hub.read(_PATH)


def load() -> dict:
    return _load()


def reload() -> None:
    _load.cache_clear()


def validate(cfg: dict) -> list[str]:
    errors = []
    prov = cfg.get("providers", {})
    if cfg.get("provider") not in prov:
        errors.append("provider 必须是 providers 里的一个")
    for name, p in prov.items():
        if not (p.get("base_url", "").startswith("http") and p.get("model") and p.get("api_key_env")):
            errors.append(f"providers.{name}: 需要 base_url / model / api_key_env")
    if cfg.get("daily_call_limit", -1) < 0 or cfg.get("timeout_seconds", 0) <= 0 or not 0 <= cfg.get("temperature", -1) <= 2:
        errors.append("daily_call_limit ≥ 0，timeout_seconds > 0，temperature 0~2")
    if cfg.get("max_output_chars", 0) <= 0 or "{max_chars}" not in cfg.get("system_prompt", ""):
        errors.append("max_output_chars > 0，system_prompt 里要有 {max_chars}")
    return errors


def _take_quota(cfg: dict, now: float) -> bool:
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    if _usage["day"] != day:
        _usage.update(day=day, calls=0)
    if _usage["calls"] >= cfg["daily_call_limit"]:
        return False
    _usage["calls"] += 1
    return True


def _clean(text: str, cfg: dict) -> str | None:
    text = (text or "").strip().strip("\"“”「」").strip()
    if not text or "\n" in text or len(text) > cfg["max_output_chars"]:
        return None
    return text


async def _request(cfg: dict, key: str, messages: list[dict]) -> str:
    p = cfg["providers"][cfg["provider"]]
    body = {"model": p["model"], "messages": messages, "temperature": cfg["temperature"], "max_tokens": cfg["max_output_chars"] * 3}
    timeout = aiohttp.ClientTimeout(total=cfg["timeout_seconds"])
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(p["base_url"].rstrip("/") + "/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"}) as resp:
            resp.raise_for_status()
            data = await resp.json()
    return data["choices"][0]["message"]["content"]


async def polish(scene: str, line: str, persona: str = "", *, now: float | None = None, request=None) -> str:
    """返回润色后的台词；任何环节不通就返回原 `line`。`persona` 是一句话的人设提示（性格 / 关系），`request` 供测试替换网络层。"""
    try:
        cfg = load()
        if not cfg["enabled"] or scene not in cfg["scenes"]:
            return line
        key = os.environ.get(cfg["providers"][cfg["provider"]]["api_key_env"], "")
        if not key and request is None:
            return line
        if not _take_quota(cfg, time.time() if now is None else now):
            return line
        messages = [
            {"role": "system", "content": cfg["system_prompt"].format(max_chars=cfg["max_output_chars"])},
            {"role": "user", "content": (f"人设：{persona}\n" if persona else "") + f"台词：{line}"},
        ]
        out = await (request or _request)(cfg, key, messages)
        return _clean(out, cfg) or line
    except Exception as exc:                                                  # 润色是锦上添花，绝不影响主流程
        log.warning("llm_polish 失败，退回模板台词：%s", exc)
        return line
