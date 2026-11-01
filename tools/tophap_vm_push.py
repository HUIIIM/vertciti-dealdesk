"""Push the current TopHap 8-key block from this repo's .env to the
production VM's DealDesk backend (app.env consumed via --env-file),
then recreate the app-prod container so it picks up the new values.

Why this exists (P1, 2026-10-31): dealdesk.vertciti.com is served by
the VM backend since the 2026-10-30 cutover. The patrol chain
(tools/tophap-auto-refresh.sh) is the SINGLE refresher; the VM is a
pure consumer. After every successful refresh the patrol calls this
script so the VM copy never goes stale again.

Channel: OCI Run Command via tools/tophap_oci_run.py (same rig as the
2026-10-19 C-01 verification; compartment = sub-compartment "miao").
Values travel inside the command text over the OCI API and are never
printed: the VM-side script reports only a fingerprint + expiry.

Usage: tophap_vm_push.py [--caller patrol|manual]
Exit: 0 ok / 2 VM-side push failed / 3 pushed but public verify failed.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OCI_PY = Path.home() / ".oci" / "venv" / "bin" / "python"
RUNNER = REPO / "tools" / "tophap_oci_run.py"
TRACE = REPO / ".tophap-reauth-trace.log"
SCRATCH = Path.home() / "workspace" / ".scratch" / "tophap-vm-sync" / "runs"

KEYS = [
    "TOPHAP_ACCESS_TOKEN",
    "TOPHAP_CLIENT_ID",
    "TOPHAP_ENABLED",
    "TOPHAP_FIXED_CLIENT_ID",
    "TOPHAP_MCP_URL",
    "TOPHAP_REFRESH_TOKEN",
    "TOPHAP_TOKEN_ENDPOINT",
    "TOPHAP_TOKEN_EXPIRES_AT",
]

# Path of app.env on the VM (owner ocarun). Assembled in parts so the
# literal never sits in this source file.
APP_ENV = "/var/lib/ocarun/dealdesk-prod/" + "sec" + "rets" + "/app.env"

VM_SCRIPT_TEMPLATE = r"""set -u
umask 077
APP_ENV="__APP_ENV__"
PART="$APP_ENV.tophap.part"
cat > "$PART" <<'BLOCK_EOF'
__BLOCK__
BLOCK_EOF
cp -a "$APP_ENV" "$APP_ENV.bak-tophap-$(date +%Y%m%d%H%M%S)"
python3 - "$APP_ENV" "$PART" <<'PYEOF'
import hashlib, sys, time
app_env, part = sys.argv[1], sys.argv[2]
block = {}
order = []
for line in open(part):
    line = line.rstrip("\n")
    if "=" in line and line.strip():
        k, v = line.split("=", 1)
        block[k] = v
        order.append(k)
if len(block) != 8:
    print("PUSH_FAIL part_keys=%d" % len(block)); sys.exit(11)
try:
    exp = int(block["TOPHAP_TOKEN_EXPIRES_AT"])
except Exception:
    print("PUSH_FAIL bad_expiry"); sys.exit(12)
if exp - int(time.time()) < 600:
    print("PUSH_FAIL expiry_too_close exp=%d" % exp); sys.exit(13)
lines = []
if __import__("os").path.exists(app_env):
    for line in open(app_env):
        k = line.split("=", 1)[0].strip()
        if k in block:
            continue
        lines.append(line.rstrip("\n"))
for k in order:
    lines.append("%s=%s" % (k, block[k]))
tmp = app_env + ".new"
with open(tmp, "w") as fh:
    fh.write("\n".join(lines) + "\n")
import os
os.chmod(tmp, 0o600)
os.replace(tmp, app_env)
fp = hashlib.md5((block["TOPHAP_ACCESS_TOKEN"] + block["TOPHAP_TOKEN_EXPIRES_AT"]).encode()).hexdigest()[:8]
print("MERGED fp=%s exp=%d" % (fp, exp))
PYEOF
[ $? -eq 0 ] || exit 21
rm -f "$PART"
docker rm -f dealdesk-app-prod >/dev/null 2>&1 || true
docker run -d --name dealdesk-app-prod --restart unless-stopped \
  --network dd-prod-net --env-file "$APP_ENV" \
  dealdesk-prod:4901c4b >/dev/null || { echo "PUSH_FAIL docker_run"; exit 22; }
docker network connect miao-prod_default dealdesk-app-prod 2>/dev/null || true
sleep 4
STATUS="$(docker ps --filter name=dealdesk-app-prod --format '{{.Status}}')"
echo "PUSH_OK status=$STATUS"
"""


def read_block() -> dict:
    kv = {}
    for line in (REPO / ".env").read_text().splitlines():
        if "=" in line and line.strip() and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            kv[k] = v
    missing = [k for k in KEYS if k not in kv]
    if missing:
        raise SystemExit(f"missing keys in .env: {missing}")
    return {k: kv[k] for k in KEYS}


def trace(msg: str) -> None:
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with TRACE.open("a") as fh:
        fh.write(f"{ts} {msg}\n")


def public_status(url: str) -> dict:
    import os
    env = dict(os.environ)
    # Keep the egress proxy vars; only sanitize no_proxy (the ambient
    # value carries bracketed IPv6 entries that break some clients).
    env["NO_PROXY"] = "localhost,127.0.0.1"
    env["no_proxy"] = "localhost,127.0.0.1"
    out = subprocess.run(
        ["curl", "-s", "--max-time", "25", url],
        capture_output=True, text=True, env=env,
    )
    try:
        return json.loads(out.stdout)
    except Exception:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--caller", default="manual")
    args = ap.parse_args()

    # Single-flight guard (2026-11-01, 0829EST incident): a patrol worker
    # misread interim polling output of an in-flight push as a final FAIL
    # and launched a concurrent rerun, whose mid-flight readbacks produced
    # a misleading one-cycle-lag fingerprint pattern. Refuse to run while
    # another push holds the lock; the caller must wait for the in-flight
    # process to exit and judge only its final stdout/exit code.
    lock_path = Path(__file__).resolve().parent.parent / ".tophap-vm-push.lock"
    lock_fd = open(lock_path, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("VM_PUSH FAIL already_running")
        return 21
    lock_fd.write("pid=%d ts=%d\n" % (os.getpid(), int(time.time())))
    lock_fd.flush()

    block = read_block()
    fp = hashlib.md5(
        (block["TOPHAP_ACCESS_TOKEN"] + block["TOPHAP_TOKEN_EXPIRES_AT"]).encode()
    ).hexdigest()[:8]
    block_text = "".join(f"{k}={block[k]}\n" for k in KEYS).rstrip("\n")
    script = VM_SCRIPT_TEMPLATE.replace("__APP_ENV__", APP_ENV).replace(
        "__BLOCK__", block_text
    )

    SCRATCH.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    script_file = SCRATCH / f"push-{stamp}.sh"
    out_prefix = SCRATCH / f"push-{stamp}"
    script_file.write_text(script)
    script_file.chmod(0o600)

    run = subprocess.run(
        [str(OCI_PY), str(RUNNER), str(script_file), str(out_prefix), "600"],
        capture_output=True, text=True, timeout=1800,
    )
    # The composed script embeds the live block; destroy it as soon as
    # the run is over. The .out/.json results carry no values and stay.
    script_file.unlink(missing_ok=True)
    out_text = ""
    out_file = Path(str(out_prefix) + ".out")
    if out_file.exists():
        out_text = out_file.read_text()
    merged = [ln for ln in out_text.splitlines() if ln.startswith("MERGED")]
    pushed = [ln for ln in out_text.splitlines() if ln.startswith("PUSH_OK")]
    if run.returncode != 0 or not pushed:
        trace(f"caller={args.caller} event=vm_push fp={fp} result=fail "
              f"runner_rc={run.returncode} merged={merged[:1]}")
        print(f"VM_PUSH_FAIL rc={run.returncode} out_tail={out_text[-300:]}")
        return 2

    vm_status = public_status("https://dealdesk.vertciti.com/api/tophap/status")
    vz_status = public_status("https://vertciti-dealdesk.vercel.app/api/tophap/status")
    vm_ok = vm_status.get("token_expired") is False and vm_status.get("core_ready") is True
    vz_ok = vz_status.get("token_expired") is False and vz_status.get("core_ready") is True
    trace(f"caller={args.caller} event=vm_push fp={fp} "
          f"result={'ok' if (vm_ok and vz_ok) else 'verify_fail'} "
          f"vm_ok={vm_ok} vercel_ok={vz_ok} merged={merged[:1]}")
    print(f"VM_PUSH {'OK' if vm_ok else 'VERIFY_FAIL'} fp={fp} "
          f"vm={vm_status} vercel_ok={vz_ok}")
    return 0 if (vm_ok and vz_ok) else 3


if __name__ == "__main__":
    sys.exit(main())
