"""vm_push 失败证据保全：driver 原文落盘、令牌原值脱敏、文件名带 rc。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import tophap_vm_push  # noqa: E402

BLOCK = {
    "TOPHAP_ACCESS_TOKEN": "access-SECRET-123",
    "TOPHAP_REFRESH_TOKEN": "refresh-SECRET-456",
    "TOPHAP_TOKEN_EXPIRES_AT": "1799999999",
}


def test_failure_evidence_redacts_tokens_and_preserves_output(tmp_path, monkeypatch):
    monkeypatch.setattr(tophap_vm_push, "ROOT", tmp_path)
    out = (
        "CREATED ocid1.command.x\n"
        "STATE FAILED\n"
        "driver saw access-SECRET-123 and refresh-SECRET-456 in env\n"
        "PUSH_DONE missing\n"
    )
    name = tophap_vm_push.preserve_failure_evidence(out, 4, BLOCK)
    assert re.fullmatch(r"\.tophap-vm-push-failure-\d{8}T\d{6}Z-rc4\.log", name)
    text = (tmp_path / name).read_text()
    assert "access-SECRET-123" not in text
    assert "refresh-SECRET-456" not in text
    assert text.count("[redacted]") == 2
    assert "STATE FAILED" in text
    assert "CREATED ocid1.command.x" in text


def test_failure_evidence_ignores_empty_secret_values(tmp_path, monkeypatch):
    monkeypatch.setattr(tophap_vm_push, "ROOT", tmp_path)
    block = {"TOPHAP_ACCESS_TOKEN": "", "TOPHAP_REFRESH_TOKEN": ""}
    out = "plain driver output, no secrets\n"
    name = tophap_vm_push.preserve_failure_evidence(out, 0, block)
    assert (tmp_path / name).read_text() == out


def test_failure_evidence_missing_keys_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(tophap_vm_push, "ROOT", tmp_path)
    out = "boom\n"
    name = tophap_vm_push.preserve_failure_evidence(out, 5, {})
    assert name.endswith("-rc5.log")
    assert (tmp_path / name).read_text() == out
