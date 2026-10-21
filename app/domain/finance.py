"""共享金融数学：标准摊销公式与衍生指标（独立实现的标准公式）.

公式编号对应 tool-study-notes.md 第三节 F1-F15。
"""

from __future__ import annotations


def _safe_pow(base: float, exp: int) -> float | None:
    """安全幂：溢出返回 None（调用方降级），不抛 OverflowError."""
    try:
        return base ** exp
    except OverflowError:
        return None


def monthly_payment(principal: float, annual_rate_pct: float, years: float) -> float:
    """F1: 等额本息月供. annual_rate_pct 用百分制 (如 6.5 表示 6.5%)."""
    if principal <= 0 or years <= 0:
        return 0.0
    # 利率钳制到 [0, 100]%：防误填 10000 导致幂溢出
    annual_rate_pct = max(0.0, min(float(annual_rate_pct or 0), 100.0))
    r = annual_rate_pct / 100.0 / 12.0
    n = int(round(years * 12))
    if n <= 0:
        return 0.0
    if r == 0:
        return principal / n
    factor = _safe_pow(1 + r, n)
    if factor is None or factor == 1:
        return 0.0
    return principal * r * factor / (factor - 1)


def remaining_balance(principal: float, annual_rate_pct: float, years: float,
                       after_years: float) -> float:
    """F2: 等额本息贷款在 after_years 年后的剩余本金."""
    if principal <= 0 or years <= 0:
        return 0.0
    r = annual_rate_pct / 100.0 / 12.0
    n = int(round(years * 12))
    k = int(round(after_years * 12))
    if k <= 0:
        return principal
    if k >= n:
        return 0.0
    pmt = monthly_payment(principal, annual_rate_pct, years)
    if r == 0:
        return principal - pmt * k
    f1 = _safe_pow(1 + r, k)
    if f1 is None:
        return 0.0
    return principal * f1 - pmt * ((f1 - 1) / r)


def wrap_analysis(underlying_balance: float, underlying_rate_pct: float,
                  underlying_term_years: float, sale_price: float,
                  down_payment: float, wrap_rate_pct: float,
                  wrap_term_years: float, balloon_years: float | None) -> dict:
    """F11: wrap / subject-to 利差结构分析（clean-room 重写 R2 计算逻辑）.

    返回: wrap 贷款额 / wrap 月供 / 底层月供 / 月利差 /
          balloon 时点双方剩余本金 / 总利润.
    总利润 = 首付 + 月利差 x 持有月数 + (wrap 余本 - 底层余本)
    """
    wrap_loan = max(sale_price - down_payment, 0.0)
    wrap_pmt = monthly_payment(wrap_loan, wrap_rate_pct, wrap_term_years)
    under_pmt = monthly_payment(underlying_balance, underlying_rate_pct,
                                underlying_term_years)
    monthly_spread = wrap_pmt - under_pmt
    hold_years = balloon_years if balloon_years else wrap_term_years
    hold_months = int(round(hold_years * 12))
    wrap_bal = remaining_balance(wrap_loan, wrap_rate_pct, wrap_term_years, hold_years)
    under_bal = remaining_balance(underlying_balance, underlying_rate_pct,
                                  underlying_term_years, hold_years)
    total_profit = down_payment + monthly_spread * hold_months + (wrap_bal - under_bal)
    return {
        "wrap_loan": round(wrap_loan, 2),
        "wrap_payment": round(wrap_pmt, 2),
        "underlying_payment": round(under_pmt, 2),
        "monthly_spread": round(monthly_spread, 2),
        "hold_months": hold_months,
        "wrap_balance_at_exit": round(wrap_bal, 2),
        "underlying_balance_at_exit": round(under_bal, 2),
        "total_profit": round(total_profit, 2),
    }


def walt(leases: list[dict]) -> float:
    """F12: 加权平均剩余租期. leases: [{'base_rent': x, 'years_left': y}]."""
    total = sum(l.get("base_rent", 0) for l in leases)
    if total <= 0:
        return 0.0
    return sum(l.get("base_rent", 0) * l.get("years_left", 0) for l in leases) / total


def safe_div(num: float, den: float) -> float | None:
    if den is None or den == 0:
        return None
    return num / den


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def lin_map(x: float, x0: float, x1: float, y0: float, y1: float) -> float:
    """线性映射: x 在 [x0,x1] -> y 在 [y0,y1], clamp."""
    if x <= x0:
        return y0
    if x >= x1:
        return y1
    if x1 == x0:
        return y1
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def floating_down_payment_score(dp_pct: float, strength: float) -> tuple[float, float, float]:
    """首付浮动制（buyer-box.md v2.2 / buyer-box-commercial.md v1.2，Miao 亲定 2026-09-28 晚）.

    基础分 base(dp%)：≤5%→100；5–8% 线性 100→85；8–10% 线性 85→70；
    10–15% 线性 70→40；>15% 线性 40→0（25% 归零）。
    strength：现金流强度＝NOI/DSCR（住宅：现金流）维度得分率，clamp 到 0–1。
    bonus ＝ 15×clamp((strength−0.6)/0.4, 0, 1)；最终 ＝ min(100, base＋bonus)。

    返回 (score100, base, bonus)，调用方按维度权重折算。
    """
    dp = dp_pct or 0
    if dp <= 5:
        base = 100.0
    elif dp <= 8:
        base = lin_map(dp, 5, 8, 100, 85)
    elif dp <= 10:
        base = lin_map(dp, 8, 10, 85, 70)
    elif dp <= 15:
        base = lin_map(dp, 10, 15, 70, 40)
    else:
        base = lin_map(dp, 15, 25, 40, 0)
    s = clamp(strength or 0, 0, 1)
    bonus = 15 * clamp((s - 0.6) / 0.4, 0, 1)
    return (min(100.0, base + bonus), base, bonus)
