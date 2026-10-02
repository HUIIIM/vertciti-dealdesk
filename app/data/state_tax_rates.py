"""美国各州平均 effective property tax rate（静态表）.

来源：Tax Foundation《Property Taxes by State and County》(2024)，基于 U.S. Census Bureau ACS。
口径：州平均 effective rate = 实缴税总额 / 住房总值。county 级差异巨大，仅作估算初值。
刷新：每年 Tax Foundation 更新后，人工核对并更新本表（见 tools/refresh_tax_rates.py）。
"""

SOURCE = "Tax Foundation 2024（基于 Census ACS）"
SOURCE_URL = "https://taxfoundation.org/data/all/state/property-taxes-by-state-and-county/"
CALIBRATION_NOTE = "州平均税率估算，待独立验证"

# key: USPS 州缩写，value: effective rate（小数，如 0.0130 = 1.30%）
STATE_PROPERTY_TAX = {
    "AL": 0.0037, "AK": 0.0094, "AZ": 0.0048, "AR": 0.0056, "CA": 0.0070,
    "CO": 0.0050, "CT": 0.0154, "DE": 0.0054, "DC": 0.0060, "FL": 0.0078,
    "GA": 0.0079, "HI": 0.0029, "ID": 0.0050, "IL": 0.0188, "IN": 0.0076,
    "IA": 0.0133, "KS": 0.0121, "KY": 0.0074, "LA": 0.0055, "ME": 0.0098,
    "MD": 0.0092, "MA": 0.0100, "MI": 0.0119, "MN": 0.0100, "MS": 0.0058,
    "MO": 0.0089, "MT": 0.0061, "NE": 0.0144, "NV": 0.0050, "NH": 0.0150,
    "NJ": 0.0188, "NM": 0.0063, "NY": 0.0130, "NC": 0.0066, "ND": 0.0092,
    "OH": 0.0136, "OK": 0.0079, "OR": 0.0081, "PA": 0.0126, "RI": 0.0112,
    "SC": 0.0049, "SD": 0.0100, "TN": 0.0052, "TX": 0.0140, "UT": 0.0048,
    "VT": 0.0151, "VA": 0.0078, "WA": 0.0075, "WV": 0.0051, "WI": 0.0132,
    "WY": 0.0053,
}

# 全名 → 缩写（Census geocoder 返回缩写；Mapbox/用户手输可能返回全名，兜底用）
STATE_NAME_TO_ABBR = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "district of columbia": "DC", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN",
    "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
    "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH",
    "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH",
    "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY",
}


def get_rate(state: str) -> float | None:
    """州缩写或全名 → effective rate；查不到返回 None（调用方必须处理，不能瞎填）。"""
    if not state:
        return None
    s = state.strip()
    abbr = s.upper() if len(s) == 2 else STATE_NAME_TO_ABBR.get(s.lower())
    return STATE_PROPERTY_TAX.get(abbr) if abbr else None
