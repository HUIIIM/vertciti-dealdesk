"""app/token_watch.py 单元测试（全部 mock，不碰真实 token/网络）。"""
from __future__ import annotations

import json
import os
import time

import httpx
import pytest

from app import tophap
from app import token_watch
from app.services import http_capped


class _FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)
        self.headers = {"content-type": "application/json"}
        self.encoding = "utf-8"

    def json(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_bytes(self, chunk_size=65536):
        data = self.text.encode()
        for i in range(0, len(data), chunk_size):
            yield data[i:i + chunk_size]


def _patch_http(monkeypatch, fake_post):
    """生产刷新已改 http_capped.post_capped（httpx.stream）：
    把 fake_post 适配成 stream 替身，fake 本体逻辑不变。"""
    def fake_stream(method, url, **kwargs):
        return fake_post(url, data=kwargs.get("data"),
                         timeout=kwargs.get("timeout"))
    monkeypatch.setattr(http_capped.httpx, "stream", fake_stream)


def _write_env(path, mapping):
    path.write_text("".join(f"{k}={v}\n" for k, v in mapping.items()))


@pytest.fixture()
def env_file(tmp_path, monkeypatch):
    """把 tophap.dotenv_path() 指向临时 .env，测试互不干扰。"""
    p = tmp_path / ".env"
    monkeypatch.setattr(tophap, "dotenv_path", lambda: p)
    return p


def _base_env(**over):
    now = int(time.time())
    d = {
        "TOPHAP_MCP_URL": "https://mcp.tophap.com/api/mcp",
        "TOPHAP_ACCESS_TOKEN": "tok-old",
        "TOPHAP_TOKEN_ENDPOINT": "https://auth.example/token",
        "TOPHAP_CLIENT_ID": "cid-123",
        "TOPHAP_TOKEN_EXPIRES_AT": str(now + 3600),
        "TOPHAP_ENABLED": "1",
    }
    d.update(over)
    return d


def test_no_refresh_when_still_valid(env_file, monkeypatch):
    _write_env(env_file, _base_env())

    def _boom(*a, **k):
        raise AssertionError("还够用时不应发起任何 HTTP 请求")

    _patch_http(monkeypatch, _boom)
    r = token_watch.ensure_fresh_token()
    assert r == {"refreshed": False, "reason": "还够用"}


def test_refresh_when_expiring_updates_dotenv(env_file, monkeypatch):
    now = int(time.time())
    _write_env(env_file, _base_env(
        TOPHAP_TOKEN_EXPIRES_AT=str(now - 100),  # 已过期
        TOPHAP_REFRESH_TOKEN="ref-old"))
    # 预置环境变量（monkeypatch 会在测试后还原，避免污染后续测试会话）
    monkeypatch.setenv("TOPHAP_ACCESS_TOKEN", "tok-old")
    monkeypatch.setenv("TOPHAP_TOKEN_EXPIRES_AT", str(now - 100))
    monkeypatch.setenv("TOPHAP_REFRESH_TOKEN", "ref-old")

    def _fake_post(url, data=None, timeout=None):
        assert data["grant_type"] == "refresh_token"
        assert data["refresh_token"] == "ref-old"
        assert data["client_id"] == "cid-123"
        assert "client_secret" not in data  # 没配 secret 就只带 client_id
        return _FakeResp(200, {"access_token": "tok-new",
                               "expires_in": 3600,
                               "refresh_token": "ref-new"})

    _patch_http(monkeypatch, _fake_post)
    r = token_watch.ensure_fresh_token()
    assert r["refreshed"] is True

    content = env_file.read_text()
    assert "TOPHAP_ACCESS_TOKEN=tok-new" in content
    assert "TOPHAP_REFRESH_TOKEN=ref-new" in content  # rolling 更新
    line = [l for l in content.splitlines()
            if l.startswith("TOPHAP_TOKEN_EXPIRES_AT=")][0]
    exp = int(line.split("=", 1)[1])
    assert now + 3500 <= exp <= now + 3700
    # 其他键原地保留
    assert "TOPHAP_ENABLED=1" in content
    # 权限 600
    assert oct(os.stat(env_file).st_mode & 0o777) == "0o600"
    # 同进程环境变量同步（token_watch 内部 os.environ.update）
    assert os.environ["TOPHAP_ACCESS_TOKEN"] == "tok-new"
    assert os.environ["TOPHAP_REFRESH_TOKEN"] == "ref-new"


def test_refresh_failure_returns_reason_no_exception(env_file, monkeypatch):
    now = int(time.time())
    _write_env(env_file, _base_env(
        TOPHAP_TOKEN_EXPIRES_AT=str(now + 600),  # 10 分钟后到期 → 触发刷新
        TOPHAP_REFRESH_TOKEN="ref-old"))

    def _fake_post(*a, **k):
        return _FakeResp(400, {"error": "invalid_grant"})

    _patch_http(monkeypatch, _fake_post)
    r = token_watch.ensure_fresh_token()  # 不抛异常
    assert r["refreshed"] is False
    assert "拒绝" in r["reason"] or "400" in r["reason"]
    # 失败时旧值保留
    assert "TOPHAP_ACCESS_TOKEN=tok-old" in env_file.read_text()


def test_refresh_network_error_no_exception(env_file, monkeypatch):
    _write_env(env_file, _base_env(
        TOPHAP_TOKEN_EXPIRES_AT=str(int(time.time()) - 10),
        TOPHAP_REFRESH_TOKEN="ref-old"))

    def _fake_post(*a, **k):
        raise httpx.ConnectError("boom")

    _patch_http(monkeypatch, _fake_post)
    r = token_watch.ensure_fresh_token()
    assert r["refreshed"] is False
    assert r["reason"]  # 中文原因非空


def test_no_refresh_token_returns_chinese_reason(env_file, monkeypatch):
    _write_env(env_file, _base_env(
        TOPHAP_TOKEN_EXPIRES_AT=str(int(time.time()) + 600)))

    def _boom(*a, **k):
        raise AssertionError("无 refresh_token 时不应发起 HTTP 请求")

    _patch_http(monkeypatch, _boom)
    r = token_watch.ensure_fresh_token()
    assert r["refreshed"] is False
    assert "无 refresh_token" in r["reason"]


def test_missing_expires_at_no_refresh(env_file, monkeypatch):
    d = _base_env(TOPHAP_REFRESH_TOKEN="ref-old")
    del d["TOPHAP_TOKEN_EXPIRES_AT"]
    _write_env(env_file, d)

    def _boom(*a, **k):
        raise AssertionError("时间戳缺失时不应发起 HTTP 请求")

    _patch_http(monkeypatch, _boom)
    r = token_watch.ensure_fresh_token()
    assert r["refreshed"] is False
    assert "TOPHAP_TOKEN_EXPIRES_AT" in r["reason"]
