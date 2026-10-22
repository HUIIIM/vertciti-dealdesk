"""EN for the embedded HPI data (hpi.py), used by /api/wb/markets?lang=en.

Keyed by the exact zh string so hpi.py stays the single source of numbers.
tests/test_hpi_en.py fails if hpi.py gains a Chinese string with no entry
here, so a data refresh cannot silently leave the EN UI half-Chinese.
"""

from __future__ import annotations

from typing import Any

EN: dict[str, str] = {
    "全美": "United States",
    "纽约": "New York",
    "凤凰城": "Phoenix",
    "坦帕": "Tampa",
    "达拉斯": "Dallas",
    "亚特兰大": "Atlanta",
    "指数 1980:Q1=100": "Index 1980:Q1=100",
    "指数 1995:Q1=100": "Index 1995:Q1=100",
    "指数 1995:Q1=100（MSA 口径）": "Index 1995:Q1=100 (MSA basis)",
    "指数 1987=100，年频": "Index 1987=100, annual",
    "季度，未季调": "Quarterly, not seasonally adjusted",
    "2025Q2→2026Q2 同比 +2.1%，环比 +0.3%（FHFA HPI 2026Q2 发布）":
        "2025Q2→2026Q2 YoY +2.1%, QoQ +0.3% (FHFA HPI 2026Q2 release)",
    "FRED USSTHPI 同比（2025Q4），指数 1980:Q1=100": "FRED USSTHPI YoY (2025Q4), index 1980:Q1=100",
    "U.S. Federal Housing Finance Agency（经 FRED 发布）": "U.S. Federal Housing Finance Agency (via FRED)",
    "2026-08-25（FHFA HPI 2026Q2 发布）": "2026-08-25 (FHFA HPI 2026Q2 release)",
    "NY州；NY-Jersey City-White Plains, NY-NJ (MSAD)": "NY state; NY-Jersey City-White Plains, NY-NJ (MSAD)",
    "NY州 2025Q2→2026Q2 同比 +3.53%，5年 +43.99%（FHFA HPI 2026Q2 发布）":
        "NY state 2025Q2→2026Q2 YoY +3.53%, 5-yr +43.99% (FHFA HPI 2026Q2 release)",
    "New York-Jersey City-White Plains MSAD：1年 +5.72%，5年 +45.06%，1991年以来 +350.02%":
        "New York-Jersey City-White Plains MSAD: 1-yr +5.72%, 5-yr +45.06%, since 1991 +350.02%",
    "FHFA HPI 2026Q2 发布（州表 + Top100 MSA/MSAD 表）": "FHFA HPI 2026Q2 release (state table + top-100 MSA/MSAD table)",
    "MSAD 指数序列以 FRED ATNHPIUS35614Q 为准，最新值请点链接查看（本页嵌入值待补）":
        "The MSAD series follows FRED ATNHPIUS35614Q; open the link for the latest value (embedded values pending)",
    "AZ州 2025Q2→2026Q2 同比 +0.58%，5年 +27.45%（FHFA HPI 2026Q2 发布）":
        "AZ state 2025Q2→2026Q2 YoY +0.58%, 5-yr +27.45% (FHFA HPI 2026Q2 release)",
    "FHFA（经 FRED 发布）；序列值逐条核验自 FRED 系列页": "FHFA (via FRED); each series value checked against the FRED series page",
    "2026-08-25（FRED 页面 Updated: Aug 25, 2026）": "2026-08-25 (FRED page Updated: Aug 25, 2026)",
    "FL州 2025Q2→2026Q2 同比 +0.96%，5年 +37.47%（FHFA HPI 2026Q2 发布）":
        "FL state 2025Q2→2026Q2 YoY +0.96%, 5-yr +37.47% (FHFA HPI 2026Q2 release)",
    "2026-09-29 抓取时 FRED 页面最新仅到 2024Q4（该市场序列更新较慢），最新季度请点 FRED 链接":
        "When fetched on 2026-09-29 the FRED page only went to 2024Q4 (this series updates slowly); open the FRED link for the latest quarter",
    "NAR Economists 坦帕本地市场报告：中位价 $405,200，同比 +3.9%，3年 +37.4%":
        "NAR Economists Tampa local market report: median price $405,200, YoY +3.9%, 3-yr +37.4%",
    "2024Q1（报告发布时）": "2024Q1 (as of the report)",
    "BLS 坦帕地区主要居所租金 CPI（经 FRED）": "BLS Tampa-area rent of primary residence CPI (via FRED)",
    "FHFA（经 FRED 发布）；本地中位价来自 NAR；租金 CPI 来自 BLS": "FHFA (via FRED); local median price from NAR; rent CPI from BLS",
    "州涨幅 2026-08-25；MSA 序列 2024Q4（旧）；NAR 本地价 2024Q1": "State change 2026-08-25; MSA series 2024Q4 (stale); NAR local price 2024Q1",
    "Dallas-Fort Worth-Arlington, TX (MSA)；州口径 TX": "Dallas-Fort Worth-Arlington, TX (MSA); state basis TX",
    "TX州 2025Q2→2026Q2 同比 +0.45%，5年 +25.11%（FHFA HPI 2026Q2 发布）":
        "TX state 2025Q2→2026Q2 YoY +0.45%, 5-yr +25.11% (FHFA HPI 2026Q2 release)",
    "FHFA HPI 2026Q2 发布（州表）": "FHFA HPI 2026Q2 release (state table)",
    "Dallas-Fort Worth-Arlington MSA 指数序列见 FHFA 下载页（HPI Datasets），本页嵌入值待补":
        "Dallas-Fort Worth-Arlington MSA series: see the FHFA download page (HPI Datasets); embedded values pending",
    "GA州 2025Q2→2026Q2 同比 +1.90%，5年 +39.22%（FHFA HPI 2026Q2 发布）":
        "GA state 2025Q2→2026Q2 YoY +1.90%, 5-yr +39.22% (FHFA HPI 2026Q2 release)",
    "2026-09-29 抓取时 FRED 页面最新到 2024Q4（Updated: Feb 25, 2025），最新季度请点 FRED 链接":
        "When fetched on 2026-09-29 the FRED page went to 2024Q4 (Updated: Feb 25, 2025); open the FRED link for the latest quarter",
    "州涨幅 2026-08-25；MSA 序列 2024Q4（旧）": "State change 2026-08-25; MSA series 2024Q4 (stale)",
    "FHFA 房价指数数据集下载页": "FHFA house price index datasets",
    "州/MSA/县三级 HPI，免费下载（purchase-only 与 all-transactions）":
        "State / MSA / county HPI, free download (purchase-only and all-transactions)",
    "FRED · 凤凰城 MSA 房价指数": "FRED · Phoenix MSA house price index",
    "FRED · 坦帕 MSA 房价指数": "FRED · Tampa MSA house price index",
    "FRED · 亚特兰大 MSA 房价指数": "FRED · Atlanta MSA house price index",
    "FRED · 纽约 MSAD 房价指数": "FRED · New York MSAD house price index",
    "FRED · 全美房价指数": "FRED · US house price index",
    "ATNHPIUS38060Q，季度，1995Q1=100": "ATNHPIUS38060Q, quarterly, 1995Q1=100",
    "ATNHPIUS45300Q，季度，1995Q1=100": "ATNHPIUS45300Q, quarterly, 1995Q1=100",
    "ATNHPIUS12060Q，季度，1995Q1=100": "ATNHPIUS12060Q, quarterly, 1995Q1=100",
    "ATNHPIUS35614Q，季度，1995Q1=100": "ATNHPIUS35614Q, quarterly, 1995Q1=100",
    "USSTHPI，季度，1980Q1=100": "USSTHPI, quarterly, 1980Q1=100",
    "NAR · 坦帕本地市场报告": "NAR · Tampa local market report",
    "含中位价、同比/3年涨幅（2024Q1）": "Median price, YoY and 3-yr change (2024Q1)",
    "Census · 坦帕 QuickFacts": "Census · Tampa QuickFacts",
    "人口、住房、收入等普查快照": "Census snapshot: population, housing, income",
    "BLS · 各州失业率历史": "BLS · State unemployment history",
    "州失业率历史表（就业市场调查用）": "State unemployment history table (for employment research)",
    "BLS · 各都市区失业率": "BLS · Metro-area unemployment",
    "JOLTS/失业率图表（含都市区）": "JOLTS / unemployment charts (incl. metro areas)",
    "FHFA All-Transactions HPI：用销售价格 + 评估值（refi 评估）估算的重复交易指数，是价格指数（index），不是房价本身；不能直接换算成 $/SF 或具体房产价值。":
        "FHFA All-Transactions HPI: a repeat-transaction index estimated from sale prices plus appraisals (refi appraisals). "
        "It is a price index, not a house price; it cannot be converted directly into $/SF or a specific property's value.",
    "FHFA House Price Index 2026年Q2发布": "FHFA House Price Index 2026 Q2 release",
}


def translate(obj: Any) -> Any:
    """Deep copy of obj with every string that has an EN entry replaced."""
    if isinstance(obj, str):
        return EN.get(obj, obj)
    if isinstance(obj, dict):
        return {k: translate(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [translate(v) for v in obj]
    return obj
