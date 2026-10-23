"""v2 中英切换：词典不缺词、占位一致；英文请求下系统生成的文案里没有一个中文字；中文请求零变化。"""

from __future__ import annotations

import ast
import glob
import re
import string

import pytest
from fastapi.testclient import TestClient

from app.core.i18n import T, label, reset_lang, set_lang
from app.core.i18n_en import EN
from app.domain import uw_commercial
from app.main import app

CJK = re.compile(r"[　-〿一-鿿＀-￯]")
FILES = [*glob.glob("app/domain/v2/*.py"), *glob.glob("app/services/v2/*.py"), *glob.glob("app/api/v2/*.py"),
         "app/core/security.py", "app/services/render/committee_pack.py"]


def _templates() -> set[str]:
    out = set()
    for f in FILES:
        for n in ast.walk(ast.parse(open(f, encoding="utf-8").read())):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("T", "label")
                    and n.args and isinstance(n.args[0], ast.Constant)):
                out.add(n.args[0].value)
    return out


def _fields(tpl: str) -> list[str]:
    return sorted(f"{name}" for _, name, _, _ in string.Formatter().parse(tpl) if name is not None)


def test_every_template_has_english_with_same_placeholders():
    missing = sorted(t for t in _templates() if t not in EN)
    assert not missing, f"缺英文：{missing[:20]}"
    bad = [(k, v) for k, v in EN.items() if _fields(k) != _fields(v)]
    assert not bad, f"占位不一致：{bad[:10]}"
    leaked = [(k, v) for k, v in EN.items() if CJK.search(v)]
    assert not leaked, f"英文里有中文：{leaked[:10]}"


def test_constant_labels_are_translated():
    from app.core.security import ROLE_LABEL
    from app.domain.v2 import lifecycle, provenance
    from app.domain.v2.assumptions import BY_TRACK
    from app.domain.v2.model import METRICS
    labels = {v for _, v in lifecycle.STAGES} | {lifecycle.TERMINAL[1]} | set(lifecycle.STATUS_WORDS.values())
    for d in (provenance.METHODS, provenance.CONFIDENCE_LABEL, provenance.REVIEW, provenance.ASSUMPTION_SOURCES, ROLE_LABEL):
        labels |= set(d.values())
    labels |= {a.label for tr in BY_TRACK.values() for a in tr} | {m.label for m in METRICS.values()}
    missing = sorted(x for x in labels if CJK.search(x) and x not in EN)
    assert not missing, f"固定标签缺英文：{missing}"


def test_T_formats_and_translates_label_args():
    tok = set_lang("en")
    try:
        # 固定标签在生成处用 label() 转好；T() 不翻译参数（参数可能是用户数据）
        assert T("「{0}」只要错 {1:g}%，{2}就落在 {3:.2f}%–{4:.2f}% 之间（摆动 {5:.0f} bp）。这个数从哪来、谁核过，决定了这笔交易。",
                 label("租金水平"), 10, "IRR", 1.5, 15.0, 747).startswith("If “Rent level” is off by just 10%")
        assert T("{0} · {1}：{2}", "租金水平", "OM", "x") == "租金水平 · OM: x"  # 用户数据原样
    finally:
        reset_lang(tok)
    assert T("第 {0} 版", 3) == "第 3 版"  # 中文请求：原样格式化


def _cjk_in_system_text(obj, path="") -> list[str]:
    """收集响应里任何位置的中文：测试数据全用英文录入，所以出现中文只可能是系统文案漏翻。"""
    out = []
    if isinstance(obj, str):
        return [f"{path}={obj[:60]}"] if CJK.search(obj) else []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out += _cjk_in_system_text(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += _cjk_in_system_text(v, f"{path}[{i}]")
    return out


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DEALDESK_DB", str(tmp_path / "i18n.db"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DEALDESK_AUTH", raising=False)
    return TestClient(app)


def test_english_requests_have_no_chinese_in_system_text(client):
    en = {"X-DD-Lang": "en"}
    d = client.post("/api/v2/deals", headers=en, json={
        "name": "Main St", "track": "commercial", "address": "1 Main St", "asking_price": 42_000_000,
        "kill_criteria": [{"metric": "irr_pct", "op": "<", "threshold": 12}, {"metric": "dscr", "op": "<", "threshold": 1.25}]}).json()
    did = d["id"]
    client.post(f"/api/v2/deals/{did}/versions", headers=en, json={"inputs": uw_commercial.example_39_main(), "label": "v1"})
    for src, v in (("OM", 5.0), ("Broker call", 5.75)):
        client.post(f"/api/v2/deals/{did}/evidence", headers=en, json={
            "field": "analysis.exit_cap_rate", "value": v, "source": src, "method": "pdf", "confidence": "high"})
    gets = ["/api/v2/catalog", f"/api/v2/deals/{did}", f"/api/v2/deals/{did}/redteam", f"/api/v2/deals/{did}/verify-queue",
            f"/api/v2/deals/{did}/devils-memo", f"/api/v2/deals/{did}/gate?target=screening", f"/api/v2/deals/{did}/passports",
            f"/api/v2/deals/{did}/conflicts", f"/api/v2/deals/{did}/events", "/api/v2/deals", "/api/v2/me",
            "/api/v2/settings/templates", "/api/v2/settings/data-sources"]
    posts = [(f"/api/v2/deals/{did}/scenarios", {}), (f"/api/v2/deals/{did}/max-bid", {"targets": []}),
             (f"/api/v2/deals/{did}/price-check", {"price": 30_000_000})]
    leaks = []
    for u in gets:
        r = client.get(u, headers=en)
        assert r.status_code == 200, (u, r.text[:200])
        leaks += [f"{u} {x}" for x in _cjk_in_system_text(r.json())]
    for u, body in posts:
        r = client.post(u, headers=en, json=body)
        assert r.status_code == 200, (u, r.text[:200])
        leaks += [f"{u} {x}" for x in _cjk_in_system_text(r.json())]
    # 报错也是英文
    r = client.post(f"/api/v2/deals/{did}/stage", headers=en, json={"target": "committee"})
    assert r.status_code == 409 and not CJK.search(r.json()["detail"])
    assert not CJK.search(client.get("/api/v2/deals/999999", headers=en).json()["detail"])
    # 内置模板的 name 是标识（保存时按它匹配），显示用 label——已是英文
    leaks = [x for x in leaks if not re.search(r"/settings/templates \[\d+\]\.name=", x)]
    tpl = client.get("/api/v2/settings/templates", headers=en).json()
    assert {t["label"] for t in tpl if t["builtin"]} == {"Commercial default", "Residential default", "Institutional default"}
    assert not leaks, "\n".join(leaks[:30])


def test_chinese_is_default_and_unchanged(client):
    zh = client.get("/api/v2/catalog").json()
    assert zh["metrics"]["irr_pct"]["label"] == "IRR" and zh["metrics"]["coc_pct"]["label"] == "现金回报"
    assert client.get("/api/v2/catalog", headers={"Accept-Language": "en-US"}).json() == zh  # 浏览器自带语言不算数
