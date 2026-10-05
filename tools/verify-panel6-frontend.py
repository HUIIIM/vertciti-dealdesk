"""DealDesk Phase 5 第六轮微修复 #1/#6/#8 前端验证（Playwright + Firefox headless）."""
import re
import sys
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8471"
PASS, FAIL = [], []

def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))

JS_COM = """
() => {
  state.type = 'com';
  state.assumptions.ask = 850000;
  state.uw = {plus: {has_rent_roll: false, noi_bank_bridge: {bank_noi: -2890}}, analysis: {}};
  state.score = {metrics: {}};
  renderZone2();
  return document.querySelector('#z2').innerHTML;
}
"""

JS_COM_RR = """
() => {
  state.uw = {plus: {has_rent_roll: true, noi_bank_bridge: {bank_noi: 51000},
    dscr_dual: {trailing: {dscr: 0.88, label: 'x'}, proforma: {dscr: 0.92}},
    debt_yield: 0.09, rent_roll_detail: {occupancy: 0.95}}, analysis: {breakeven_occupancy: 0.8}};
  renderZone2();
  return document.querySelector('#z2').innerHTML;
}
"""

JS_RES = """
() => {
  state.type = 'res';
  state.assumptions.ask = 1200000;
  state.assumptions.down = 240000;
  state.assumptions.rate = 6.5;
  state.assumptions.rent = 3000;
  state.assumptions.vac = 8;
  state.score = {metrics: {cash_flow_monthly: -7584.82, opex: 0, monthly_pi: 6068.10}};
  state.intake = {fields: [{key: 'taxes_annual', value: 27200, display: '$27,200/年（2025）'}]};
  renderZone4();
  return document.querySelector('#z4Body').innerHTML;
}
"""

JS_RES_NOTAX = """
() => {
  state.intake = {fields: []};
  renderZone4();
  return document.querySelector('#z4Body').innerHTML;
}
"""

def cap_val(html):
    m = re.search(r'Trailing cap</div><div class="k-val[^"]*">([^<]*)</div>', html)
    return m.group(1) if m else "NOTFOUND"

with sync_playwright() as p:
    b = p.firefox.launch(headless=True)
    pg = b.new_page()

    pg.goto(BASE + "/d?type=com", wait_until="networkidle")
    z2 = pg.evaluate(JS_COM)
    check("#1 无RR时Trailing cap显示—", cap_val(z2) == "—", "实测=" + cap_val(z2))
    check("#1 幽灵-0.34%已消除", "-0.34%" not in z2 and "-0.35%" not in z2)
    m = re.search(r'Trailing cap</div><div class="k-val[^"]*">[^<]*</div>\s*<div class="k-sub">([^<]*)</div>', z2)
    check("#1 sub注记待rent roll", bool(m and "待 rent roll" in m.group(1)),
          m.group(1) if m else "无sub")

    z2b = pg.evaluate(JS_COM_RR)
    check("#1 有RR时正常显示cap", cap_val(z2b) == "6.00%", "实测=" + cap_val(z2b))

    fmt = pg.evaluate("() => ({a: fmt$(-8000), b: fmt$(-7584.82), g: fmt$(-585), c: fmt$(8000), d: fmt$(-2500000), e: fmt$(0), f: fmt$(null)})")
    check("#8 fmt$(-8000)=-$8K", fmt["a"] == "-$8K", fmt["a"])
    check("#8 fmt$(-7584.82)=-$8K（K位）", fmt["b"] == "-$8K", fmt["b"])
    check("#8 fmt$(-585)=-$585", fmt["g"] == "-$585", fmt["g"])
    check("#8 正数/零/null不变",
          fmt["c"] == "$8K" and fmt["d"] == "-$2.50M" and fmt["e"] == "$0" and fmt["f"] == "—",
          str(fmt))

    pg.goto(BASE + "/d?type=res", wait_until="networkidle")
    z4 = pg.evaluate(JS_RES)
    check("#6 档案税解释句出现",
          "档案税" in z4 and "$27,200/年（2025）" in z4 and "未采用" in z4)
    check("#6 原因一句话（公共记录未经核验）", "公共记录未经核验" in z4)
    check("#8 每月净剩-$8K", "-$8K" in z4 and "$-8K" not in z4)
    check("#8 无$-残留", "$-" not in z4)

    z4b = pg.evaluate(JS_RES_NOTAX)
    check("#6 无档案税时不硬编数字", "档案税" not in z4b and "27,200" not in z4b)

    b.close()

print("\n共 %d 通过，%d 失败" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
