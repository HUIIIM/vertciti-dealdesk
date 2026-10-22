"""v2 服务层的拒绝路径：坏输入一律给出中文、可操作的错误（InvalidInputError → 422 / NotFound → 404 /
Conflict → 409），状态不被半途改坏。正常路径见 test_v2_api.py。"""

from __future__ import annotations

import pytest

from app.domain import uw_commercial
from app.services.v2 import deals, evidence, settings, workflow
from app.services.v2.errors import ConflictError, InvalidInputError, NotFoundError

COM = uw_commercial.example_39_main()


@pytest.fixture
def deal(tmp_path, monkeypatch):
    monkeypatch.setenv("DEALDESK_DB", str(tmp_path / "svc.db"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DEALDESK_AUTH", raising=False)
    return deals.create_deal("S", "commercial", address="1 St", kill=[])


# ---------------------------------------------------------------- 交易与版本
def test_create_and_update_deal_rejections(deal):
    with pytest.raises(InvalidInputError, match="赛道"):
        deals.create_deal("x", "office")
    with pytest.raises(InvalidInputError, match="名称"):
        deals.create_deal("  ", "commercial")
    with pytest.raises(InvalidInputError, match="阈值"):
        deals.create_deal("x", "commercial", kill=[{"metric": "dscr", "op": "<", "threshold": "1"}])
    with pytest.raises(InvalidInputError, match="stage"):
        deals.update_deal(deal["id"], {"stage": "closing"})  # 阶段只能走关卡
    with pytest.raises(InvalidInputError):
        deals.update_deal(deal["id"], {"kill_criteria": [{"metric": "nope", "op": "<", "threshold": 1}]})
    with pytest.raises(NotFoundError):
        deals.update_deal(99999, {"name": "y"})


def test_kill_criteria_change_is_logged_and_archive_hides(deal):
    crit = [{"metric": "dscr", "op": "<", "threshold": 1.2}]
    out = deals.update_deal(deal["id"], {"kill_criteria": crit})
    assert out["kill_criteria"][0]["threshold"] == 1.2
    kinds = [e["kind"] for e in deals.events(deal["id"])]
    assert "kill_criteria_changed" in kinds  # 事后改门槛必须留痕
    deals.archive_deal(deal["id"])
    assert all(d["id"] != deal["id"] for d in deals.list_deals())


def test_versions_bad_input_and_missing(deal):
    with pytest.raises(InvalidInputError):
        deals.save_version(deal["id"], {"property": "not a dict"})
    v1 = deals.save_version(deal["id"], COM)
    v2 = deals.save_version(deal["id"], COM, "复核后")
    assert v1["run_id"] == v2["run_id"]  # 同输入同运行编号（可复现）
    assert [v["version_no"] for v in deals.list_versions(deal["id"])] == [2, 1]
    assert "detail" not in deals.get_version(deal["id"], v1["id"], with_detail=False)["outputs"]
    with pytest.raises(NotFoundError):
        deals.get_version(deal["id"], 99999)
    with pytest.raises(NotFoundError):
        deals.get_run("nope")


# ---------------------------------------------------------------- 流程
def test_stage_task_and_approval_rejections(deal):
    did = deal["id"]
    with pytest.raises(InvalidInputError):
        workflow.advance(did, "mars")
    with pytest.raises(ConflictError):
        workflow.advance(did, "closing")  # 不能跳阶段
    with pytest.raises(InvalidInputError, match="标题"):
        workflow.add_task(did, " ")
    with pytest.raises(InvalidInputError, match="阶段"):
        workflow.add_task(did, "t", stage="mars")
    t = workflow.add_task(did, "核对租约", assignee="miao", due="2026-11-01")
    with pytest.raises(InvalidInputError):
        workflow.update_task(did, t["id"], {"stage": "closing"})
    with pytest.raises(InvalidInputError):
        workflow.update_task(did, t["id"], {"status": "maybe"})
    with pytest.raises(NotFoundError):
        workflow.update_task(did, 99999, {"status": "done"})
    assert workflow.update_task(did, t["id"], {"status": "done"})["status"] == "done"
    assert [e["kind"] for e in deals.events(did)][0] == "task_done"

    with pytest.raises(InvalidInputError, match="类型"):
        workflow.request_approval(did, "bribe", "x")
    with pytest.raises(InvalidInputError, match="金额"):
        workflow.request_approval(did, "payment", "定金")
    a = workflow.request_approval(did, "general", "", note="请批")
    assert a["title"] == "general"
    done = workflow.decide_approval(did, a["id"], approve=False, note="资料不全")
    assert done["status"] == "rejected" and "资料不全" in done["note"]
    with pytest.raises(ConflictError, match="驳回"):
        workflow.decide_approval(did, a["id"], approve=True)
    with pytest.raises(NotFoundError):
        workflow.decide_approval(did, 99999, approve=True)
    assert len(workflow.list_approvals(did)) == 1


def test_documents_and_decisions_rejections(deal, monkeypatch):
    did = deal["id"]
    with pytest.raises(InvalidInputError, match="为空"):
        workflow.upload_document(did, "a.pdf", "application/pdf", b"")
    monkeypatch.setattr(workflow, "MAX_DOC_BYTES", 4)
    with pytest.raises(InvalidInputError, match="上限"):
        workflow.upload_document(did, "a.pdf", "application/pdf", b"12345")
    doc = workflow.upload_document(did, "", "", b"1234")
    assert doc["filename"] == "file" and doc["content_type"] == "application/octet-stream" and "content" not in doc
    meta, body = workflow.get_document(did, doc["id"])
    assert body == b"1234" and meta["sha256"]
    with pytest.raises(NotFoundError):
        workflow.get_document(did, 99999)
    with pytest.raises(InvalidInputError, match="BUY"):
        workflow.log_decision(did, "MAYBE", "x" * 20)
    with pytest.raises(InvalidInputError, match="10"):
        workflow.log_decision(did, "PASS", "太贵")
    d = workflow.log_decision(did, "PASS", "没有承销版本也能记：快照里版本为空")
    assert d["snapshot"]["version_id"] is None and d["run_id"] is None
    assert workflow.list_decisions(did)[0]["verdict"] == "PASS"


# ---------------------------------------------------------------- 证据
def test_evidence_rejections_and_conflict_flow(deal):
    did = deal["id"]
    ev = evidence.Evidence
    for bad, msg in [({"method": "guess"}, "抽取方式"), ({"confidence": "sure"}, "可信度"),
                     ({"assumption_source": "gut"}, "假设来源"), ({"field": " "}, "不能为空"),
                     ({"evidence_at": "昨天"}, "ISO")]:
        base = {"field": "analysis.exit_cap_rate", "value": 6.5, "source": "OM p.3", "method": "pdf",
                "confidence": "high"}
        with pytest.raises(InvalidInputError, match=msg):
            evidence.add_evidence(did, ev(**{**base, **bad}))
    with pytest.raises(NotFoundError):
        evidence.review(did, "nope")
    with pytest.raises(NotFoundError, match="未知保持未知"):
        evidence.passport(did, "nope")
    evidence.add_evidence(did, ev("noi", 100_000, "OM", "pdf", "high", evidence_at="2026-10-01"))
    r = evidence.add_evidence(did, ev("noi", 130_000, "T12", "pdf", "high", evidence_at="2026-10-01T00:00:00Z"))
    c = r["conflict"]
    assert c is not None and evidence.list_conflicts(did, "open")[0]["id"] == c["id"]
    with pytest.raises(InvalidInputError, match="理由"):
        evidence.resolve_conflict(did, c["id"], 100_000, " ")
    with pytest.raises(NotFoundError):
        evidence.resolve_conflict(did, 99999, 1, "x")
    evidence.resolve_conflict(did, c["id"], 100_000, "T12 含一次性收入")
    assert evidence.list_conflicts(did, "open") == []
    reviewed = evidence.review(did, "noi", "已对原件")
    assert reviewed["review_status"] == "reviewed" and "已对原件" in reviewed["note"]
    # 人工覆盖后复核不会把“已覆盖”洗成“已复核”
    evidence.add_evidence(did, ev("noi", 101_000, "T12", "manual", "medium"))
    assert evidence.review(did, "noi")["review_status"] == "overridden"
    assert len(evidence.passport(did, "noi")["history"]) == 3


# ---------------------------------------------------------------- 设置
def test_settings_rejections_and_upserts(deal):
    with pytest.raises(InvalidInputError, match="模板类型"):
        settings.save_template("colors", "x", {})
    with pytest.raises(InvalidInputError):
        settings.save_template("kill_criteria", "坏", {"criteria": [{"metric": "x", "op": "<", "threshold": 1}]})
    t1 = settings.save_template("market", "坦帕", {"rent_growth_pct": 3})
    t2 = settings.save_template("market", "坦帕", {"rent_growth_pct": 4})
    assert t1["id"] == t2["id"] and t2["payload"]["rent_growth_pct"] == 4
    names = [t["name"] for t in settings.list_templates("kill_criteria")]
    assert "商业默认" in names and all(t["kind"] == "market" for t in settings.list_templates("market"))
    with pytest.raises(InvalidInputError):
        settings.save_view(" ", {})
    v1 = settings.save_view("我的", {"stage": "screening"})
    v2 = settings.save_view("我的", {"stage": "committee"})
    assert v1["id"] == v2["id"] and settings.list_views()[0]["config"]["stage"] == "committee"
    settings.delete_view(v1["id"])
    with pytest.raises(NotFoundError):
        settings.delete_view(v1["id"])
    with pytest.raises(InvalidInputError, match="角色"):
        settings.create_user("bob", "admin")
    u = settings.create_user("bob", "viewer", "Bob")
    assert u["token"].startswith("dd_") and "token_sha256" not in u
    assert any(a["entity"] == "user" for a in settings.audit_log("user"))
    assert settings.audit_log("deal", str(deal["id"]))[0]["entity_id"] == str(deal["id"])
    assert {s["key"] for s in settings.data_sources()} >= {"tophap", "database"}
