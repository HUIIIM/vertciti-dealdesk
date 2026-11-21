"""地址结果缓存：分级 TTL（完整成功 7 天 / 部分或失败 24h）+ 全挂时 stale 兜底。

- 与项目库同一个数据库（persistence.session_scope；SQLite / Postgres 通用）。
- 表 address_cache(address_hash TEXT PRIMARY KEY, provider TEXT, data_json TEXT, fetched_at REAL)
- address_hash = sha256(归一化地址).hexdigest()，归一化 = strip + lower + 压缩空白。
- 写入条件（以代码为准）：providers.run_chain 在默认链（use_cache 且未注入 providers）
  合并出至少 1 个字段（result ok=True）时写入——含"部分失败"结果（如 TopHap 挂、
  RentCast 未配置、仅 Census 1 个字段），并非只有完整成功才写。
- 分级 TTL（读时由存储的结果推导，无写时标记、无 schema 变更；存量条目同样适用）：
  完整成功 = ok=True 且 primary_provider 非空，且满足其一：
    (a) provider_results 每一段 status 都是 "ok"（无 failed / skipped 段）；
    (b) 冒烟口径：fields ≥ COMPLETE_MIN_FIELDS（15，同 tools/smoke-test.sh MIN_FIELDS）。
  完整成功 → CACHE_TTL_SECONDS（默认 604800=7 天；env DEALDESK_CACHE_TTL_SECONDS 覆盖）；
  其余（部分/失败）→ CACHE_TTL_PARTIAL_SECONDS（默认 86400=24h；
  env DEALDESK_CACHE_TTL_PARTIAL_SECONDS 覆盖）。env 非正整数时回落默认值。
- get_cached 返回 {"data", "fetched_at", "stale", "complete", "ttl_seconds"}，
  stale=True 表示条目存在但已超过其所属档 TTL（由调用方决定是否兜底使用）。
- data_json 存整个 run_chain 返回 dict 的 JSON（default=str，容忍 datetime 等类型）。
- 同表另承载用量计数行（usage_count / usage_reserve）：键为 "usage:<名>" 前缀
  （非 64 位 hex，永不与地址 hash 冲突），provider 列固定 USAGE_PROVIDER，
  data_json = {"count": n}。用于 RentCast 月度预算帽（跨进程/跨实例共享计数）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.services.persistence.engine import session_scope
from app.services.persistence.schema import AddressCache

CACHE_TTL_SECONDS = 604800  # 完整成功档默认 7 天（env DEALDESK_CACHE_TTL_SECONDS）
CACHE_TTL_PARTIAL_SECONDS = 86400  # 部分/失败档默认 24h（env DEALDESK_CACHE_TTL_PARTIAL_SECONDS）
COMPLETE_MIN_FIELDS = 15  # 冒烟口径（tools/smoke-test.sh MIN_FIELDS）
USAGE_KEY_PREFIX = "usage:"
USAGE_PROVIDER = "usage-counter"


def _env_seconds(name: str, default: int) -> int:
    """读正整数秒数 env；缺失/非法/非正回落默认值（调用时读，便于运维即时生效）。"""
    raw = os.environ.get(name, "").strip()
    try:
        v = int(raw)
    except ValueError:
        return default
    return v if v > 0 else default


def ttl_complete_seconds() -> int:
    """完整成功档 TTL（秒）。"""
    return _env_seconds("DEALDESK_CACHE_TTL_SECONDS", CACHE_TTL_SECONDS)


def ttl_partial_seconds() -> int:
    """部分/失败档 TTL（秒）。"""
    return _env_seconds("DEALDESK_CACHE_TTL_PARTIAL_SECONDS", CACHE_TTL_PARTIAL_SECONDS)


def is_complete(result: dict[str, Any]) -> bool:
    """完整成功判定（见模块 docstring）；结构不认识一律按部分处理（保守取短 TTL）。"""
    if not isinstance(result, dict) or result.get("ok") is not True:
        return False
    if not result.get("primary_provider"):
        return False
    fields = result.get("fields")
    if isinstance(fields, list) and len(fields) >= COMPLETE_MIN_FIELDS:
        return True
    legs = result.get("provider_results")
    if not isinstance(legs, list) or not legs:
        return False
    return all(isinstance(r, dict) and r.get("status") == "ok" for r in legs)


def ttl_for(result: dict[str, Any]) -> int:
    """按结果完整度取该条目的 TTL（秒）。"""
    return ttl_complete_seconds() if is_complete(result) else ttl_partial_seconds()


def normalize_address(address: str) -> str:
    """归一化：strip + lower + 压缩连续空白为单个空格。"""
    return re.sub(r"\s+", " ", (address or "").strip().lower())


def address_hash(address: str) -> str:
    """sha256(归一化地址).hexdigest()。"""
    return hashlib.sha256(normalize_address(address).encode("utf-8")).hexdigest()


def get_cached(address: str) -> dict | None:
    """查缓存。

    返回 {"data": 反序列化后的 run_chain 结果, "fetched_at": float,
           "stale": bool(是否超过该条目所属档 TTL), "complete": bool,
           "ttl_seconds": int}；无条目/反序列化失败返回 None。
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
    complete = is_complete(data)
    ttl = ttl_complete_seconds() if complete else ttl_partial_seconds()
    return {
        "data": data,
        "fetched_at": fetched_at,
        "stale": (time.time() - fetched_at) > ttl,
        "complete": complete,
        "ttl_seconds": ttl,
    }


def put_cached(address: str, result_dict: dict) -> None:
    """写入缓存（upsert），fetched_at=now。

    现状调用方：providers.run_chain 在合并出 ≥1 个字段（ok=True，可能是部分失败）时调用；
    TTL 档位不在写时决定，由 get_cached 读时按结果完整度推导。"""
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


# ---------------- 用量计数（同表，"usage:" 前缀键） ----------------

def _usage_hash(name: str) -> str:
    return USAGE_KEY_PREFIX + name


def _usage_value(data_json: str) -> int:
    try:
        v = json.loads(data_json).get("count", 0)
        return int(v) if isinstance(v, (int, float)) and v > 0 else 0
    except Exception:
        return 0


def usage_count(name: str) -> int:
    """读用量计数（无行返回 0）。name 例：rentcast:2026-11。"""
    with session_scope() as sess:
        row = sess.execute(select(AddressCache.data_json)
                           .where(AddressCache.address_hash == _usage_hash(name))).first()
    return 0 if row is None else _usage_value(row.data_json)


def usage_reserve(name: str, cap: int) -> int | None:
    """原子预占一次用量：计数 < cap 则 +1 并返回新值，已达 cap 返回 None（不改计数）。

    同一事务内加锁读改写（Postgres SELECT … FOR UPDATE；SQLite 写串行），并发请求
    不会一起越过 cap。首行并发插入撞主键时重试一次（第二次走已存在行的加锁更新）；
    仍失败则上抛，调用方据此 fail-closed（不发计费请求）。"""
    key = _usage_hash(name)
    for attempt in (1, 2):
        try:
            return _usage_reserve_once(key, cap)
        except IntegrityError:
            if attempt == 2:
                raise
    raise AssertionError("unreachable")  # pragma: no cover


def _usage_reserve_once(key: str, cap: int) -> int | None:
    now = time.time()
    with session_scope() as sess:
        row = sess.execute(select(AddressCache)
                           .where(AddressCache.address_hash == key)
                           .with_for_update()).scalar_one_or_none()
        used = 0 if row is None else _usage_value(row.data_json)
        if used >= cap:
            return None
        n = used + 1
        if row is None:
            sess.add(AddressCache(address_hash=key, provider=USAGE_PROVIDER,
                                  data_json=json.dumps({"count": n}), fetched_at=now))
        else:
            row.data_json, row.fetched_at = json.dumps({"count": n}), now
    return n
