#!/usr/bin/env python3
"""Generate a CycloneDX 1.5 SBOM from a pinned requirements lock file.

SEC-A5 (backlog #31): the SBOM is derived from requirements.lock.txt, the
exact-pin closure of the production dependencies, so it describes the
shipped dependency set rather than whatever happens to be installed on
the machine that runs the script. Standard library only; deterministic
output (components sorted by name, no timestamps), so CI can diff it.

Usage:
    python tools/generate_sbom.py [--requirements requirements.lock.txt]
                                  [--output sbom.cdx.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PIN_RE = re.compile(
    r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?==([^\s;#]+)\s*(?:#.*)?$"
)


def parse_pins(text: str) -> list[tuple[str, str]]:
    """Parse `name==version` lines; comments/blank lines are skipped.

    Any non-empty, non-comment line that is not an exact pin is a hard
    error: a lock file with a floating requirement is not a lock file.
    """
    pins: list[tuple[str, str]] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-r"):
            continue
        match = PIN_RE.match(line)
        if not match:
            raise ValueError(f"line {lineno}: not an exact pin: {raw!r}")
        pins.append((match.group(1), match.group(2)))
    return pins


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def build_sbom(pins: list[tuple[str, str]]) -> dict:
    components = []
    for name, version in sorted(pins, key=lambda p: normalize(p[0])):
        components.append(
            {
                "type": "library",
                "bom-ref": f"pkg:pypi/{normalize(name)}@{version}",
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{normalize(name)}@{version}",
                "scope": "required",
            }
        )
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "tools": [
                {
                    "vendor": "vertciti",
                    "name": "dealdesk-generate-sbom",
                    "version": "1.0.0",
                }
            ],
            "component": {
                "type": "application",
                "bom-ref": "pkg:pypi/vertciti-dealdesk",
                "name": "vertciti-dealdesk",
            },
        },
        "components": components,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--requirements",
        default="requirements.lock.txt",
        help="pinned lock file to read (default: requirements.lock.txt)",
    )
    parser.add_argument(
        "--output",
        default="sbom.cdx.json",
        help="where to write the SBOM (default: sbom.cdx.json)",
    )
    args = parser.parse_args(argv)
    text = Path(args.requirements).read_text(encoding="utf-8")
    sbom = build_sbom(parse_pins(text))
    Path(args.output).write_text(
        json.dumps(sbom, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {args.output}: {len(sbom['components'])} components")
    return 0


if __name__ == "__main__":
    sys.exit(main())
