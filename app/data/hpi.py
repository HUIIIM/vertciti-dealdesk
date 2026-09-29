"""嵌入的公开房价指数数据（FHFA HPI / FRED / NAR / BLS）.

铁律：
- 只收录本会话中用 browser 工具逐条核验过的公开数据；
- 指数是指数，不是房价：绝不把指数值当作 $/SF 或房产价值呈现；
- 每条数据都带 source（来源）、vintage（数据版本/更新日期）、url；
- 不同市场的序列新旧程度不同（vintage 不同），前端必须按市场分别标注，
  不得暗示所有市场同样新。
"""

from __future__ import annotations

FHFA_RELEASE = "FHFA House Price Index 2026年Q2发布"
FHFA_RELEASE_DATE = "2026-08-25"  # 发布日前后；FRED 系列同日更新
FHFA_DOWNLOADS_URL = "https://www.fhfa.gov/DataTools/Downloads/Pages/House-Price-Index-Datasets.aspx"

# 口径说明（所有市场通用）
METHODOLOGY = (
    "FHFA All-Transactions HPI：用销售价格 + 评估值（refi 评估）估算的重复交易指数，"
    "是价格指数（index），不是房价本身；不能直接换算成 $/SF 或具体房产价值。"
)

MARKETS = {
    "us": {
        "label": "全美",
        "geo": "United States",
        "fred_series": "USSTHPI",
        "fred_url": "https://fred.stlouisfed.org/series/USSTHPI",
        "units": "指数 1980:Q1=100",
        "freq": "季度，未季调",
        "changes": {"1y": 2.1, "qq": 0.3},
        "changes_note": "2025Q2→2026Q2 同比 +2.1%，环比 +0.3%（FHFA HPI 2026Q2 发布）",
        "fred_yoy_q4_2025": 3.5,
        "fred_yoy_note": "FRED USSTHPI 同比（2025Q4），指数 1980:Q1=100",
        "source": "U.S. Federal Housing Finance Agency（经 FRED 发布）",
        "vintage": "2026-08-25（FHFA HPI 2026Q2 发布）",
    },
    "nyc": {
        "label": "纽约",
        "geo": "NY州；NY-Jersey City-White Plains, NY-NJ (MSAD)",
        "fred_series": "ATNHPIUS35614Q",
        "fred_url": "https://fred.stlouisfed.org/series/ATNHPIUS35614Q",
        "units": "指数 1995:Q1=100",
        "freq": "季度，未季调",
        "changes": {"1y": 3.53, "5y": 43.99},
        "changes_note": "NY州 2025Q2→2026Q2 同比 +3.53%，5年 +43.99%（FHFA HPI 2026Q2 发布）",
        "msad_changes": {"1y": 5.72, "5y": 45.06, "since_1991": 350.02},
        "msad_note": "New York-Jersey City-White Plains MSAD：1年 +5.72%，5年 +45.06%，1991年以来 +350.02%",
        "source": "FHFA HPI 2026Q2 发布（州表 + Top100 MSA/MSAD 表）",
        "vintage": "2026-08-25（FHFA HPI 2026Q2 发布）",
        "series_note": "MSAD 指数序列以 FRED ATNHPIUS35614Q 为准，最新值请点链接查看（本页嵌入值待补）",
    },
    "phoenix": {
        "label": "凤凰城",
        "geo": "Phoenix-Mesa-Chandler, AZ (MSA)",
        "fred_series": "ATNHPIUS38060Q",
        "fred_url": "https://fred.stlouisfed.org/series/ATNHPIUS38060Q",
        "units": "指数 1995:Q1=100",
        "freq": "季度，未季调",
        "changes": {"1y": 0.58, "5y": 27.45},
        "changes_note": "AZ州 2025Q2→2026Q2 同比 +0.58%，5年 +27.45%（FHFA HPI 2026Q2 发布）",
        # FRED 核验的最近 5 个季度（2026-09-29 抓取，FRED 页面原文）
        "series": [
            {"q": "2025Q2", "value": 512.77},
            {"q": "2025Q3", "value": 510.78},
            {"q": "2025Q4", "value": 515.00},
            {"q": "2026Q1", "value": 518.97},
            {"q": "2026Q2", "value": 517.12},
        ],
        "source": "FHFA（经 FRED 发布）；序列值逐条核验自 FRED 系列页",
        "vintage": "2026-08-25（FRED 页面 Updated: Aug 25, 2026）",
    },
    "tampa": {
        "label": "坦帕",
        "geo": "Tampa-St. Petersburg-Clearwater, FL (MSA)",
        "fred_series": "ATNHPIUS45300Q",
        "fred_url": "https://fred.stlouisfed.org/series/ATNHPIUS45300Q",
        "units": "指数 1995:Q1=100",
        "freq": "季度，未季调",
        "changes": {"1y": 0.96, "5y": 37.47},
        "changes_note": "FL州 2025Q2→2026Q2 同比 +0.96%，5年 +37.47%（FHFA HPI 2026Q2 发布）",
        # 注意：FRED 抓取到的该序列最新为 2024Q4，比凤凰城旧，属实标注
        "series": [
            {"q": "2023Q4", "value": 544.33},
            {"q": "2024Q1", "value": 544.47},
            {"q": "2024Q2", "value": 553.39},
            {"q": "2024Q3", "value": 559.56},
            {"q": "2024Q4", "value": 554.54},
        ],
        "series_vintage": "2026-09-29 抓取时 FRED 页面最新仅到 2024Q4（该市场序列更新较慢），最新季度请点 FRED 链接",
        "nar_local": {
            "period": "2024Q1",
            "median_price": 405200,
            "yoy": 3.9,
            "y3": 37.4,
            "note": "NAR Economists 坦帕本地市场报告：中位价 $405,200，同比 +3.9%，3年 +37.4%",
            "url": "https://www.nar.realtor/blogs/economists/tampa-housing-market",
            "vintage": "2024Q1（报告发布时）",
        },
        "census_url": "https://www.census.gov/quickfacts/fact/table/tampacityflorida/",
        "bls_rent_cpi": {
            "series": "CUUSA321SEHA",
            "url": "https://fred.stlouisfed.org/series/CUUSA321SEHA",
            "units": "指数 1987=100，年频",
            "values": {"2021": 300.342, "2022": 341.787, "2023": 379.270,
                       "2024": 404.263, "2025": 417.854},
            "note": "BLS 坦帕地区主要居所租金 CPI（经 FRED）",
        },
        "source": "FHFA（经 FRED 发布）；本地中位价来自 NAR；租金 CPI 来自 BLS",
        "vintage": "州涨幅 2026-08-25；MSA 序列 2024Q4（旧）；NAR 本地价 2024Q1",
    },
    "dallas": {
        "label": "达拉斯",
        "geo": "Dallas-Fort Worth-Arlington, TX (MSA)；州口径 TX",
        "fred_series": None,
        "fred_url": None,
        "units": "指数 1995:Q1=100（MSA 口径）",
        "freq": "季度，未季调",
        "changes": {"1y": 0.45, "5y": 25.11},
        "changes_note": "TX州 2025Q2→2026Q2 同比 +0.45%，5年 +25.11%（FHFA HPI 2026Q2 发布）",
        "source": "FHFA HPI 2026Q2 发布（州表）",
        "vintage": "2026-08-25（FHFA HPI 2026Q2 发布）",
        "series_note": "Dallas-Fort Worth-Arlington MSA 指数序列见 FHFA 下载页（HPI Datasets），本页嵌入值待补",
    },
    "atlanta": {
        "label": "亚特兰大",
        "geo": "Atlanta-Sandy Springs-Alpharetta, GA (MSA)",
        "fred_series": "ATNHPIUS12060Q",
        "fred_url": "https://fred.stlouisfed.org/series/ATNHPIUS12060Q",
        "units": "指数 1995:Q1=100",
        "freq": "季度，未季调",
        "changes": {"1y": 1.90, "5y": 39.22},
        "changes_note": "GA州 2025Q2→2026Q2 同比 +1.90%，5年 +39.22%（FHFA HPI 2026Q2 发布）",
        # FRED 核验的最近 5 个季度（2026-09-29 抓取）
        "series": [
            {"q": "2023Q4", "value": 361.17},
            {"q": "2024Q1", "value": 366.44},
            {"q": "2024Q2", "value": 372.78},
            {"q": "2024Q3", "value": 376.64},
            {"q": "2024Q4", "value": 376.30},
        ],
        "series_vintage": "2026-09-29 抓取时 FRED 页面最新到 2024Q4（Updated: Feb 25, 2025），最新季度请点 FRED 链接",
        "source": "FHFA（经 FRED 发布）；序列值逐条核验自 FRED 系列页",
        "vintage": "州涨幅 2026-08-25；MSA 序列 2024Q4（旧）",
    },
}

# 市场调查模块的公开数据源链接（全部为本会话核验过的原文 URL）
PUBLIC_SOURCES = [
    {"name": "FHFA 房价指数数据集下载页", "url": FHFA_DOWNLOADS_URL,
     "note": "州/MSA/县三级 HPI，免费下载（purchase-only 与 all-transactions）"},
    {"name": "FRED · 凤凰城 MSA 房价指数", "url": "https://fred.stlouisfed.org/series/ATNHPIUS38060Q",
     "note": "ATNHPIUS38060Q，季度，1995Q1=100"},
    {"name": "FRED · 坦帕 MSA 房价指数", "url": "https://fred.stlouisfed.org/series/ATNHPIUS45300Q",
     "note": "ATNHPIUS45300Q，季度，1995Q1=100"},
    {"name": "FRED · 亚特兰大 MSA 房价指数", "url": "https://fred.stlouisfed.org/series/ATNHPIUS12060Q",
     "note": "ATNHPIUS12060Q，季度，1995Q1=100"},
    {"name": "FRED · 纽约 MSAD 房价指数", "url": "https://fred.stlouisfed.org/series/ATNHPIUS35614Q",
     "note": "ATNHPIUS35614Q，季度，1995Q1=100"},
    {"name": "FRED · 全美房价指数", "url": "https://fred.stlouisfed.org/series/USSTHPI",
     "note": "USSTHPI，季度，1980Q1=100"},
    {"name": "NAR · 坦帕本地市场报告", "url": "https://www.nar.realtor/blogs/economists/tampa-housing-market",
     "note": "含中位价、同比/3年涨幅（2024Q1）"},
    {"name": "Census · 坦帕 QuickFacts", "url": "https://www.census.gov/quickfacts/fact/table/tampacityflorida/",
     "note": "人口、住房、收入等普查快照"},
    {"name": "BLS · 各州失业率历史", "url": "https://www.bls.gov/web/laus/lauhsthl.htm",
     "note": "州失业率历史表（就业市场调查用）"},
    {"name": "BLS · 各都市区失业率", "url": "https://www.bls.gov/charts/job-openings-and-labor-turnover/opening.htm",
     "note": "JOLTS/失业率图表（含都市区）"},
]


def get_market(key: str) -> dict | None:
    return MARKETS.get(key)


def market_list() -> list[dict]:
    return [{"key": k, **{kk: vv for kk, vv in v.items() if kk != "series"}}
            for k, v in MARKETS.items()]


def yoy_from_series(series: list[dict]) -> dict | None:
    """从季度序列算最新同比（需 >=5 个点）；返回 {latest_q, latest, yoy_pct}."""
    if not series or len(series) < 5:
        return None
    pts = sorted(series, key=lambda p: p["q"])
    latest, year_ago = pts[-1], pts[-5]
    if not year_ago["value"]:
        return None
    return {
        "latest_q": latest["q"],
        "latest": latest["value"],
        "year_ago_q": year_ago["q"],
        "yoy_pct": round((latest["value"] / year_ago["value"] - 1) * 100, 2),
    }
