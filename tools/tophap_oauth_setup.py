#!/usr/bin/env python3
"""TopHap MCP 首次 OAuth 授权脚本（独立运行一次）。

标准流程（MCP Streamable HTTP + OAuth 2.1：RFC 8414 / RFC 9728 / RFC 7591 / PKCE）：
  1. 裸调 MCP endpoint → 401，读 WWW-Authenticate 拿 resource_metadata
  2. 取 Protected Resource Metadata → authorization_servers
  3. 取 Authorization Server Metadata → authorization/token/registration endpoints
  4. 动态注册 client（RFC 7591，public client + PKCE，不产生 client_secret）
  5. 起 localhost 回调，打印授权 URL → 用户在已登录 TopHap 的浏览器打开 → 点 Approve
  6. 回调拿到 code → 换 access_token（+ expires_in）
  7. access_token / 绝对过期时间戳（TOPHAP_TOKEN_EXPIRES_AT，epoch 秒）/
     token_endpoint / client_id → .env（gitignored）
     8. exchange_code 返回里若有 refresh_token → .env（TOPHAP_REFRESH_TOKEN），
        供 app/token_watch.py 的 ensure_fresh_token() 自动刷新（<30 分钟到期时
        用 refresh_token 换新 access_token；server 下发新的 refresh_token 时
        做 rolling 更新）。Secure Vault 按平台设计是 opaque 的（读不回），
        所以刷新凭证只存 .env（gitignored，权限 600），不进 Vault。

用法：
  cd ~/workspace/vertcity/dealdesk && .venv/bin/python tools/tophap_oauth_setup.py
  # 若浏览器打不开 localhost 回调：加 --manual，按提示粘贴跳转 URL 或 code

说明：
  - .env 已 gitignore，权限 600；token 只进 .env，不进 git、不打印。
  - 本脚本不依赖 Secure Vault；vault 相关门槛已按平台 opaque 特性移除。
  - 若授权服务器下发 refresh_token，一并持久化到 .env
    （TOPHAP_REFRESH_TOKEN），app/token_watch.py 会用它自动刷新。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from app.tophap import mcp_url, write_dotenv  # noqa: E402

CALLBACK_PORT = 8765
CALLBACK_PATH = "/callback"


def redirect_uri() -> str:
    """OAuth 回调地址。默认本机 localhost；浏览器与本机不在同一 host 时，
    可设 TOPHAP_REDIRECT_URI（如 https://httpbin.org/get）让浏览器把 code
    回显在公网页面上再读回。code 经 PKCE 绑定，无 verifier 无法换 token，
    回显页看到 code 也无风险。"""
    return os.environ.get("TOPHAP_REDIRECT_URI") or f"http://127.0.0.1:{CALLBACK_PORT}{CALLBACK_PATH}"
USER_TIMEOUT = 10 * 60  # 等用户点 Approve 最长 10 分钟
NET_TIMEOUT = 15


def log(msg: str) -> None:
    print(f"[tophap-oauth] {msg}", flush=True)


def parse_www_authenticate(header_value: str) -> str | None:
    """从 401 的 WWW-Authenticate 头提取 resource_metadata URL（RFC 9728）。"""
    if not header_value:
        return None
    m = re.search(r'resource_metadata="([^"]+)"', header_value)
    return m.group(1) if m else None


def discover_auth_server(mcp: str) -> dict:
    """401 → resource metadata → authorization server metadata。返回含
    authorization_endpoint / token_endpoint / registration_endpoint 的 dict。"""
    log(f"探测 MCP endpoint（期待 401）: {mcp}")
    try:
        r = httpx.post(mcp,
                       json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                             "params": {"protocolVersion": "2024-11-05",
                                        "capabilities": {},
                                        "clientInfo": {"name": "dealdesk-oauth-setup",
                                                       "version": "1.0"}}},
                       headers={"Content-Type": "application/json",
                                "Accept": "application/json, text/event-stream"},
                       timeout=NET_TIMEOUT)
    except Exception as e:
        raise SystemExit(f"连不上 MCP endpoint：{e}")
    rm_url = parse_www_authenticate(r.headers.get("www-authenticate", ""))
    if not rm_url:
        # RFC 9728 回退：mcp host 上的 well-known
        host = urllib.parse.urlparse(mcp)
        rm_url = (f"{host.scheme}://{host.netloc}"
                  "/.well-known/oauth-protected-resource")
        log(f"401 头里没有 resource_metadata，回退 well-known: {rm_url}")
    if r.status_code != 401:
        log(f"注意：裸调返回 HTTP {r.status_code}（非 401），仍尝试继续发现流程")
    try:
        rm = httpx.get(rm_url, params={"resource": mcp},
                       timeout=NET_TIMEOUT).json()
    except Exception as e:
        raise SystemExit(f"取不到 Protected Resource Metadata（{rm_url}）：{e}")
    servers = rm.get("authorization_servers") or []
    if not servers:
        raise SystemExit("resource metadata 里没有 authorization_servers，无法继续")
    issuer = servers[0].rstrip("/")
    log(f"授权服务器：{issuer}")
    as_meta = None
    for path in ("/.well-known/oauth-authorization-server",
                 "/.well-known/openid-configuration"):
        try:
            cand = httpx.get(issuer + path, timeout=NET_TIMEOUT)
            if cand.status_code == 200:
                as_meta = cand.json()
                log(f"拿到 Authorization Server Metadata（{path}）")
                break
        except Exception:
            continue
    if not as_meta or not as_meta.get("authorization_endpoint"):
        raise SystemExit("取不到 authorization_endpoint，无法继续")
    return as_meta


def register_client(as_meta: dict) -> dict:
    """RFC 7591 动态注册 public client（PKCE，无 client_secret）。"""
    reg_ep = as_meta.get("registration_endpoint")
    if not reg_ep:
        cid = os.environ.get("TOPHAP_CLIENT_ID", "").strip()
        if cid:
            log("无动态注册端点，使用环境变量里的 TOPHAP_CLIENT_ID")
            return {"client_id": cid}
        raise SystemExit("授权服务器不支持动态注册，且未提供 TOPHAP_CLIENT_ID")
    body = {
        "client_name": "DealDesk",
        "redirect_uris": [redirect_uri()],
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": "openid profile email",
    }
    try:
        r = httpx.post(reg_ep, json=body, timeout=NET_TIMEOUT)
        if r.status_code >= 400 and "scope" in body:
            body.pop("scope")  # 有的 server 不接受 scope，裸重试一次
            r = httpx.post(reg_ep, json=body, timeout=NET_TIMEOUT)
        r.raise_for_status()
    except Exception as e:
        raise SystemExit(f"client 注册失败：{e}")
    reg = r.json()
    if not reg.get("client_id"):
        raise SystemExit(f"注册返回缺 client_id：{str(reg)[:200]}")
    if reg.get("client_secret"):
        log("server 下发了 client_secret，但本设计不做静默刷新（Vault opaque 读不回），"
            "忽略它；access token 过期后重跑本脚本即可")
    log(f"client 注册成功（client_id={reg['client_id'][:12]}…）")
    return reg


def pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def build_authorize_url(as_meta: dict, client_id: str, challenge: str,
                        state: str, scope: str | None = None) -> str:
    # RFC 8707：authorize 必须带 resource，否则 AS 下发 opaque token，
    # MCP 端 401 "no token payload"（2026-09-28 实测）。
    q = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri(),
        "resource": mcp_url(),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    if scope:
        q["scope"] = scope
    return as_meta["authorization_endpoint"] + "?" + urllib.parse.urlencode(q)


class _CallbackHandler(BaseHTTPRequestHandler):
    code: str | None = None
    state: str | None = None
    error: str | None = None

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        _CallbackHandler.code = (qs.get("code") or [None])[0]
        _CallbackHandler.state = (qs.get("state") or [None])[0]
        _CallbackHandler.error = (qs.get("error") or [None])[0]
        body = ("<html><body><h2>授权成功</h2><p>可以关掉这个页面，"
                "回到终端继续。</p></body></html>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # 安静
        pass


def wait_for_code(manual: bool) -> str:
    """等用户点 Approve。localhost 回调优先；--manual 则提示粘贴。"""
    if manual:
        log("--manual 模式：完成浏览器授权后，把跳转到的完整 URL 或 code 粘进来")
        pasted = input("URL 或 code> ").strip()
        if "code=" in pasted:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query)
            code = (qs.get("code") or [None])[0]
        else:
            code = pasted
        if not code:
            raise SystemExit("没拿到 code，中止")
        return code
    server = HTTPServer(("127.0.0.1", CALLBACK_PORT), _CallbackHandler)
    server.timeout = 1
    deadline = time.time() + USER_TIMEOUT
    log(f"localhost 回调监听中（127.0.0.1:{CALLBACK_PORT}，最多等 10 分钟）…")
    while time.time() < deadline:
        server.handle_request()
        if _CallbackHandler.error:
            raise SystemExit(f"授权被拒：{_CallbackHandler.error}")
        if _CallbackHandler.code:
            return _CallbackHandler.code
    raise SystemExit("等用户 Approve 超时（10 分钟），中止")


def exchange_code(as_meta: dict, client_id: str, client_secret: str | None,
                  code: str, verifier: str) -> dict:
    # RFC 8707：token 交换也必须带 resource（与 authorize 一致），否则 401。
    body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri(),
        "resource": mcp_url(),
        "client_id": client_id,
        "code_verifier": verifier,
    }
    if client_secret:
        body["client_secret"] = client_secret
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
    manual = "--manual" in sys.argv
    mcp = mcp_url()

    as_meta = discover_auth_server(mcp)
    reg = register_client(as_meta)
    client_id = reg["client_id"]
    client_secret = reg.get("client_secret")

    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    auth_url = build_authorize_url(as_meta, client_id, challenge, state,
                                   scope="openid profile email")

    print()
    print("=" * 70)
    print("第 1 步（唯一需要你动手的一步）：在已登录 TopHap 的浏览器打开下面这个 URL，")
    print("点 Approve 授权给 DealDesk。")
    print("=" * 70)
    print(auth_url)
    print("=" * 70)
    print()

    code = wait_for_code(manual)
    got_state = _CallbackHandler.state
    if got_state and got_state != state:
        raise SystemExit("state 不匹配（疑似 CSRF），中止")
    log("拿到授权码，换 token…")
    tok = exchange_code(as_meta, client_id, client_secret, code, verifier)

    # 直接写 .env（不走 Vault：Secure Vault 按平台设计是 opaque 的，读不回）。
    # refresh_token 若下发则一并持久化（TOPHAP_REFRESH_TOKEN），供
    # app/token_watch.py 自动刷新；若 server 没下发则跳过。
    updates = {
        "TOPHAP_MCP_URL": mcp,
        "TOPHAP_ACCESS_TOKEN": tok["access_token"],
        "TOPHAP_TOKEN_ENDPOINT": as_meta["token_endpoint"],
        "TOPHAP_CLIENT_ID": client_id,
    }
    if tok.get("refresh_token"):
        updates["TOPHAP_REFRESH_TOKEN"] = tok["refresh_token"]
        log("授权服务器下发了 refresh_token，已写入 .env（TOPHAP_REFRESH_TOKEN）")
    else:
        log("授权服务器未下发 refresh_token（TopHap 目前仅下发 access_token）："
            "将来下发后可再跑一次本脚本持久化，app/token_watch.py 才能自愈")
    if tok.get("expires_in"):
        try:
            updates["TOPHAP_TOKEN_EXPIRES_AT"] = str(
                int(time.time()) + int(tok["expires_in"]))
        except (TypeError, ValueError):
            log(f"expires_in 非法（{tok['expires_in']!r}），跳过过期时间戳")
    write_dotenv(updates)
    log(".env 已写入：access token＋绝对过期时间戳（TOPHAP_TOKEN_EXPIRES_AT，epoch 秒）")

    print()
    print("授权完成。下一步：在 shell 里执行")
    print("  export TOPHAP_ENABLED=1")
    print("然后跑一次 intake，或调 GET /api/tophap/status 验证连通性。")


if __name__ == "__main__":
    main()
