"""vertciti 品牌 DNA 令牌（后端唯一真源）。

品牌侧锚：品牌组 canonical 规格（deliverables/brand-assets/brand-tokens-canonical-2026-10-26/）；
派生色经品牌组 2026-10-27 裁定归一至全舰队登记阶（dealdesk-token-ruling-prep-2026-10-27.md），值冻结。
黑白为主、信号橙点睛；绿 = 已验证 / 达标，黄 = 待复核，红 = 风险 / 否决。
HTML 报告、SVG/PNG 图表、PDF、Tear Sheet 一律从这里取色，不再各写一套。
"""

from __future__ import annotations

# ---- 基础色（tokens.json）
INK = "#000000"
PAPER = "#FFFFFF"
ORANGE = "#FF4713"       # 信号橙：图形标记、品牌强调（不用作白底小字）
YELLOW = "#FFCE00"       # 证据黄：底色 / 标记
GREEN = "#1D8348"        # 验证绿
GRAPHITE = "#3F3F3F"
STONE = "#6B6B6B"
LINE = "#DEDEDE"
MIST = "#F5F5F5"

# ---- 派生色（2026-10-27 裁定登记阶，白底文字对比度 ≥ 4.5:1）
ORANGE_TEXT = "#C93308"  # 信号橙深色版：白底上的强调文字
AMBER_TEXT = "#7A5C00"   # 提示 / 待复核文字
RED = "#B3261E"          # 风险 / 错误 / 否决（canonical --status-error，全舰队唯一状态红）
LINE_SOFT = "#ECECEC"
GREEN_TINT = "#EAF4EE"
YELLOW_TINT = "#FFF6CC"
RED_TINT = "#F9DEDC"
ORANGE_TINT = "#FFF0EB"  # 品牌组 2026-10-27 裁定调值归一至登记值（原 #FFEDE7 已入退役词表）；唯一消费＝服务端图表数据填充
NAV_GREY = "#BDBDBD"     # 余用仅经典版 PDF 网格线（pdf_uw）；品牌组 2026-10-27 裁定归一 brand.LINE 方向、随下一次后端批改，不单跑
DARK_BAR_LINK = "#C8C8C8"  # 黑底品牌条次级链接字（品牌组 2026-10-27 裁定自 NAV_GREY 拆分归一，与暗面梯 --text-2 同角色）

# 对外面（报告/导出）字体栈＝canonical 栈逐字（品牌组 2026-10-27 裁定四）
FONT_STACK = ('"Nunito Sans","PingFang SC","Hiragino Sans GB","Microsoft YaHei",'
              '"Noto Sans SC",sans-serif')

# 打分等级配色（A 达标绿 / B 中性石墨 / C 待复核琥珀 / 否决红 / D 石灰）
GRADE_COLORS = {"A": GREEN, "B": GRAPHITE, "C": AMBER_TEXT, "否决": RED, "D": STONE}
GRADE_BG = {"A": GREEN_TINT, "B": MIST, "C": YELLOW_TINT, "否决": RED_TINT, "D": MIST}


def rgb(hex_color: str) -> tuple[int, int, int]:
    """'#RRGGBB' → (r, g, b)，给 Pillow 用。"""
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# ---- 服务端 HTML 报告共用样式与品牌条（与 static/vc-dna.css 同口径）
REPORT_CSS = f"""
 *{{border-radius:0!important}}
 html{{overflow-x:hidden}}
 body{{font-family:{FONT_STACK};max-width:900px;margin:0 auto;padding:0 20px 32px;color:{INK};background:{PAPER};
   line-height:1.65;-webkit-font-smoothing:antialiased}}
 .vc-util{{background:{INK};color:{PAPER};font-size:13px;min-height:44px;display:flex;align-items:center;gap:20px;
   padding:0 24px;margin:0 calc(50% - 50vw) 24px}}
 .vc-util a{{color:{DARK_BAR_LINK};text-decoration:none;font-weight:700;min-height:44px;display:inline-flex;align-items:center;
   border-bottom:3px solid transparent}}
 .vc-util a[aria-current]{{color:{PAPER};border-bottom-color:{ORANGE}}}
 .vc-util .lg{{font-weight:900;font-size:16px;letter-spacing:-.02em;color:{PAPER}}}
 .vc-util .lg i{{display:inline-block;width:5px;height:5px;background:{ORANGE};margin:0 0 3px 2px}}
 .vc-util .sp{{flex:1}}
 h1{{font-size:28px;font-weight:800;line-height:1.2;margin:8px 0}}
 h2{{font-size:17px;font-weight:800;border-bottom:2px solid {INK};padding-bottom:4px;margin-top:32px}}
 .eyebrow{{font-size:12px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;display:flex;align-items:center;gap:10px;margin:0}}
 .eyebrow::before{{content:"";width:24px;height:4px;background:{ORANGE}}}
 table{{width:100%;border-collapse:collapse;margin:8px 0;font-size:14px}}
 th,td{{border-bottom:1px solid {LINE};padding:8px 12px;text-align:left;vertical-align:top}}
 th{{background:{MIST};font-weight:800;color:{GRAPHITE}}}
 td.num{{text-align:right;font-variant-numeric:tabular-nums}}
 .meta{{color:{STONE};font-size:13px}}
 .mono{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px}}
 .warn{{color:{AMBER_TEXT};font-weight:700}}
 .disclaimer{{font-size:12px;color:{STONE};border-top:1px solid {LINE};margin-top:32px;padding-top:8px}}
 button{{font:inherit;font-weight:800;min-height:44px;padding:0 20px;border:2px solid {INK};background:{INK};color:{PAPER};cursor:pointer}}
 button:hover{{background:{ORANGE};border-color:{ORANGE};color:{INK}}}
 :focus-visible{{outline:3px solid {ORANGE};outline-offset:2px}}
 @media print{{.noprint,.vc-util{{display:none}} body{{margin:0}}}}
 @media (prefers-reduced-motion:reduce){{*{{transition:none!important;animation:none!important}}}}
"""

REPORT_BRAND_BAR = (
    '<div class="vc-util noprint" role="navigation" aria-label="vertciti">'
    '<a class="lg" href="https://vertciti.com" aria-label="vertciti 官网">vertciti<i></i></a>'
    '<a href="/" aria-current="page">DealDesk</a><span class="sp"></span>'
    '<a href="https://vertciti.com/business/">vertciti 业务版图</a></div>'
)
