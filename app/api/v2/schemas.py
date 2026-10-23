"""v2 API 契约（Pydantic）：请求严格校验（extra=forbid），响应给出主干字段类型，供生成 TypeScript 客户端。"""
from __future__ import annotations

import json
from typing import Annotated, Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

Track = Literal["residential", "commercial", "institutional"]
Stage = Literal["sourcing", "screening", "underwriting", "committee", "diligence", "closing", "holding", "passed"]


class In(BaseModel):
    model_config = ConfigDict(extra="forbid")


Tag = Annotated[str, Field(min_length=1, max_length=40)]
MAX_TENANTS = 2000
MAX_INPUT_BYTES = 2 * 1024 * 1024
M = TypeVar("M", bound=BaseModel)


def _reject_nulls(model: M, fields: tuple[str, ...]) -> M:
    """PATCH 语义：没传 = 不改；显式传 null 给不可为空的字段 = 输入错误（而不是悄悄清空或写库时报冲突）。"""
    bad = [f for f in fields if f in model.model_fields_set and getattr(model, f) is None]
    if bad:
        raise ValueError(f"{', '.join(bad)}: null is not allowed")
    return model


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
    kill_criteria: list[KillCriterion] = Field(default_factory=list, max_length=20,
                                               description="淘汰条件：先写“什么情况下放弃”，再开始承销")
    tags: list[Tag] = Field(default_factory=list, max_length=20)


class DealPatch(In):
    """只改传了的字段。name / kill_criteria / tags 显式传 null 是错误（清空淘汰条件请传 []，不能“误清空”）。"""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=300)
    asking_price: float | None = Field(default=None, ge=0)
    kill_criteria: list[KillCriterion] | None = Field(default=None, max_length=20)
    tags: list[Tag] | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def _no_explicit_null(self) -> DealPatch:
        return _reject_nulls(self, ("name", "kill_criteria", "tags"))


class VersionCreate(In):
    inputs: dict[str, Any]
    label: str = Field(default="", max_length=200, description="本版改了什么 / 为什么（进投委会包“改动说明”）")

    @model_validator(mode="after")
    def _bounded(self) -> VersionCreate:
        # 每次打开交易页都会按当前版本跑红队（数十次模型）：输入规模必须有界，防只读用户拖垮服务
        tenants = self.inputs.get("tenants")
        if isinstance(tenants, list) and len(tenants) > MAX_TENANTS:
            raise ValueError(f"tenants: at most {MAX_TENANTS}")
        if len(json.dumps(self.inputs, default=str)) > MAX_INPUT_BYTES:
            raise ValueError(f"inputs: at most {MAX_INPUT_BYTES // 1024} KB")
        return self


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
    field: str = Field(min_length=1, max_length=160)
    note: str = Field(default="", max_length=2000)


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
    name: str = Field(min_length=1, max_length=80)
    probability: float = Field(ge=0, le=100)
    changes: list[ScenarioChange] = Field(default_factory=list, max_length=30)


class ScenariosIn(In):
    scenarios: list[Scenario] | None = Field(default=None, max_length=10)  # 每个情景跑一次模型：限量防耗尽


class Target(In):
    metric: str
    min: float


class MaxBidIn(In):
    targets: list[Target] = Field(default_factory=list, max_length=10)
    include_kill_criteria: bool = True


class DecisionIn(In):
    verdict: Literal["BUY", "HOLD", "PASS"]
    rationale: str = Field(min_length=10, max_length=5000)


class TaskIn(In):
    title: str = Field(min_length=1, max_length=300)
    stage: str = Field(default="", max_length=40)
    assignee: str = Field(default="", max_length=80)
    due: str = Field(default="", pattern=r"^$|^\d{4}-\d{2}-\d{2}$")


class TaskPatch(In):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    status: Literal["open", "done"] | None = None
    assignee: str | None = Field(default=None, max_length=80)
    due: str | None = Field(default=None, pattern=r"^$|^\d{4}-\d{2}-\d{2}$")

    @model_validator(mode="after")
    def _no_explicit_null(self) -> TaskPatch:
        return _reject_nulls(self, ("title", "status", "assignee", "due"))


class ApprovalIn(In):
    kind: Literal["payment", "general", "stage_override"]
    title: str = Field(min_length=1, max_length=300)
    amount: float | None = Field(default=None, gt=0)
    note: str = Field(default="", max_length=2000)


class ApprovalDecide(In):
    approve: bool
    note: str = Field(default="", max_length=2000)


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
    display_name: str = Field(default="", max_length=120)


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


# ---------------------------------------------------------------- 分析类响应（前端类型由此生成，杜绝手写类型漂移）
class KillItemOut(Out):
    metric: str
    op: str
    threshold: float
    value: float | None
    state: Literal["ok", "triggered", "unknown"]
    text: str


class KillEvalOut(Out):
    items: list[KillItemOut]
    triggered: list[KillItemOut]
    unknown: list[KillItemOut]
    defined: bool
    clear: bool


class ShockOut(Out):
    value: float
    delta_pct_points: float


class RedTeamRowOut(Out):
    key: str
    label: str
    paths: list[str]
    source_hint: str
    minus: ShockOut
    plus: ShockOut
    swing_bps: float
    material: bool


class SkippedOut(Out):
    key: str
    label: str
    reason: str


class RedTeamOut(Out):
    metric: str
    metric_label: str
    base: float | None
    shock_pct: float
    material_bps: float
    top: list[RedTeamRowOut]
    all: list[RedTeamRowOut]
    skipped: list[SkippedOut]
    key_assumptions: list[str]
    key_fields: list[str]
    note: str
    version_id: int
    read: bool


class RedTeamReadOut(Out):
    version_id: int
    read: bool


class ScenarioRowOut(Out):
    name: str
    probability: float
    changes: list[dict[str, Any]]
    metrics: dict[str, float | None]
    primary: float | None
    loss: bool | None
    note: str = ""  # 算不出时说明原因（如要调整的假设没有输入值）


class ScenariosOut(Out):
    metric: str
    metric_label: str
    scenarios: list[ScenarioRowOut]
    expected: float | None
    loss_probability_pct: float | None
    note: str


class ConstraintOut(Out):
    source: Literal["target", "kill_criteria"]
    metric: str
    label: str
    price: float | None
    status: Literal["ok", "above_range", "infeasible", "unknown"]
    reason: str


class VerifyItemOut(Out):
    kind: Literal["conflict", "unverified"]
    field: str
    label: str
    conflict_id: int | None
    swing_bps: float | None
    detail: str
    primary_a: float | None
    primary_b: float | None
    action: str


class VerifyQueueOut(Out):
    metric: str
    metric_label: str
    items: list[VerifyItemOut]
    top_share_pct: float | None
    note: str
    version_id: int


class MemoPointOut(Out):
    key: str
    severity: Literal["high", "medium"]
    title: str
    text: str
    tab: Literal["overview", "risk", "files", "model", "rentroll"]


class DevilsMemoOut(Out):
    headline: str | None
    points: list[MemoPointOut]
    high: int
    note: str
    version_id: int
    run_id: str


class PriceCheckIn(In):
    price: float = Field(gt=0, le=1e10, description="试算出价（美元）")


class PriceCheckOut(Out):
    price: float
    asking: float | None
    vs_asking_pct: float | None
    metrics: dict[str, float | None]
    kill: KillEvalOut


class MaxBidOut(Out):
    asking: float
    max_bid: float | None
    binding: ConstraintOut | None
    constraints: list[ConstraintOut]
    headroom_pct: float | None
    note: str


class DiffRowOut(Out):
    path: str
    kind: Literal["added", "removed", "changed"]
    before: Any = None
    after: Any = None
    delta: float | None = None
    delta_pct: float | None = None


class DiffSideOut(Out):
    id: int
    version_no: int
    label: str
    run_id: str


class DiffOut(Out):
    a: DiffSideOut
    b: DiffSideOut
    inputs: list[DiffRowOut]
    metrics: list[DiffRowOut]
    changed_inputs: int
    changed_metrics: int


class TallyOut(Out):
    approve: int
    reject: int
    abstain: int
    chairman_vote: str | None
    result: Literal["approved", "rejected", "pending"]
    why: str
    votes: int


class VoteOut(Out):
    id: int
    voter: str
    vote: Literal["approve", "reject", "abstain"]
    comment: str
    role: str
    role_label: str
    created_at: str


class CommitteeStatusOut(Out):
    version_id: int
    votes: list[VoteOut]
    tally: TallyOut
    rules: str


class PackOut(Out):
    id: int
    deal_id: int
    version_id: int
    run_id: str
    kind: Literal["pdf", "xlsx"]
    sha256: str
    size: int
    created_at: str
    created_by: str


class VerifyOut(Out):
    genuine: bool
    sha256: str
    message: str
    run_id: str | None = None
    deal_id: int | None = None
    version_id: int | None = None


class EventOut(Out):
    id: int
    deal_id: int
    kind: str
    payload: dict[str, Any]
    created_at: str
    created_by: str


class DecisionOut(Out):
    id: int
    deal_id: int
    verdict: Literal["BUY", "HOLD", "PASS"]
    rationale: str
    snapshot: dict[str, Any]
    run_id: str | None
    stage: str
    created_at: str
    created_by: str


class TaskOut(Out):
    id: int
    deal_id: int
    title: str
    status: Literal["open", "done"]
    stage: str
    assignee: str
    due: str
    created_by: str


class ApprovalOut(Out):
    id: int
    deal_id: int
    kind: Literal["payment", "general", "stage_override"]
    title: str
    amount: float | None
    status: Literal["pending", "approved", "rejected"]
    created_by: str
    decided_by: str | None
    decided_at: str | None
    note: str


class DocOut(Out):
    id: int
    deal_id: int
    filename: str
    content_type: str
    size: int
    sha256: str
    category: str
    created_at: str
    created_by: str


class ConflictOut(Out):
    id: int
    deal_id: int
    field: str
    value_a: Any = None
    source_a: str
    value_b: Any = None
    source_b: str
    diff_pct: float | None
    status: Literal["open", "resolved"]
    resolved_value: Any = None
    resolution_note: str
    resolved_by: str | None


class VarianceCellOut(Out):
    actual: float | None
    underwritten: float | None
    variance: float | None
    variance_pct: float | None


class VarianceRowOut(Out):
    months: int = 12  # 这一年由几个月的实际数合成（不足 12 个月时 NOI / 现金流为未知）
    period: str
    year: int
    noi: VarianceCellOut
    cash_flow: VarianceCellOut
    occupancy_pct: float | None


class AttributionStepOut(Out):
    key: str
    label: str
    underwritten: Any = None
    actual: Any = None
    contribution_pct_points: float | None


class AttributionOut(Out):
    available: bool
    reason: str | None = None
    metric: str | None = None
    underwritten: float | None = None
    actual_implied: float | None = None
    total_pct_points: float | None = None
    steps: list[AttributionStepOut] | None = None
    note: str | None = None


class HoldingBasisOut(Out):
    version_id: int
    version_no: int
    run_id: str
    from_buy_decision: bool


class ActualOut(Out):
    period: str
    noi: float | None = None
    occupancy_pct: float | None = None
    capex: float | None = None
    debt_service: float | None = None
    cash_flow: float | None = None


class HoldingOut(Out):
    basis: HoldingBasisOut
    actuals: list[ActualOut]
    variance: list[VarianceRowOut]
    attribution: AttributionOut


class MetricMetaOut(Out):
    label: str
    label_en: str
    unit: Literal["usd", "pct", "x", "usd_month", "pts"]
    better: Literal["higher", "lower"]


class AssumptionOut(Out):
    key: str
    label: str
    paths: list[str]
    source_hint: str


class CatalogOut(Out):
    metrics: dict[str, MetricMetaOut]
    primary_metric: dict[str, str]
    assumptions: dict[str, list[AssumptionOut]]
    kill_criteria_defaults: dict[str, list[KillCriterion]]
    scenario_defaults: dict[str, list[Scenario]]


class MeOut(Out):
    username: str
    role: str
    role_label: str
    display_name: str
    auth: bool
    permissions: list[str]


class CompareDealOut(Out):
    deal: DealOut
    metrics: dict[str, float | None]
    version: dict[str, Any] | None
    kill: KillEvalOut | None


class CompareOut(Out):
    deals: list[CompareDealOut]
    best: dict[str, int]


class ModelOut(Out):
    track: Track
    metrics: dict[str, float | None]
    detail: dict[str, Any]


class StageResultOut(Out):
    deal: DealOut
    gate: GateOut


class HealthDbOut(Out):
    ok: bool
    revision: str | None
    kind: Literal["postgres", "sqlite"]
    error: str


class HealthOut(Out):
    ok: bool
    service: str
    version: str
    engine_version: str
    db: HealthDbOut
    auth: Literal["on", "off"]
    uptime_s: float


class TemplateOut(Out):
    id: int | None
    kind: str
    name: str  # 标识（保存 / 覆盖按它匹配），不随语言变
    label: str = ""  # 显示名：内置模板按语言翻译，自定义模板同 name
    payload: dict[str, Any]
    builtin: bool = False


class ViewOut(Out):
    id: int
    name: str
    config: dict[str, Any]


class UserOut(Out):
    id: int
    username: str
    display_name: str
    role: str
    active: bool


class UserCreatedOut(UserOut):
    token: str = Field(description="访问令牌，只在创建时返回这一次")
    note: str


class AuditOut(Out):
    id: int
    entity: str
    entity_id: str
    action: str
    actor: str
    before: Any = None
    after: Any = None
    request_id: str
    at: str


class DataSourceOut(Out):
    key: str
    label: str
    configured: bool
    detail: str


class PortfolioOut(Out):
    count: int
    total_price: float
    weighted_coc_pct: float | None
    deals: list[DealListItem]


# ---------------------------------------------------------------- 取数与导出（老版功能搬进 v2）
class CandidateOut(Out):
    """提取 / 搜集到的一个候选值：path 为空表示只作参考（不是承销输入或值不可用）。"""

    key: str
    label: str
    path: str | None
    value: float | int | str | None
    display: str
    page: int | None
    source: str
    source_url: str
    confidence: Literal["high", "medium", "low"]
    confidence_label: str
    seller_claimed: bool
    note: str
    method: Literal["pdf", "api"]


class ExtractedTenantOut(Out):
    suite: str | None = None
    tenant: str | None = None
    sf: float | None = None
    monthly_rent: float | None = None
    page: int | None = None


class ExtractOut(Out):
    document_id: int
    filename: str
    track: Track
    candidates: list[CandidateOut]
    tenants: list[ExtractedTenantOut]
    notice: str


class ResearchIn(In):
    track: Track
    mode: Literal["address", "url"] = "address"
    text: str = Field(min_length=1, max_length=500)


class ResearchOut(Out):
    track: Track
    mode: str
    address: str
    candidates: list[CandidateOut]
    manual_needed: list[str]
    error: str


class LegacyProjectOut(Out):
    kind: Literal["project", "uw"]
    id: int
    track: Track
    name: str
    address: str
    updated_at: float | None
    imported_deal_id: int | None


class LegacyImportOut(Out):
    deal: DealOut
    version: VersionOut | None
    warning: str


# ---------------------------------------------------------------- 机构级承销引擎
class InstitutionalOut(Out):
    """逐租约按月引擎的结果：metrics 主指标；annual / monthly 为逐期现金流科目；rent_roll 含到期续上的假设段。"""

    engine: str
    metrics: dict[str, float | None]
    annual: dict[str, list[float]]
    monthly: dict[str, list[float]]
    flows: dict[str, list[float]]
    exit: dict[str, float]
    rent_roll: list[dict[str, Any]]
    unit_mix: list[dict[str, Any]] | None = None
    refinance: dict[str, Any] | None = None
    construction: dict[str, Any] | None = None
    waterfall: dict[str, Any] | None
