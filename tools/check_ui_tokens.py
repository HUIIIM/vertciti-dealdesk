#!/usr/bin/env python3
"""UI token adjudication check (Appendix-3 ruling values).

Asserts the adjudicated brand token values are in force and that none of
the superseded values survive in any tracked text file.

Exit 0 = pass; exit 1 = violations listed on stdout.
"""
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

EXPECTED = {
    "ORANGE_TINT": "#FFF0EB",
    "NAV_GREY": "#DEDEDE",
}
OLD_VALUES = ["#FFEDE7", "#BDBDBD", "#E6B8B4"]
EXPECTED_LITERALS = ["#FFF0EB", "#DEDEDE", "#F9DEDC"]

failures = []

brand_py = (ROOT / "app/core/brand.py").read_text(encoding="utf-8")
for name, want in EXPECTED.items():
    m = re.search(rf'^{name}\s*=\s*"(#[0-9A-Fa-f]{{6}})"', brand_py, re.M)
    if not m:
        failures.append(f"app/core/brand.py: {name} not found")
    elif m.group(1).upper() != want:
        failures.append(f"app/core/brand.py: {name}={m.group(1)} != adjudicated {want}")

try:
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
except Exception as e:  # pragma: no cover
    print(f"cannot list tracked files: {e}")
    sys.exit(1)

SELF = pathlib.Path(__file__).resolve()
for rel in tracked:
    p = ROOT / rel
    if p.resolve() == SELF:
        continue  # the banned-value list lives in this file; skip self-scan
    if not p.is_file():
        continue
    try:
        text = p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    for old in OLD_VALUES:
        if old in text or old.lower() in text:
            failures.append(f"{rel}: superseded value {old} still present")

for lit in EXPECTED_LITERALS:
    if not any(lit in (ROOT / rel).read_text(encoding="utf-8", errors="ignore") for rel in tracked if (ROOT / rel).is_file()):
        failures.append(f"adjudicated value {lit} not found in any tracked file")

if failures:
    print("check_ui_tokens: FAIL")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("check_ui_tokens: PASS (adjudicated values in force, superseded values absent)")
