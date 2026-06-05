"""Anthropic API 토큰 사용량 로컬 추적기.

각 Claude API 호출 후 response.usage 를 읽어 usage_log.json 에 누적한다.
"""
import datetime
import json
import threading
from pathlib import Path

_LOCK = threading.Lock()
LOG_PATH = Path(__file__).parent / "usage_log.json"

# USD / 1M tokens — 공개 가격표 기준 참고치 (변동 가능)
_PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"input": 0.80,  "output": 4.00,  "cache_write": 1.00,  "cache_read": 0.08},
    "claude-haiku-4-5":          {"input": 0.80,  "output": 4.00,  "cache_write": 1.00,  "cache_read": 0.08},
    "claude-sonnet-4-6":         {"input": 3.00,  "output": 15.00, "cache_write": 3.75,  "cache_read": 0.30},
    "claude-opus-4-8":           {"input": 15.00, "output": 75.00, "cache_write": 18.75, "cache_read": 1.50},
}
_DEFAULT_PRICING = {"input": 3.00, "output": 15.00, "cache_write": 3.75, "cache_read": 0.30}


def record(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_write: int = 0,
    cache_read: int = 0,
    purpose: str = "",
) -> None:
    entry = {
        "ts":          datetime.datetime.now().isoformat(timespec="seconds"),
        "model":       model,
        "input":       input_tokens,
        "output":      output_tokens,
        "cache_write": cache_write,
        "cache_read":  cache_read,
        "purpose":     purpose,
    }
    with _LOCK:
        data = _load_raw()
        data["calls"].append(entry)
        t = data["totals"]
        t["input"]       += input_tokens
        t["output"]      += output_tokens
        t["cache_write"] += cache_write
        t["cache_read"]  += cache_read
        t["calls"]       += 1
        _save_raw(data)


def get_stats() -> dict:
    with _LOCK:
        data = _load_raw()

    calls  = data["calls"]
    totals = data["totals"]
    today  = datetime.date.today().isoformat()

    today_calls = [c for c in calls if c["ts"].startswith(today)]

    def _cost(c: dict) -> float:
        p = _PRICING.get(c["model"], _DEFAULT_PRICING)
        return (
            c["input"]       * p["input"]       +
            c["output"]      * p["output"]       +
            c["cache_write"] * p["cache_write"]  +
            c["cache_read"]  * p["cache_read"]
        ) / 1_000_000

    def _sum(lst: list[dict], key: str) -> int:
        return sum(c[key] for c in lst)

    return {
        "today": {
            "date":        today,
            "calls":       len(today_calls),
            "input":       _sum(today_calls, "input"),
            "output":      _sum(today_calls, "output"),
            "cache_write": _sum(today_calls, "cache_write"),
            "cache_read":  _sum(today_calls, "cache_read"),
            "cost_usd":    sum(_cost(c) for c in today_calls),
        },
        "total": {
            "calls":       totals["calls"],
            "input":       totals["input"],
            "output":      totals["output"],
            "cache_write": totals["cache_write"],
            "cache_read":  totals["cache_read"],
            "cost_usd":    sum(_cost(c) for c in calls),
        },
        "last_call": calls[-1]["ts"] if calls else None,
        "recent": calls[-5:] if calls else [],
    }


def _load_raw() -> dict:
    if LOG_PATH.exists():
        try:
            return json.loads(LOG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "calls": [],
        "totals": {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0, "calls": 0},
    }


def _save_raw(data: dict) -> None:
    LOG_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
