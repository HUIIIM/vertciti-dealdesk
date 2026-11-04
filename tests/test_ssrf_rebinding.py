"""SSRF：DNS 重绑定（#73 / 审查 #53）。

_is_public_url 解析到公网之后，httpx 连接时再解析一次，攻击者可在两次之间把域名改指内网。
连接后复核 httpx 实际连上的对端 IP：非公网即中止，响应体不读取、不回显。
"""
from __future__ import annotations

import pytest

from app.services import research_pipeline as rp

URL = "https://rebind.example/listing"


class _Stream:
    def __init__(self, ip: str) -> None:
        self._ip = ip

    def get_extra_info(self, name: str):  # noqa: ANN201 — 模拟 httpcore 网络流接口
        return (self._ip, 443) if name == "server_addr" else None


class _Resp:
    def __init__(self, peer: str, body: bytes = b"<html><body>3 bed 2 bath</body></html>") -> None:
        self.status_code, self.url, self.encoding, self.headers = 200, URL, "utf-8", {}
        self.extensions = {"network_stream": _Stream(peer)}
        self.read = False
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_bytes(self, chunk_size=65536):
        self.read = True
        yield self._body


@pytest.fixture()
def no_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(k, raising=False)


def _serve(monkeypatch: pytest.MonkeyPatch, resp: _Resp) -> None:
    # 连接前检查放行（模拟第一次解析到公网），连接时对端是 resp 里的 IP（模拟重绑定后的第二次解析）
    monkeypatch.setattr(rp, "_is_public_url", lambda u: (True, ""))
    monkeypatch.setattr(rp, "robots_allowed", lambda u: (True, ""))
    monkeypatch.setattr(rp.httpx, "stream", lambda *a, **k: resp)


@pytest.mark.parametrize("peer", ["169.254.169.254", "127.0.0.1", "10.0.0.5", "::1", "fd00::1"])
def test_rebinding_to_internal_peer_is_blocked(monkeypatch, no_proxy_env, peer):
    resp = _Resp(peer, body=b"SECRET-METADATA")
    _serve(monkeypatch, resp)
    out = rp.fetch_page(URL, [])
    assert out["ok"] is False and "非公网 IP" in out["note"] and peer in out["note"]
    assert resp.read is False and "SECRET" not in str(out)  # 内网响应体一字未读


def test_public_peer_is_fetched(monkeypatch, no_proxy_env):
    _serve(monkeypatch, _Resp("93.184.216.34"))
    out = rp.fetch_page(URL, [])
    assert out["ok"] is True and "3 bed" in out["text"]


def test_peer_check_skipped_behind_proxy(monkeypatch):
    # 走代理时对端是代理本身（可能是内网地址），目标由代理解析：不做对端复核，连接前检查仍在
    monkeypatch.setenv("HTTPS_PROXY", "http://10.0.0.1:3128")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    _serve(monkeypatch, _Resp("10.0.0.1"))
    assert rp.fetch_page(URL, [])["ok"] is True
