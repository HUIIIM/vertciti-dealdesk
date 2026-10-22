"""地址结果缓存：24h TTL + 全挂时 stale 兜底。

- 与项目库同一个数据库（persistence.session_scope；SQLite / Postgres 通用）。
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

from sqlalchemy import select

from app.services.persistence.engine import session_scope
from app.services.persistence.schema import AddressCache

CACHE_TTL_SECONDS = 86400  # 24h


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
    h = address_hash(address)
    with session_scope() as sess:
        row = sess.execute(select(AddressCache.data_json, AddressCache.fetched_at)
                           .where(AddressCache.address_hash == h)).first()
    if row is None:
        return None
    try:
        data = json.loads(row.data_json)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    fetched_at = float(row.fetched_at)
    return {
        "data": data,
        "fetched_at": fetched_at,
        "stale": (time.time() - fetched_at) > CACHE_TTL_SECONDS,
    }


def put_cached(address: str, result_dict: dict) -> None:
    """写入缓存（upsert），fetched_at=now。只应在链成功（ok=True）后调用。"""
    h = address_hash(address)
    payload = json.dumps(result_dict or {}, ensure_ascii=False, default=str)
    primary = (result_dict or {}).get("primary_provider") or ""
    now = time.time()
    with session_scope() as sess:
        row = sess.get(AddressCache, h)
        if row is None:
            sess.add(AddressCache(address_hash=h, provider=primary, data_json=payload, fetched_at=now))
        else:
            row.provider, row.data_json, row.fetched_at = primary, payload, now
