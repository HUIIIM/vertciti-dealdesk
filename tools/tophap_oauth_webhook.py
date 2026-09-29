#!/usr/bin/env python3
"""TopHap MCP OAuth via public webhook redirect（浏览器与脚本不在同一台机器时用）。

tophap_oauth_setup.py 的变体：redirect_uri 改用 https://webhook.site/<uuid>，
浏览器（另一台 VM，已登录 TopHap）点 Approve 后 TopHap 302 到 webhook.site，
本脚本轮询 webhook.site API 取回 ?code=，再换 token 写 .env。

流程：
  1. 复用 tophap_oauth_setup.discover_auth_server / pkce_pair
  2. RFC 7591 注册 client，redirect_uris=[WEBHOOK_URL]
  3. 打印 AUTHORIZE_URL_BEGIN/END → 由浏览器任务打开并点 Approve
  4. 轮询 webhook.site 等回调 → 换 token → 写 .env（逻辑同原脚本）

用法：
  cd ~/workspace/vertcity/dealdesk && .venv/bin/python -u tools/tophap_oauth_webhook.py
"""

from __future__ import annotations

import secrets
import sys
import time
import urllib.parse
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from app.tophap import mcp_url, write_dotenv  # noqa: E402
import tophap_oauth_setup as base  # noqa: E402  (同目录脚本，import 只定义函数)

WEBHOOK_UUID = "41b03171-ef9a-4b03-a5dd-08a0b9938f8c"
REDIRECT_URI = f"https://webhook.site/{WEBHOOK_UUID}"
# RFC 8707：MCP 要求 authorize＋token 两步都带 resource，否则 AS 下发的 token
# 与 MCP resource server 的期望受众不一致（实测：不带会被 401 "no token payload"）
RESOURCE = "https://mcp.tophap.com/api/mcp"
NET_TIMEOUT = 15
WAIT_SECS = 8 * 60


def register_client(as_meta: dict, redirect_uri: str) -> dict:
    reg_ep = as_meta.get("registration_endpoint")
    if not reg_ep:
        raise SystemExit("授权服务器不支持动态注册，无法继续")
    body = {
        "client_name": "DealDesk",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": "openid profile email",
    }
    try:
        r = httpx.post(reg_ep, json=body, timeout=NET_TIMEOUT)
        if r.status_code >= 400:
            body.pop("scope", None)
            r = httpx.post(reg_ep, json=body, timeout=NET_TIMEOUT)
        r.raise_for_status()
    except Exception as e:
        raise SystemExit(f"client 注册失败：{e}")
    reg = r.json()
    if not reg.get("client_id"):
        raise SystemExit(f"注册返回缺 client_id：{str(reg)[:200]}")
    base.log(f"client 注册成功（client_id={reg['client_id'][:12]}…）")
    return reg


def build_auth_url(as_meta: dict, client_id: str, challenge: str,
                   state: str, redirect_uri: str) -> str:
    q = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "resource": RESOURCE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "scope": "openid profile email",
    }
    return as_meta["authorization_endpoint"] + "?" + urllib.parse.urlencode(q)


def wait_for_code_webhook(state: str) -> str:
    url = f"https://webhook.site/token/{WEBHOOK_UUID}/requests?sorting=newest"
    deadline = time.time() + WAIT_SECS
    seen: set[str] = set()
    base.log(f"等待 webhook 回调（{REDIRECT_URI}，最多 {WAIT_SECS // 60} 分钟）…")
    while time.time() < deadline:
        try:
            items = httpx.get(url, timeout=NET_TIMEOUT).json().get("data", [])
        except Exception as e:
            base.log(f"轮询 webhook.site 失败：{e}，5 秒后重试")
            time.sleep(5)
            continue
        for it in items:
            uid = it.get("uuid")
            if uid in seen:
                continue
            seen.add(uid)
            query = it.get("query") or {}
            code = query.get("code")
            if code:
                got_state = query.get("state")
                if got_state and got_state != state:
                    base.log(f"跳过旧回调（state={str(got_state)[:10]}… 与本轮不符）")
                    continue
                base.log(f"收到回调（state={str(got_state)[:10]}…）")
                return code
        time.sleep(5)
    raise SystemExit("等 webhook 回调超时，中止")


def exchange(as_meta: dict, client_id: str, code: str,
             verifier: str, redirect_uri: str) -> dict:
    body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "resource": RESOURCE,
        "client_id": client_id,
        "code_verifier": verifier,
    }
    try:
        r = httpx.post(as_meta["token_endpoint"], data=body, timeout=NET_TIMEOUT)
    except Exception as e:
        raise SystemExit(f"换 token 连不上：{e}")
    if r.status_code != 200:
        raise SystemExit(f"换 token 失败（HTTP {r.status_code}）：{r.text[:300]}")
    tok = r.json()
    if not tok.get("access_token"):
        raise SystemExit(f"token 响应缺 access_token：{sorted(tok.keys())}")
    return tok


def main() -> None:
    mcp = mcp_url()
    as_meta = base.discover_auth_server(mcp)
    reg = register_client(as_meta, REDIRECT_URI)
    client_id = reg["client_id"]

    verifier, challenge = base.pkce_pair()
    state = secrets.token_urlsafe(16)
    auth_url = build_auth_url(as_meta, client_id, challenge, state, REDIRECT_URI)

    print("AUTHORIZE_URL_BEGIN", flush=True)
    print(auth_url, flush=True)
    print("AUTHORIZE_URL_END", flush=True)

    code = wait_for_code_webhook(state)
    base.log("拿到授权码，换 token…")
    tok = exchange(as_meta, client_id, code, verifier, REDIRECT_URI)

    updates = {
        "TOPHAP_MCP_URL": mcp,
        "TOPHAP_ACCESS_TOKEN": tok["access_token"],
        "TOPHAP_TOKEN_ENDPOINT": as_meta["token_endpoint"],
        "TOPHAP_CLIENT_ID": client_id,
    }
    if tok.get("expires_in"):
        try:
            updates["TOPHAP_TOKEN_EXPIRES_AT"] = str(
                int(time.time()) + int(tok["expires_in"]))
        except (TypeError, ValueError):
            base.log(f"expires_in 非法（{tok['expires_in']!r}），跳过过期时间戳")
    write_dotenv(updates)
    base.log(".env 已写入：access token＋绝对过期时间戳")
    print("OAUTH_DONE", flush=True)


if __name__ == "__main__":
    main()
