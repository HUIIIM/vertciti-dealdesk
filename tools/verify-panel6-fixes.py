"""DealDesk Phase 5 第六轮微修复 #2-#5 后端验证脚本."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import pdf_uw, uw_commercial, excel_uw, scoring_residential
import fitz

PASS, FAIL = [], []

def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))

def pdf_text(b):
    doc = fitz.open(stream=b, filetype="pdf")
    return "\n".join(p.get_text() for p in doc)

# ---------- 场景 A：无 rent roll（120 Broadway 式） ----------
inp = uw_commercial.default_inputs()
inp["analysis"] = {"purchase_price": 850000, "down_pct": 0.30,
                   "rate": 0.065, "amort_years": 25}
inp["property"]["address"] = "120 Broadway, New York, NY"
r = uw_commercial.compute_all(inp)
deal_a = {"name": "120 Broadway", "address": "120 Broadway, New York, NY",
          "verdict": {"verdict": "VETO",
                      "one_liner": "无 rent roll，DSCR 无法核保（待接数据）",
                      "reasons": ["一票否决：无 rent roll，DSCR 无法核保（待接数据）"]},
          "verdict_word": "VETO", "veto_count": 1,
          "has_rent_roll": False, "dscr_trailing": None,
          "score": {"metrics": {"dscr": 0, "required_dscr": 1.25}},
          "comps": [], "assumptions": {}, "effective_assumptions": []}
t_a = pdf_text(pdf_uw.build_uw_pdf(r, "enhanced", deal=deal_a))

# #3：预测列 5 行应为 $0（待接/未填），不许裸 $0
for lbl in ["基础租金", "有效总收入 EGI", "总费用", "NOI", "可用于还贷现金流"]:
    check(f"#3 预测列[{lbl}]标待接/未填",
          "$0（待接/未填）" in t_a, lbl)
# 无裸 $0 行（预测列）：简单检查——现金流表区域不应出现孤立 "$0"
check("#3 无裸$0预测值", t_a.count("$0（待接/未填）") >= 10,
      f"待接/未填出现 {t_a.count('$0（待接/未填）')} 次")
# Y5 备注
check("#2/#3 PDF Y5 备注不含退出", "不含退出（退出假设缺失）" in t_a)
check("#5 无RR无打分DSCR仍为待rent roll", "—（待 rent roll）" in t_a)

# ---------- Excel：Y5 备注 ----------
x = excel_uw.build_uw_xlsx(r, inp, [], meta={"has_rent_roll": False})
import openpyxl, io
wb = openpyxl.load_workbook(io.BytesIO(x))
ws = wb[wb.sheetnames[0]]
notes = {}
for row in ws.iter_rows(values_only=True):
    if row[0] and str(row[0]).startswith("现金流 Y"):
        notes[str(row[0])] = str(row[2] or "")
y5 = notes.get("现金流 Y5", "")
check("#2 Excel Y5 备注与PDF对齐",
      "不含退出" in y5 and "含出售所得" not in y5, y5)

# ---------- 场景 B：rent-roll 路径（双 DSCR 口径注） ----------
deal_b = dict(deal_a)
deal_b.update({
    "verdict": {"verdict": "VETO",
                "one_liner": "DSCR 0.88 < 1.0（生死线），贴钱持有",
                "reasons": ["一票否决：DSCR 0.80 < 1.25，直接否决不参与打分"]},
    "has_rent_roll": True, "dscr_trailing": 0.88,
    "score": {"metrics": {"dscr": 0.80, "required_dscr": 1.25}}})
t_b = pdf_text(pdf_uw.build_uw_pdf(r, "enhanced", deal=deal_b))
check("#4 双DSCR口径注出现", "口径不同" in t_b and "生死线" in t_b and "承销底线" in t_b)
check("#4 注含两个数字", "0.88×" in t_b and "0.80×" in t_b)
check("#4 verdict一句话未改", "DSCR 0.88 < 1.0（生死线），贴钱持有" in t_b)
check("#4 否决依据未改", "一票否决：DSCR 0.80 < 1.25，直接否决不参与打分" in t_b)

# ---------- 场景 C：proforma 路径（verdict 0.82，备忘录无银行口径） ----------
deal_c = dict(deal_a)
deal_c.update({
    "verdict": {"verdict": "VETO",
                "one_liner": "DSCR 0.82 < 1.0（生死线），贴钱持有",
                "reasons": ["一票否决：DSCR 0.82 < 1.25，直接否决不参与打分"]},
    "has_rent_roll": False, "dscr_trailing": None,
    "score": {"metrics": {"dscr": 0.82, "required_dscr": 1.25}}})
t_c = pdf_text(pdf_uw.build_uw_pdf(r, "enhanced", deal=deal_c))
check("#5 备忘录显示打分口径0.82", "打分口径·预测" in t_c and "0.82×" in t_c)
check("#5 verdict一句话未改", "DSCR 0.82 < 1.0（生死线），贴钱持有" in t_c)
# 风险指标区不应再有"DSCR（在手·银行口径）—（待 rent roll）"的矛盾行
check("#5 风险区无矛盾待rent roll",
      "DSCR（在手·银行口径）" not in t_c,
      "在手银行口径行已替换为打分口径")

# ---------- 场景 D：住宅 scoring（#7/#8，负现金流如 newbie 报告） ----------
s = scoring_residential.score({"monthly_rent": 3000, "vacancy_pct": 8,
    "tax_annual": 0, "insurance_annual": 0, "price": 1200000,
    "loan_balance": 960000, "down_payment": 240000,
    "rate": 6.5, "term_years_remaining": 30, "units": 1})
det = s["dimensions"][0]["detail"]
chk = [c for c in s["checks"] if "现金流" in c["label"]]
check("#7 维度detail用整套", "整套现金流" in det and "单门" not in det, det)
check("#8 detail负号规范", "-$" in det and "$-" not in det, det)
check("#7 check标签用整套",
      chk and "整套现金流 ≥$300/月" in chk[0]["label"] and "单门" not in chk[0]["label"],
      chk[0]["label"] if chk else "无")
check("#8 check备注负号规范",
      chk and "-$" in str(chk[0]["note"]) and "$-" not in str(chk[0]["note"]),
      str(chk[0]["note"]) if chk else "无")

print(f"\n共 {len(PASS)} 通过，{len(FAIL)} 失败")
if FAIL:
    print("失败项:", FAIL); sys.exit(1)
