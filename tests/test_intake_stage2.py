"""截图 intake Stage 2 测试：取原图端点 + extracted 回写端点契约.

全部走 TestClient + tmp pending 目录，不碰公网、不碰真实队列。
形态沿用 tests/test_intake.py 截图段（monkeypatch PENDING_DIR）。
"""

from __future__ import annotations

import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from app import image_intake
from app.main import app

client = TestClient(app)

PNG_1x1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)

FIELD = {"key": "asking_price", "label": "挂牌价", "value": 485000,
         "display": "$485,000", "source": "screenshot",
         "fetched_at": "2026-11-23 10:00", "confidence": "中",
         "seller_claimed": True, "claim_label": "截图提取",
         "note": "待验证", "status": "filled"}


def _tmp_pending(monkeypatch, tmp_path):
    monkeypatch.setattr(image_intake, "PENDING_DIR", str(tmp_path / "pending"))


def _make_task(monkeypatch, tmp_path) -> str:
    _tmp_pending(monkeypatch, tmp_path)
    r = client.post("/api/wb/intake/image",
                    files={"file": ("shot.png", io.BytesIO(PNG_1x1), "image/png")})
    assert r.status_code == 200, r.text
    return r.json()["task_id"]


def _payload(**over):
    d = {"mode": "screenshot", "filename": "shot.png",
         "fields": [dict(FIELD)], "raw_text": "List Price $485,000",
         "deal_type": "residential", "fetched_at": "2026-11-23 10:00"}
    d.update(over)
    return d


# ---------------- 取原图端点 ----------------

def test_original_roundtrip(monkeypatch, tmp_path):
    tid = _make_task(monkeypatch, tmp_path)
    r = client.get(f"/api/wb/intake/original/{tid}")
    assert r.status_code == 200, r.text
    assert r.content == PNG_1x1
    assert r.headers["content-type"] == "image/png"


def test_original_unknown_task_404(monkeypatch, tmp_path):
    _tmp_pending(monkeypatch, tmp_path)
    r = client.get("/api/wb/intake/original/" + "0" * 32)
    assert r.status_code == 404


def test_original_rejects_bad_task_id(monkeypatch, tmp_path):
    _tmp_pending(monkeypatch, tmp_path)
    r = client.get("/api/wb/intake/original/zz-not-a-task")
    assert r.status_code == 400
    # 穿越形态：不得逃出 PENDING_DIR
    r2 = client.get("/api/wb/intake/original/..%2f..%2fetc")
    assert r2.status_code in (400, 404)
    with pytest.raises(ValueError):
        image_intake.get_original("../../etc/passwd")


# ---------------- 回写端点 ----------------

def test_extracted_write_then_read(monkeypatch, tmp_path):
    tid = _make_task(monkeypatch, tmp_path)
    r = client.post(f"/api/wb/intake/extracted/{tid}",
                    json=_payload(extra_key="passthrough"))
    assert r.status_code == 200, r.text
    assert r.json() == {"task_id": tid, "status": "done"}
    r2 = client.get(f"/api/wb/intake/extracted/{tid}")
    assert r2.status_code == 200, r2.text
    d = r2.json()
    assert d["fields"][0]["value"] == 485000
    assert d["extra_key"] == "passthrough"  # 余键透传
    assert "quality_gate" in d  # 取回时现跑附门


def test_extracted_strips_quality_gate_keys(monkeypatch, tmp_path):
    tid = _make_task(monkeypatch, tmp_path)
    r = client.post(f"/api/wb/intake/extracted/{tid}", json=_payload(
        quality_gate={"verdict": "SENTINEL"}, quality_gate_error="SENTINEL"))
    assert r.status_code == 200, r.text
    ep = os.path.join(image_intake.PENDING_DIR, tid, "extracted.json")
    with open(ep, encoding="utf-8") as f:
        stored = json.load(f)
    # 生产者自带的两键剥离、不落盘（取回时现跑 attach_quality_gate）
    assert "quality_gate" not in stored
    assert "quality_gate_error" not in stored


def test_extracted_contract_rejects(monkeypatch, tmp_path):
    tid = _make_task(monkeypatch, tmp_path)
    # fields 缺失
    r = client.post(f"/api/wb/intake/extracted/{tid}", json={"raw_text": "x"})
    assert r.status_code == 400
    # fields 非 list
    r = client.post(f"/api/wb/intake/extracted/{tid}", json={"fields": "nope"})
    assert r.status_code == 400
    # tenants 在位非 list
    r = client.post(f"/api/wb/intake/extracted/{tid}",
                    json=_payload(tenants="nope"))
    assert r.status_code == 400
    # 体非对象（JSON 数组）
    r = client.post(f"/api/wb/intake/extracted/{tid}", json=[1, 2, 3])
    assert r.status_code == 400
    # 非法 JSON 原始体
    r = client.post(f"/api/wb/intake/extracted/{tid}",
                    content=b"{not json",
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 400


def test_extracted_unknown_task_404(monkeypatch, tmp_path):
    _tmp_pending(monkeypatch, tmp_path)
    r = client.post("/api/wb/intake/extracted/" + "0" * 32, json=_payload())
    assert r.status_code == 404


def test_extracted_size_limits_double_check(monkeypatch, tmp_path):
    tid = _make_task(monkeypatch, tmp_path)
    # 路由层：原始体 >2MB 先判 400（不解析）
    raw = json.dumps({"fields": [], "pad": "x" * (2 * 1024 * 1024)}).encode()
    assert len(raw) > 2 * 1024 * 1024
    r = client.post(f"/api/wb/intake/extracted/{tid}", content=raw,
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    # 服务层：序列化 >2MB 同样拒绝（双重判）
    big = {"fields": [{"key": "raw_text", "value": "x" * (2 * 1024 * 1024)}]}
    with pytest.raises(ValueError):
        image_intake.save_extracted(tid, big)


def test_extracted_idempotent_overwrite_manifest_untouched(monkeypatch, tmp_path):
    tid = _make_task(monkeypatch, tmp_path)
    mp = os.path.join(image_intake.PENDING_DIR, tid, "manifest.json")
    with open(mp, "rb") as f:
        manifest_before = f.read()
    r1 = client.post(f"/api/wb/intake/extracted/{tid}", json=_payload())
    assert r1.status_code == 200, r1.text
    v2 = _payload()
    v2["fields"] = [dict(FIELD, value=490000)]
    r2 = client.post(f"/api/wb/intake/extracted/{tid}", json=v2)
    assert r2.status_code == 200, r2.text
    # 幂等覆盖：取回为第二次内容
    d = client.get(f"/api/wb/intake/extracted/{tid}").json()
    assert d["fields"][0]["value"] == 490000
    # 不改 manifest（done 由 list_tasks 派生）
    with open(mp, "rb") as f:
        assert f.read() == manifest_before
    tasks = client.get("/api/wb/intake/pending").json()["tasks"]
    assert any(t["task_id"] == tid and t["status"] == "done" for t in tasks)
