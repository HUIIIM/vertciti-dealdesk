"""数据库 Schema（SQLAlchemy 2 声明式，SQLite 开发 / Postgres 生产同一套）。

约定（v2 蓝图 §7 数据）：
- 所有 v2 表带 created_at / updated_at / created_by（AuditMixin）。
- 关键表（deals、deal_versions、approvals、committee_votes、decisions、kill criteria）的每次写入
  另记 audit_log（谁、何时、改前改后、请求编号），见 services/persistence/audit.py。
- v1 遗留表（projects、uw_projects、address_cache）列定义与 v1 完全一致（REAL 时间戳），
  另加 created_by 可空列；v1 API 输出由金标准锁定不变。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSON, list[Any]: JSON}


class AuditMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow,
                                                 nullable=False)
    created_by: Mapped[str] = mapped_column(String(80), default="system", nullable=False)


# ---------------------------------------------------------------- v1 遗留表（列与 v1 一致）
class LegacyProject(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    track: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    score_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)


class LegacyUwProject(Base):
    __tablename__ = "uw_projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)


class AddressCache(Base):
    __tablename__ = "address_cache"
    address_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False, default="")
    data_json: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[float] = mapped_column(Float, nullable=False)


# ---------------------------------------------------------------- v2：用户与权限
class User(AuditMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # chairman | analyst | viewer
    token_sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


# ---------------------------------------------------------------- v2：交易与生命周期
class Deal(AuditMixin, Base):
    __tablename__ = "deals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    track: Mapped[str] = mapped_column(String(20), nullable=False)  # residential | commercial
    stage: Mapped[str] = mapped_column(String(20), default="sourcing", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="planned", nullable=False)  # 统一状态词
    asking_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kill_criteria: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    tags: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    __table_args__ = (Index("ix_deals_stage", "stage"),)


class DealVersion(AuditMixin, Base):
    """承销版本：每次保存假设生成一版，带可复现运行编号。"""

    __tablename__ = "deal_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    outputs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    run_id: Mapped[str] = mapped_column(String(80), nullable=False)
    __table_args__ = (UniqueConstraint("deal_id", "version_no", name="uq_deal_versions_deal_no"),)


class Run(AuditMixin, Base):
    """可复现运行：run_id = 引擎版本 + 规范化输入的哈希；同编号重算结果分毫不差。"""

    __tablename__ = "runs"
    run_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    outputs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    output_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class FieldProvenance(Base):
    """数字护照：每个字段每次变更一行（最新一行 = 当前值），可回看谁在何时改过。"""

    __tablename__ = "field_provenance"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), nullable=False)
    field: Mapped[str] = mapped_column(String(160), nullable=False)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    document_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    method: Mapped[str] = mapped_column(String(20), nullable=False)  # manual | ocr | api | pdf | calc
    confidence: Mapped[str] = mapped_column(String(10), nullable=False)  # high | medium | low
    evidence_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    market_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # 复核状态（pending / reviewed / overridden）与假设来源类型（provenance.ASSUMPTION_SOURCES）
    review_status: Mapped[str] = mapped_column(String(12), default="pending", nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assumption_source: Mapped[str] = mapped_column(String(20), default="document", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    created_by: Mapped[str] = mapped_column(String(80), default="system", nullable=False)
    __table_args__ = (Index("ix_field_provenance_deal_field", "deal_id", "field"),)


class Conflict(AuditMixin, Base):
    """跨来源矛盾登记：同一字段两个来源数值不同，记两边的值、差多少、采用哪个、谁裁决。"""

    __tablename__ = "conflicts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), nullable=False)
    field: Mapped[str] = mapped_column(String(160), nullable=False)
    value_a: Mapped[Any] = mapped_column(JSON, nullable=True)
    source_a: Mapped[str] = mapped_column(String(300), nullable=False)
    value_b: Mapped[Any] = mapped_column(JSON, nullable=True)
    source_b: Mapped[str] = mapped_column(String(300), nullable=False)
    diff_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="open", nullable=False)  # open | resolved
    resolved_value: Mapped[Any] = mapped_column(JSON, nullable=True)
    resolution_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    resolved_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CommitteePack(AuditMixin, Base):
    """投委会包登记：内容哈希印在包上，任何人拿到 PDF 都能校验是否原样。"""

    __tablename__ = "committee_packs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), nullable=False)
    version_id: Mapped[int] = mapped_column(Integer, nullable=False)
    run_id: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # pdf | xlsx
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)


class Task(AuditMixin, Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)  # open | done
    assignee: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    due: Mapped[str] = mapped_column(String(10), default="", nullable=False)  # YYYY-MM-DD
    stage: Mapped[str] = mapped_column(String(20), default="", nullable=False)


class Approval(AuditMixin, Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)  # payment | stage_override | general
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)


class Document(AuditMixin, Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), nullable=False)
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(40), default="other", nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class CommitteeVote(AuditMixin, Base):
    __tablename__ = "committee_votes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), nullable=False)
    version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    voter: Mapped[str] = mapped_column(String(80), nullable=False)
    vote: Mapped[str] = mapped_column(String(10), nullable=False)  # approve | reject | abstain
    comment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    __table_args__ = (UniqueConstraint("deal_id", "version_id", "voter", name="uq_committee_votes_once"),)


class Decision(AuditMixin, Base):
    """决策日志：BUY / HOLD / PASS + 理由 + 当时的数字快照（可复盘）。"""

    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), nullable=False)
    verdict: Mapped[str] = mapped_column(String(10), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    stage: Mapped[str] = mapped_column(String(20), default="", nullable=False)


class HoldingActual(AuditMixin, Base):
    """持有期实际数（按期），与承销对比偏差。"""

    __tablename__ = "holding_actuals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), nullable=False)
    period: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY 或 YYYY-MM
    noi: Mapped[float | None] = mapped_column(Float, nullable=True)
    occupancy_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    capex: Mapped[float | None] = mapped_column(Float, nullable=True)
    debt_service: Mapped[float | None] = mapped_column(Float, nullable=True)
    cash_flow: Mapped[float | None] = mapped_column(Float, nullable=True)
    __table_args__ = (UniqueConstraint("deal_id", "period", name="uq_holding_actuals_period"),)


class DealEvent(Base):
    """交易时间线（阶段推进、红队面板已读、投委会包生成等），也是“日志”标签页的数据源。"""

    __tablename__ = "deal_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    created_by: Mapped[str] = mapped_column(String(80), default="system", nullable=False)


class Template(AuditMixin, Base):
    """设置：假设模板 / 市场默认值 / 淘汰条件模板。"""

    __tablename__ = "templates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)  # assumptions | market | kill_criteria
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    __table_args__ = (UniqueConstraint("kind", "name", name="uq_templates_kind_name"),)


class SavedView(AuditMixin, Base):
    """流水线保存的视图（筛选、排序、列）。"""

    __tablename__ = "saved_views"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # create | update | delete | decide
    actor: Mapped[str] = mapped_column(String(80), nullable=False)
    before: Mapped[Any] = mapped_column(JSON, nullable=True)
    after: Mapped[Any] = mapped_column(JSON, nullable=True)
    request_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (Index("ix_audit_log_entity", "entity", "entity_id"),)
