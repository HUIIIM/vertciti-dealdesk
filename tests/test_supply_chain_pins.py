"""Supply-chain pinning guards (SEC-A5, backlog #31).

These tests fail CI if any of the pinning invariants regress:
- every GitHub Actions `uses:` reference is pinned to a full commit SHA;
- requirements.txt / requirements-dev.txt use exact `==` pins only;
- every direct production pin also appears, identically, in the
  requirements.lock.txt closure;
- the SBOM generator emits a valid CycloneDX document covering exactly
  the locked components.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
USES_RE = re.compile(r"uses:\s*([^\s#]+)")


def _requirement_lines(path: Path) -> list[str]:
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and not line.startswith("-r"):
            lines.append(line)
    return lines


def _pins(path: Path) -> dict[str, str]:
    from tools.generate_sbom import normalize, parse_pins

    text = path.read_text(encoding="utf-8")
    return {normalize(name): version for name, version in parse_pins(text)}


def test_all_action_references_pinned_to_commit_sha():
    workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflows, "no workflow files found"
    offenders = []
    for wf in workflows:
        for lineno, raw in enumerate(
            wf.read_text(encoding="utf-8").splitlines(), start=1
        ):
            match = USES_RE.search(raw)
            if not match:
                continue
            ref = match.group(1).strip().strip('"').strip("'")
            if ref.startswith("./") or ref.startswith("docker://"):
                continue
            assert "@" in ref, f"{wf.name}:{lineno}: no ref in {ref!r}"
            sha = ref.rsplit("@", 1)[1]
            if not SHA_RE.match(sha):
                offenders.append(f"{wf.name}:{lineno}: {ref}")
    assert not offenders, "unpinned action references:\n" + "\n".join(offenders)


def test_requirements_files_are_exact_pins_only():
    for name in ("requirements.txt", "requirements-dev.txt"):
        lines = _requirement_lines(ROOT / name)
        assert lines, f"{name} has no requirements"
        for line in lines:
            assert "==" in line, f"{name}: not an exact pin: {line!r}"
            assert not re.search(r"[<>~!]", line.split("==", 1)[0] + "=="), line


def test_lock_covers_every_direct_production_pin():
    direct = _pins(ROOT / "requirements.txt")
    lock = _pins(ROOT / "requirements.lock.txt")
    missing = {
        name: ver for name, ver in direct.items() if lock.get(name) != ver
    }
    assert not missing, f"direct pins missing/mismatched in lock: {missing}"
    assert len(lock) > len(direct), "lock must include the transitive closure"


def test_sbom_covers_exactly_the_lock(tmp_path):
    from tools.generate_sbom import build_sbom, parse_pins

    lock_text = (ROOT / "requirements.lock.txt").read_text(encoding="utf-8")
    pins = parse_pins(lock_text)
    sbom = build_sbom(pins)
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.5"
    components = sbom["components"]
    assert len(components) == len(pins)
    for comp in components:
        assert comp["type"] == "library"
        assert comp["purl"] == (
            f"pkg:pypi/{comp['name'].lower()}@{comp['version']}".replace(
                "_", "-"
            )
        )
    # deterministic: rebuilding yields the identical document
    assert build_sbom(pins) == sbom
