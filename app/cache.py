"""地址结果缓存：24h TTL + 全挂时 stale 兜底。

- 与 app/db.py 共用同一个 SQLite 库（复用 _conn()，不另建库）。
- 表 address_cache(address_hash TEXT PRIMARY KEY, provider TEXT, data_json TEXT, fetched_at REAL)
- address_hash = sha256(归一化地址).hexdigest()，归一化 = strip + lower + 压缩空白。
- TTL = 24h（CACHE_TTL_SECONDS）；get_cached 返回 {"data", "fetched_at", "stale"}，
  stale=True 表示条目存在但已超过 TTL（由调用方决定是否兜底使用）。
- data_json 存整个 run_chain 返回 dict 的 JSON（default=str，容忍 datetime 等类型）。
"""

from __future__ import annotations

import hashlib
import json
import re
import time

from .db import _conn

CACHE_TTL_SECONDS = 86400  # 24h

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS address_cache (
    address_hash TEXT PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT '',
    data_json TEXT NOT NULL,
    fetched_at REAL NOT NULL
)
"""


def _ensure_table() -> None:
    with _conn() as conn:
        conn.execute(_CREATE_SQL)


def normalize_address(address: str) -> str:
    """归一化：strip + lower + 压缩连续空白为单个空格。"""
    return re.sub(r"\s+", " ", (address or "").strip().lower())


def address_hash(address: str) -> str:
    """sha256(归一化地址).hexdigest()。"""
    return hashlib.sha256(normalize_address(address).encode("utf-8")).hexdigest()


def get_cached(address: str) -> dict | None:
    """查缓存。

    返回 {"data": 反序列化后的 run_chain 结果, "fetched_at": float,
           "stale": bool(是否超过 TTL)}；无条目/反序列化失败返回 None。
    """
    _ensure_table()
    h = address_hash(address)
    with _conn() as conn:
        row = conn.execute(
            "SELECT data_json, fetched_at FROM address_cache WHERE address_hash=?",
            (h,),
        ).fetchone()
    if row is None:
        return None
    try:
        data = json.loads(row["data_json"])
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    fetched_at = float(row["fetched_at"])
    return {
        "data": data,
        "fetched_at": fetched_at,
        "stale": (time.time() - fetched_at) > CACHE_TTL_SECONDS,
    }


def put_cached(address: str, result_dict: dict) -> None:
    """写入缓存（upsert），fetched_at=now。只应在链成功（ok=True）后调用。"""
    _ensure_table()
    h = address_hash(address)
    payload = json.dumps(result_dict or {}, ensure_ascii=False, default=str)
    primary = (result_dict or {}).get("primary_provider") or ""
    now = time.time()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO address_cache (address_hash, provider, data_json, fetched_at)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(address_hash) DO UPDATE SET"
            " provider=excluded.provider,"
            " data_json=excluded.data_json,"
            " fetched_at=excluded.fetched_at",
            (h, primary, payload, now),
        )
