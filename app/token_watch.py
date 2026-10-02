"""TopHap access token 自愈：剩余有效期 <30 分钟时用 refresh_token 自动换新。

前提（重要）：
  首次真实刷新需要下次 OAuth 授权时持久化 refresh_token：
  tools/tophap_oauth_setup.py 在 exchange_code 返回里有 refresh_token 时
  会写入 .env 的 TOPHAP_REFRESH_TOKEN。历史授权（2026-10-01 及之前）没有
  持久化 refresh_token，因此在下一次 OAuth 授权完成之前，
  ensure_fresh_token() 会因"无 refresh_token"直接返回不刷新——这是预期
  行为，不是 bug。

工作方式：
  - 读 .env 的 TOPHAP_TOKEN_EXPIRES_AT；剩余有效期 >=30 分钟 → 不刷新。
  - 否则用 .env 的 TOPHAP_REFRESH_TOKEN 向 TOPHAP_TOKEN_ENDPOINT 做
    refresh_token grant 换新 access_token；成功后更新 .env 的
    TOPHAP_ACCESS_TOKEN / TOPHAP_TOKEN_EXPIRES_AT；若响应带新的
    refresh_token 则做 rolling 更新（TOPHAP_REFRESH_TOKEN）。
  - 任何失败都返回 {"refreshed": False, "reason": 中文原因}，绝不抛异常。
  - 生产同步由 tools/tophap-auto-refresh.sh 负责：刷新成功后把新 token
    推到 Vercel 环境变量（production）并触发 redeploy。

注意：Secure Vault 按平台设计是 opaque 的（读不回），刷新凭证只存
仓库 .env（gitignored，权限 600），不进 Vault、不进 git、不打印。
"""

from __future__ import annotations

import time

import httpx

from app import tophap

REFRESH_THRESHOLD_SEC = 30 * 60  # 剩余有效期 <30 分钟才刷新
NET_TIMEOUT = 20


def _read_dotenv_map() -> dict:
    """读仓库 .env，返回 {key: value}（只取 TOPHAP_*；失败返回空 dict）。"""
    out: dict = {}
    try:
        path = tophap.dotenv_path()
        if not path.exists():
            return out
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k.startswith("TOPHAP_"):
                out[k] = v
    except Exception:
        pass
    return out


def _expires_at(env: dict) -> int | None:
    try:
        v = int((env.get("TOPHAP_TOKEN_EXPIRES_AT") or "").strip())
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _do_refresh(env: dict, now: int) -> dict:
    refresh_token = (env.get("TOPHAP_REFRESH_TOKEN") or "").strip()
    if not refresh_token:
        return {"refreshed": False,
                "reason": ("无 refresh_token：.env 缺少 TOPHAP_REFRESH_TOKEN。"
                           "需要下次 OAuth 授权时持久化（tools/tophap_oauth_setup.py "
                           "已支持，授权服务器下发即写入），本次无法自动刷新")}
    endpoint = (env.get("TOPHAP_TOKEN_ENDPOINT") or "").strip()
    client_id = (env.get("TOPHAP_CLIENT_ID") or "").strip()
    if not endpoint or not client_id:
        return {"refreshed": False,
                "reason": "缺少 TOPHAP_TOKEN_ENDPOINT 或 TOPHAP_CLIENT_ID，无法发起刷新"}
    # 与 tools/tophap_oauth_setup.py 的 exchange_code 保持一致：
    # form 表单 POST；client_secret 只有 .env 里有才带（动态注册的是 public
    # client，默认无 secret），否则只带 client_id。
    body = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    client_secret = (env.get("TOPHAP_CLIENT_SECRET") or "").strip()
    if client_secret:
        body["client_secret"] = client_secret
    try:
        r = httpx.post(endpoint, data=body, timeout=NET_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        return {"refreshed": False,
                "reason": f"刷新请求失败（网络/连接）：{str(e)[:120]}"}
    if r.status_code != 200:
        return {"refreshed": False,
                "reason": f"授权服务器拒绝刷新（HTTP {r.status_code}）：{r.text[:150]}"}
    try:
        tok = r.json()
    except Exception:
        return {"refreshed": False, "reason": "刷新响应不是合法 JSON"}
    if not isinstance(tok, dict) or not tok.get("access_token"):
        return {"refreshed": False,
                "reason": "刷新响应缺 access_token，放弃更新（旧 token 保留）"}
    updates = {"TOPHAP_ACCESS_TOKEN": tok["access_token"]}
    if tok.get("expires_in"):
        try:
            updates["TOPHAP_TOKEN_EXPIRES_AT"] = str(now + int(tok["expires_in"]))
        except (TypeError, ValueError):
            updates["TOPHAP_TOKEN_EXPIRES_AT"] = str(now + 3600)
    new_refresh = tok.get("refresh_token")
    if new_refresh and str(new_refresh).strip() != refresh_token:
        updates["TOPHAP_REFRESH_TOKEN"] = str(new_refresh).strip()
    tophap.write_dotenv(updates)
    # 同进程内也同步，避免本进程后续调用还用旧 token
    import os
    os.environ.update(updates)
    return {"refreshed": True,
            "reason": "已用 refresh_token 换到新 access_token 并写入 .env",
            "new_expires_at": updates.get("TOPHAP_TOKEN_EXPIRES_AT")}


def _ensure() -> dict:
    env = _read_dotenv_map()
    exp = _expires_at(env)
    if exp is None:
        return {"refreshed": False,
                "reason": ("TOPHAP_TOKEN_EXPIRES_AT 缺失或非法，无法判断有效期，"
                           "未尝试刷新（建议重跑授权脚本写入正确时间戳）")}
    now = int(time.time())
    if exp - now >= REFRESH_THRESHOLD_SEC:
        return {"refreshed": False, "reason": "还够用"}
    return _do_refresh(env, now)


def ensure_fresh_token() -> dict:
    """保证 token 有效：快过期就用 refresh_token 自动换新。

    返回 {"refreshed": bool, "reason": 中文原因}；绝不抛异常。"""
    try:
        return _ensure()
    except Exception as e:  # noqa: BLE001  # 兜底：任何未预料的异常都转成结果
        return {"refreshed": False,
                "reason": f"自愈流程内部异常（未抛给调用方）：{str(e)[:150]}"}
