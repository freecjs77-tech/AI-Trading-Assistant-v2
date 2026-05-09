"""
Market Momentum Scanner — History tracking (streak/change/EXIT).

Schema:
{
  "_meta": {"scanner": "momentum_us", "schema_version": 1, "version": "Momentum v1.0",
            "last_updated": "2026-05-06"},
  "data": {
    "<ticker>": {
      "<YYYY-MM-DD>": {
        "stage": "MOMENTUM_2" | None (EXIT),
        "streak": int,
        "prev_stage": str | None,
        "change": "NEW" | "HOLD" | "UPGRADE" | "DOWNGRADE" | "EXIT",
        "entry_price": float, "entry_date": str, "time_in_stage": int,
        "price": float, "rsi": float,
        "ret_1d_pct": float, "ret_3d_pct": float, "ret_5d_pct": float,
        "sector": str, "rs_vs_sector": bool, "risk_tags": list[str],
        "entry_context": dict,    # NEW/UPGRADE/DOWNGRADE 시
        # EXIT 시:
        "exit_price": float, "exit_date": str, "exit_reason": str,
      }
    }
  }
}
"""
import os, json, sys
from datetime import datetime, timezone, timedelta

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import momentum_config as cfg

RANK = {"EM": 0, "MOMENTUM_1": 1, "MOMENTUM_2": 2, "MOMENTUM_3": 3}


def load_history(path: str, scanner_name: str = "momentum_us") -> dict:
    """JSON history 파일 로드. 없으면 skeleton. Legacy EARLY/EXTENDED risk tags filtered."""
    if not os.path.exists(path):
        return _empty_skeleton(scanner_name)
    try:
        with open(path, "rb") as f:
            raw = f.read().rstrip(b" \t\n\r\x00").decode("utf-8")
        history = json.loads(raw)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[momentum_history] WARN corrupt history {path}: {e}")
        return _empty_skeleton(scanner_name)

    # Legacy tag filter on active entries (read-time)
    legacy = cfg.LEGACY_RISK_TAGS
    for ticker, dates in history.get("data", {}).items():
        for d, entry in dates.items():
            tags = entry.get("risk_tags")
            if isinstance(tags, list) and any(t in legacy for t in tags):
                entry["risk_tags"] = [t for t in tags if t not in legacy]
    return history


def _empty_skeleton(scanner_name: str) -> dict:
    return {
        "_meta": {
            "scanner": scanner_name,
            "schema_version": cfg.HISTORY_SCHEMA_VERSION,
            "version": cfg.VERSION,
            "last_updated": None,
        },
        "data": {},
    }


def save_history(path: str, history: dict):
    history.setdefault("_meta", {})
    history["_meta"]["last_updated"] = datetime.now(
        timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    history["_meta"]["schema_version"] = cfg.HISTORY_SCHEMA_VERSION
    history["_meta"]["version"] = cfg.VERSION
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def _last_active_entry(ticker_data: dict) -> dict | None:
    """가장 최근 거래일 entry 반환. EXIT 후 비어있으면 None.

    EXIT 이벤트가 있으면 그 이후로는 새 NEW까지 entry 추가 안 됨이 원칙.
    여기서는 단순히 최신 날짜 entry 반환 — caller가 EXIT 여부로 판단.
    """
    if not ticker_data:
        return None
    last_date = max(ticker_data.keys())
    return ticker_data[last_date]


def update_history(history: dict, today_signals: list[dict], today: str) -> dict:
    """
    today_signals: [{ticker, stage, price, ...}, ...] (M1+ 발동 종목만)
    today: "YYYY-MM-DD"

    Returns: 업데이트된 history dict (in-place modification + return).
    """
    history.setdefault("data", {})
    today_set = {s["ticker"]: s for s in today_signals}

    # ── 시그널 발동 종목: NEW / HOLD / UPGRADE / DOWNGRADE
    for ticker, sig in today_set.items():
        ticker_data = history["data"].setdefault(ticker, {})
        prev = _last_active_entry(ticker_data)
        prev_stage = None
        was_exit = False
        if prev is not None:
            if prev.get("change") == "EXIT":
                was_exit = True
            else:
                prev_stage = prev.get("stage")

        new_stage = sig["stage"]
        if was_exit or prev_stage is None:
            change, streak = "NEW", 1
            entry_price = sig.get("price")
            entry_date = today
            time_in_stage = 1
        elif new_stage == prev_stage:
            change = "HOLD"
            streak = prev.get("streak", 1) + 1
            entry_price = prev.get("entry_price", sig.get("price"))
            entry_date = prev.get("entry_date", today)
            time_in_stage = prev.get("time_in_stage", 1) + 1
        elif RANK.get(new_stage, 0) > RANK.get(prev_stage, 0):
            change = "UPGRADE"
            streak = prev.get("streak", 1) + 1
            entry_price = sig.get("price")
            entry_date = today
            time_in_stage = 1
        else:
            change = "DOWNGRADE"
            streak = 1
            entry_price = sig.get("price")
            entry_date = today
            time_in_stage = 1

        entry = {
            "stage": new_stage,
            "streak": streak,
            "prev_stage": prev_stage,
            "change": change,
            "maturity": sig.get("maturity"),
            "risk_tags": sig.get("risk_tags", []),
            "price": sig.get("price"),
            "rsi": sig.get("rsi"),
            "ret_1d_pct": sig.get("ret_1d_pct"),
            "ret_3d_pct": sig.get("ret_3d_pct"),
            "ret_5d_pct": sig.get("ret_5d_pct"),
            "ret_20d_pct": sig.get("ret_20d_pct"),
            "dist_ema9_pct": sig.get("dist_ema9_pct"),
            "name": sig.get("name"),
            "sector": sig.get("sector"),
            "sector_top_rank": sig.get("sector_top_rank"),
            "rs_vs_sector": sig.get("rs_vs_sector"),
            "entry_price": entry_price,
            "entry_date": entry_date,
            "time_in_stage": time_in_stage,
            "entry_context": {
                "sector": sig.get("sector"),
                "streak": streak,
                "maturity": sig.get("maturity"),
                "risk_tags": sig.get("risk_tags", []),
            },
        }
        ticker_data[today] = entry

    # ── EXIT: 시그널이 사라진 종목
    for ticker, ticker_data in history["data"].items():
        if ticker in today_set:
            continue
        prev = _last_active_entry(ticker_data)
        if prev is None or prev.get("change") == "EXIT" or prev.get("stage") is None:
            continue
        ticker_data[today] = {
            "stage": None,
            "change": "EXIT",
            "prev_stage": prev.get("stage"),
            "exit_price": prev.get("price"),
            "exit_date": today,
            "exit_reason": "EXIT",
        }
    return history
