#!/usr/bin/env python3
"""Push the local TopHap chain head (.env TOPHAP_ block) to the production
VM (dealdesk-app-prod container) via OCI Run Command, then verify.

Restored 2026-11-07 (protocol team) after the untracked original was lost
in a re-clone cleanup; mechanics re-proven live the same day. This restore
embodies the 2026-11-05 verify-fix brief: the retired vercel.app verify
leg is gone, VM verify is a bounded readiness poll, and the trace/stdout
fingerprint is labeled fp_caliber=values (md5(access_token+expires_at)
[:8]; never cross-compare with the patrol's line-caliber env fp).

Exit codes: 0 = pushed and verified; 2 = push/Run Command failure;
3 = pushed but verify still failing after the bounded poll;
21 = another push holds the flock.
Only fingerprints and expiries are printed/traced; never token values.
"""
import argparse
import base64
import fcntl
import hashlib
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRACE = ROOT / ".tophap-reauth-trace.log"
LOCK = ROOT / ".tophap-vm-push.lock"
OCI_PY = str(Path.home() / ".oci" / "venv" / "bin" / "python")
STATUS_URL = "https://dealdesk.vertciti.com/api/tophap/status"

DRIVER = r'''
import oci, sys, time
cfg = oci.config.from_file()
client = oci.compute_instance_agent.ComputeInstanceAgentClient(cfg)
COMP = "ocid1.compartment.oc1..aaaaaaaam6cye5hw4ff6znkn62fkt4oehjlgzkslj753j4jytfqmvfnoeqna"
INST = "ocid1.instance.oc1.iad.anuwcljr7nklamicii3r4m4xsvvtpaldkge2hf5ifmhuxvs3ny7z7ird5x6q"
M = oci.compute_instance_agent.models
script = open(sys.argv[1]).read()
details = M.CreateInstanceAgentCommandDetails(
    compartment_id=COMP, execution_time_out_in_seconds=900,
    target=M.InstanceAgentCommandTarget(instance_id=INST),
    content=M.InstanceAgentCommandContent(
        source=M.InstanceAgentCommandSourceViaTextDetails(source_type="TEXT", text=script)))
cmd = client.create_instance_agent_command(details).data
cid = getattr(cmd, "id", None) or getattr(cmd, "instance_agent_command_id", None)
print("CREATED", cid, flush=True)
deadline = time.time() + 1500
while time.time() < deadline:
    try:
        ex = client.get_instance_agent_command_execution(cid, INST).data
    except Exception as e:
        print("poll-err", type(e).__name__, str(e)[:200], flush=True); time.sleep(15); continue
    st = ex.lifecycle_state
    print("STATE", st, flush=True)
    if st in ("SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELED"):
        c = ex.content
        for attr in ("text", "output"):
            v = getattr(c, attr, None)
            if v:
                print(f"--- {attr} ---")
                print(v if isinstance(v, str) else repr(v))
        sys.exit(0 if st == "SUCCEEDED" else 4)
    time.sleep(15)
print("POLL_TIMEOUT"); sys.exit(5)
'''


def nowz():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def trace(line):
    with TRACE.open("a") as fh:
        fh.write(f"{nowz()} {line}\n")


def read_block(env_path):
    block, order = {}, []
    for line in Path(env_path).read_text().splitlines():
        if line.startswith("TOPHAP_") and "=" in line:
            k, v = line.split("=", 1)
            if k not in block:
                order.append(k)
            block[k] = v
    return block, order


def build_payload(block, order, exp):
    text = "".join(f"{k}={block[k]}\n" for k in order)
    b64 = base64.b64encode(text.encode()).decode()
    return f'''set -eu
ENV_DIR="$HOME/dealdesk-prod/secrets"
ENV_FILE="$ENV_DIR/app.env"
TS=$(date +%Y%m%d%H%M%S)
cp -a "$ENV_FILE" "$ENV_FILE.bak-tophap-$TS"
printf '%s' '{b64}' | base64 -d > "$ENV_DIR/tophap.part"
chmod 600 "$ENV_DIR/tophap.part"
grep -q '^TOPHAP_TOKEN_EXPIRES_AT={exp}$' "$ENV_DIR/tophap.part" || {{ echo "PART_EXP_MISMATCH_ABORT"; exit 1; }}
grep -v '^TOPHAP_' "$ENV_FILE" > "$ENV_FILE.new" || true
cat "$ENV_DIR/tophap.part" >> "$ENV_FILE.new"
chmod 600 "$ENV_FILE.new"
mv "$ENV_FILE.new" "$ENV_FILE"
rm -f "$ENV_DIR/tophap.part"
docker rm -f dealdesk-app-prod
docker run -d --name dealdesk-app-prod --restart unless-stopped --env-file "$ENV_FILE" --network dd-prod-net dealdesk-prod:4901c4b >/dev/null
docker network connect miao-prod_default dealdesk-app-prod
for i in $(seq 1 40); do
  OUT=$(docker exec dealdesk-app-prod python3 -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8100/api/tophap/status',timeout=5).read().decode())" 2>/dev/null) && {{ echo "STATUS=$OUT"; break; }}
  sleep 3
done
docker exec dealdesk-app-prod python3 -c "
import os,hashlib
t=os.environ.get('TOPHAP_ACCESS_TOKEN',''); e=os.environ.get('TOPHAP_TOKEN_EXPIRES_AT','')
print('MERGED fp=%s exp=%s' % (hashlib.md5((t+e).encode()).hexdigest()[:8], e))
"
echo PUSH_DONE
'''


def run_rc(payload):
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as pf:
        pf.write(payload)
        payload_path = pf.name
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as df:
        df.write(DRIVER)
        driver_path = df.name
    try:
        proc = subprocess.run([OCI_PY, driver_path, payload_path],
                              capture_output=True, text=True, timeout=1560)
        return proc.returncode, proc.stdout + proc.stderr
    finally:
        Path(payload_path).unlink(missing_ok=True)
        Path(driver_path).unlink(missing_ok=True)


def public_status_ok():
    try:
        req = urllib.request.Request(STATUS_URL, headers={"User-Agent": "tophap-vm-push/2.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
        return data.get("token_expired") is False and data.get("core_ready") is True
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--caller", default="patrol")
    ap.add_argument("--env-file", default=str(ROOT / ".env"))
    args = ap.parse_args()

    lock_fh = LOCK.open("w")
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("VM_PUSH ALREADY_RUNNING")
        return 21

    block, order = read_block(args.env_file)
    exp = int(block["TOPHAP_TOKEN_EXPIRES_AT"])
    fp = hashlib.md5((block["TOPHAP_ACCESS_TOKEN"] + block["TOPHAP_TOKEN_EXPIRES_AT"]).encode()).hexdigest()[:8]

    rc, out = run_rc(build_payload(block, order, exp))
    merged_ok = f"MERGED fp={fp} exp={exp}" in out
    if rc != 0 or "PUSH_DONE" not in out:
        trace(f"caller={args.caller} event=vm_push fp={fp} fp_caliber=values result=fail vm_ok=False merged=[]")
        print(f"VM_PUSH FAIL fp={fp} exp={exp} rc={rc}")
        return 2
    if not merged_ok:
        trace(f"caller={args.caller} event=vm_push fp={fp} fp_caliber=values result=fail vm_ok=False merged=[]")
        print(f"VM_PUSH FAIL fp={fp} exp={exp} reason=merged_fp_mismatch")
        return 2

    # Bounded verify: public data plane, up to ~60s (6 tries x 10s),
    # spanning the container readiness window (2026-11-05 ruling).
    attempts = 0
    vm_ok = False
    for i in range(6):
        attempts += 1
        if public_status_ok():
            vm_ok = True
            break
        if i < 5:
            time.sleep(10)
    merged = [f"MERGED fp={fp} exp={exp}"]
    if vm_ok:
        trace(f"caller={args.caller} event=vm_push fp={fp} fp_caliber=values result=ok vm_ok=True verify_attempts={attempts} merged={merged}")
        print(f"VM_PUSH OK fp={fp} exp={exp}")
        return 0
    trace(f"caller={args.caller} event=vm_push fp={fp} fp_caliber=values result=verify_fail vm_ok=False verify_attempts={attempts} merged={merged}")
    print(f"VM_PUSH VERIFY_FAIL fp={fp} exp={exp}")
    return 3


if __name__ == "__main__":
    sys.exit(main())
