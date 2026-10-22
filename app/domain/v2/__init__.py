"""v2 领域层：交易生命周期与决策支持的纯计算（无 I/O，全类型标注，mypy 严格）。

计算本身复用 v1 引擎（app.domain.scoring_residential / uw_commercial，口径由金标准锁定），
本包只在其上做：统一指标、扰动、情景、反推、关卡、对比、归因。
"""
