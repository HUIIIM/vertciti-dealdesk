"""v2 API 契约（Pydantic）：请求严格校验（extra=forbid），响应给出主干字段类型，供生成 TypeScript 客户端。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Track = Literal["residential", "commercial"]
Stage = Literal["sourcing", "screening", "underwriting", "committee", "diligence", "closing", "holding", "passed"]


class In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Out(BaseModel):
    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------- 请求
class KillCriterion(In):
    metric: str
    op: Literal["<", "<=", ">", ">="]
    threshold: float


class DealCreate(In):
    name: str = Field(min_length=1, max_length=200)
    track: Track
    address: str = Field(default="", max_length=300)
    asking_price: float | None = Field(default=None, ge=0)
    kill_criteria: list[KillCriterion] = Field(default_factory=list,
                                               description="淘汰条件：先写“什么情况下放弃”，再开始承销")
    tags: list[str] = Field(default_factory=list)


class DealPatch(In):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=300)
    asking_price: float | None = Field(default=None, ge=0)
    kill_criteria: list[KillCriterion] | None = None
    tags: list[str] | None = None


class VersionCreate(In):
    inputs: dict[str, Any]
    label: str = Field(default="", max_length=200, description="本版改了什么 / 为什么（进投委会包“改动说明”）")


class StageAdvance(In):
    target: Stage
    reason: str = Field(default="", max_length=2000)


class EvidenceIn(In):
    field: str = Field(min_length=1, max_length=160, description="输入路径，如 analysis.exit_cap_rate")
    value: Any = None
    source: str = Field(min_length=1, max_length=300)
    method: Literal["manual", "ocr", "api", "pdf", "calc", "import"]
    confidence: Literal["high", "medium", "low"]
    page: int | None = Field(default=None, ge=1)
    document_id: int | None = None
    evidence_at: str | None = Field(default=None, description="证据日期（ISO 8601）；市场数据据此判断新鲜度")
    market_data: bool = False
    assumption_source: Literal["document", "historical", "benchmark", "comps", "analyst"] = "document"
    note: str = Field(default="", max_length=2000)


class ReviewIn(In):
    field: str
    note: str = ""


class ConflictResolve(In):
    value: Any
    note: str = Field(min_length=1, max_length=2000)


class ScenarioChange(In):
    assumption: str | None = None
    path: str | None = None
    pct: float | None = None
    add: float | None = None
    set: Any = None


class Scenario(In):
    name: str
    probability: float = Field(ge=0, le=100)
    changes: list[ScenarioChange] = Field(default_factory=list)


class ScenariosIn(In):
    scenarios: list[Scenario] | None = None


class Target(In):
    metric: str
    min: float


class MaxBidIn(In):
    targets: list[Target] = Field(default_factory=list)
    include_kill_criteria: bool = True


class DecisionIn(In):
    verdict: Literal["BUY", "HOLD", "PASS"]
    rationale: str = Field(min_length=10, max_length=5000)


class TaskIn(In):
    title: str = Field(min_length=1, max_length=300)
    stage: str = ""
    assignee: str = ""
    due: str = Field(default="", pattern=r"^$|^\d{4}-\d{2}-\d{2}$")


class TaskPatch(In):
    title: str | None = None
    status: Literal["open", "done"] | None = None
    assignee: str | None = None
    due: str | None = Field(default=None, pattern=r"^$|^\d{4}-\d{2}-\d{2}$")


class ApprovalIn(In):
    kind: Literal["payment", "general", "stage_override"]
    title: str = Field(min_length=1, max_length=300)
    amount: float | None = Field(default=None, gt=0)
    note: str = ""


class ApprovalDecide(In):
    approve: bool
    note: str = ""


class VoteIn(In):
    vote: Literal["approve", "reject", "abstain"]
    comment: str = Field(default="", max_length=5000)


class ActualIn(In):
    period: str = Field(pattern=r"^\d{4}(-\d{2})?$")
    noi: float | None = None
    occupancy_pct: float | None = Field(default=None, ge=0, le=100)
    capex: float | None = None
    debt_service: float | None = None
    cash_flow: float | None = None


class TemplateIn(In):
    kind: Literal["assumptions", "market", "kill_criteria"]
    name: str = Field(min_length=1, max_length=120)
    payload: dict[str, Any]


class ViewIn(In):
    name: str = Field(min_length=1, max_length=120)
    config: dict[str, Any]


class UserIn(In):
    username: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    role: Literal["chairman", "analyst", "viewer"]
    display_name: str = ""


# ---------------------------------------------------------------- 响应
class DealOut(Out):
    id: int
    name: str
    address: str
    track: Track
    stage: str
    stage_label: str
    status: str
    asking_price: float | None
    current_version_id: int | None
    kill_criteria: list[dict[str, Any]]
    tags: list[str]
    created_at: str
    updated_at: str
    created_by: str


class DealListItem(DealOut):
    metrics: dict[str, Any]
    kill: dict[str, Any] | None
    stage_index: int


class VersionOut(Out):
    id: int
    deal_id: int
    version_no: int
    label: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    run_id: str
    created_at: str
    created_by: str


class RunOut(Out):
    run_id: str
    engine_version: str
    kind: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    output_sha256: str
    created_at: str


class RunVerifyOut(Out):
    run_id: str
    identical: bool
    same_engine: bool
    stored_engine: str
    current_engine: str
    stored_sha256: str
    recomputed_sha256: str


class GateCheck(Out):
    key: str
    label: str
    status: Literal["verified", "building", "planned", "risk"]
    status_label: str
    detail: str
    ok: bool


class GateOut(Out):
    allowed: bool
    reason: str = ""
    direction: str | None = None
    checks: list[GateCheck] = Field(default_factory=list)


class OverviewOut(Out):
    deal: DealOut
    version: dict[str, Any] | None
    metrics: dict[str, Any]
    metric_catalog: dict[str, dict[str, Any]]
    kill: dict[str, Any]
    verification: dict[str, Any]
    committee: dict[str, Any]
    last_verdict: str | None
    next_stage: str | None
    next_gate: GateOut | None
    stages: list[dict[str, str]]


class PassportOut(Out):
    id: int
    field: str
    value: Any
    source: str
    page: int | None
    method: str
    method_label: str
    confidence: str
    confidence_label: str
    review_status: str
    review_label: str
    assumption_source: str
    freshness: dict[str, Any]
    created_at: str
    created_by: str


class PassportDetail(Out):
    field: str
    current: PassportOut
    history: list[PassportOut]
    conflicts: list[dict[str, Any]]


class EvidenceOut(Out):
    passport: PassportOut
    conflict: dict[str, Any] | None


class Generic(Out):
    """结构较深的分析结果（红队、情景、反推、对比、归因）：字段见各端点说明。"""
