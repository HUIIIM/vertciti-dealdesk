#!/usr/bin/env python3
"""UI token reconciliation: brand canonical tokens (2026-10-26 spec) vs DealDesk v2 tokens.

Compares the mapped base tokens (colors / spacing / motion / font) between
the brand canonical spec tokens.css (semantic names; supersedes brand kit
v1.0/v1.1 --vc-* names, values unchanged) and DealDesk's light :root block.
Dark-theme and other DealDesk-only variables are reported as extensions,
not failures. Exit 1 iff a mapped base token differs or is missing.

Usage: check_ui_tokens.py [--brand PATH] [--dealdesk PATH]
Defaults resolve relative to the vertcity workspace layout.
"""
import argparse, re, sys
from pathlib import Path

HOME = Path.home()
DEF_BRAND = HOME / "workspace/vertcity/deliverables/brand-assets/brand-tokens-canonical-2026-10-26/tokens.css"
DEF_DD = HOME / "workspace/vertcity/dealdesk/frontend/src/styles/tokens.css"

# canonical brand var -> dealdesk var (base layer, light theme)
MAP = {
    "--color-ink": "--ink", "--color-paper": "--paper", "--brand-primary": "--orange",
    "--brand-evidence": "--yellow", "--status-verified": "--green",
    "--color-text-secondary": "--graphite", "--color-text-tertiary": "--stone",
    "--color-border": "--line", "--color-surface-alt": "--mist",
    "--space-1": "--s1", "--space-2": "--s2", "--space-3": "--s3",
    "--space-4": "--s4", "--space-6": "--s5", "--space-8": "--s6",
    "--space-12": "--s7", "--space-16": "--s8",
    "--easing-standard": "--ease", "--duration-micro": "--dur", "--duration-reveal": "--dur-in",
}
SEMANTIC_PREFIXES = ("--bg", "--surface", "--text", "--border", "--hover", "--selected",
                     "--ok", "--warn", "--risk", "--plan", "--accent", "--shadow", "--font",
                     "--mono", "--row-h", "--fs", "--cell-px", "--dur-grow")

# Brand-group ruling 2026-10-27 (dealdesk-token-ruling-prep-2026-10-27.md):
# registered DealDesk derivative values, frozen. var -> expected value.
RULED_LIGHT = {
    "--orange-text": "#c93308", "--amber-text": "#7a5c00", "--ok": "#145c32",
    "--ok-bg": "#eaf4ee", "--warn-bg": "#fff6cc", "--risk-bg": "#f9dedc",
    "--selected": "#fff0eb", "--line-soft": "#ececec", "--hover": "#f0f0f0",
    "--red": "#b3261e",
}
RULED_DARK = {
    "--bg": "#000000", "--text": "#ffffff", "--warn": "#ffce00",
    "--risk": "#f2b8b5", "--accent-text": "#ff8a66", "--ok": "#5fc48a",
    "--ok-mark": "#3fa86a", "--border": "#2e2e2e", "--line-soft": "#242424",
    "--hover": "#1f1f1f",
}
# Values retired by the 2026-10-27 ruling; must be zero-hit in carrier files.
RETIRED = ["#c93410", "#8a5a00", "#17703c", "#e8f3ec", "#fff5cc", "#f7e9e8",
           "#fff3ee", "#0b0b0b", "#f2f2f2", "#f2c94c", "#ff8a80", "#ff7a52"]
DEF_CARRIERS = ["frontend/src/styles/tokens.css", "app/core/brand.py",
                "app/services/render/pdf_report.py"]

def parse_vars(text, first_root_only=False):
    if first_root_only:
        m = re.search(r":root\s*\{(.*?)\n\}", text, re.S)
        text = m.group(1) if m else ""
    out = {}
    for name, val in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", text):
        out.setdefault(name, val.strip())
    return out

def norm(v):
    # whitespace-insensitive + numeric-representation-insensitive:
    # cubic-bezier(0.2, 0.7, 0.2, 1) == cubic-bezier(.2,.7,.2,1) (same numbers,
    # different leading-zero spelling); distinct numbers never collapse.
    s = re.sub(r"\s+", "", v.strip().lower())
    def canon(m):
        return "%g" % float(m.group(0))
    return re.sub(r"\d*\.\d+|\d+", canon, s)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", default=str(DEF_BRAND))
    ap.add_argument("--dealdesk", default=str(DEF_DD))
    a = ap.parse_args()
    brand = parse_vars(Path(a.brand).read_text())
    dd = parse_vars(Path(a.dealdesk).read_text(), first_root_only=True)
    dd_all = parse_vars(Path(a.dealdesk).read_text())
    diffs = 0
    print("== mapped base tokens ==")
    for b, d in MAP.items():
        bv, dv = brand.get(b), dd.get(d)
        if bv is None or dv is None:
            print(f"MISSING  {b}={bv}  {d}={dv}"); diffs += 1
        elif norm(bv) == norm(dv):
            print(f"MATCH    {b} {bv} == {d} {dv}")
        else:
            print(f"DIFF     {b} {bv} != {d} {dv}"); diffs += 1
    # font: canonical font stack should head-match DealDesk --font
    bf, df = brand.get("--font-sans", ""), dd.get("--font", "")
    head = bf.split(",")[0].strip().strip('"')
    print(f"FONT     brand head {head!r} in dealdesk --font: {head in df}")
    if head not in df: diffs += 1
    # info only: canonical --status-error vs DealDesk --red (fleet flag 5 subject)
    se, dr = brand.get("--status-error"), dd_all.get("--red")
    print(f"INFO     canonical --status-error={se} vs dealdesk --red={dr}: "
          f"{'VALUE-EQUAL' if se and dr and norm(se) == norm(dr) else 'DIFFERS/ABSENT'} "
          f"(flag 5: brand ruling 2026-10-27 confirms value matches the annex-registered "
          f"fleet status red; unified ruling only backfills registration identity)")
    # ruling-registered derivative values (light :root + both dark blocks)
    dd_text = Path(a.dealdesk).read_text()
    dark_blocks = re.findall(r'\{(.*?)\n\s*\}', dd_text.split('[data-theme="dark"]', 1)[1], re.S) \
        if '[data-theme="dark"]' in dd_text else []
    print("== ruling values 2026-10-27 ==")
    for name, want in RULED_LIGHT.items():
        got = dd.get(name)
        ok = got is not None and norm(got) == norm(want)
        print(f"{'MATCH    ' if ok else 'RULEDIFF '} {name} want {want} got {got}")
        diffs += 0 if ok else 1
    dark_sets = [parse_vars(b) for b in dark_blocks[:2]] or [{}]
    for name, want in RULED_DARK.items():
        for i, ds in enumerate(dark_sets):
            got = ds.get(name)
            ok = got is not None and norm(got) == norm(want)
            print(f"{'MATCH    ' if ok else 'RULEDIFF '} dark[{i}] {name} want {want} got {got}")
            diffs += 0 if ok else 1
    # retired values zero-hit across carrier files
    repo = Path(a.dealdesk).parents[3]
    hits = 0
    for rel in DEF_CARRIERS:
        f = repo / rel
        if not f.exists():
            continue
        txt = f.read_text().lower()
        for v in RETIRED:
            if v in txt:
                print(f"RETIRED-HIT {v} in {rel}"); hits += 1
    print(f"== retired scan: {hits} hits across {len(DEF_CARRIERS)} carrier files ==")
    diffs += hits
    mapped_dd = set(MAP.values()) | {"--font"}
    ext = sorted(v for v in dd_all if v not in mapped_dd and not v.startswith(SEMANTIC_PREFIXES))
    print("== dealdesk extension vars (registered by brand ruling 2026-10-27) ==")
    for v in ext: print(f"EXT      {v}: {dd_all[v]}")
    sem = sorted(v for v in dd_all if v.startswith(SEMANTIC_PREFIXES) and v not in mapped_dd)
    print(f"== semantic/functional vars (derived layer): {len(sem)} ==")
    for v in sem: print(f"SEM      {v}: {dd_all[v]}")
    print(f"RESULT: {'FAIL' if diffs else 'PASS'} ({diffs} mapped diffs, {len(ext)} extensions)")
    return 1 if diffs else 0

if __name__ == "__main__":
    sys.exit(main())
