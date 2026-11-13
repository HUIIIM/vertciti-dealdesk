#!/usr/bin/env python3
"""TopHap patrol watchdog (protocol team). Observes only; never refreshes.

Restored 2026-11-07 from the log-evidenced contract in
dealdesk/.tophap-patrol-watchdog.log after the untracked original was lost
in a re-clone cleanup. Behavior:
- remaining_sec = local .env TOPHAP_TOKEN_EXPIRES_AT - now.
- domains: single production surface since the 2026-11-04 Vercel
  retirement (dealdesk.vertciti.com/api/tophap/status). ok = reachable
  with token_expired false and core_ready true; unhealthy = reachable
  but flags bad; unreachable = fetch failed twice (3s apart, per the
  2026-11-03 confirm-retry fix).
- verdict OK iff remaining >= floor (1800) and all domains ok, else FLAG.
- Appends one line to dealdesk/.tophap-patrol-watchdog.log and prints it.
Exit codes: 0 = OK, 3 = FLAG (wrapper contract).
No token values are read beyond the expiry field; nothing secret is logged.
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

for _k in ("NO_PROXY", "no_proxy"):
    if _k in os.environ:
        os.environ[_k] = "localhost,127.0.0.1"

ROOT = Path(os.environ.get("DEALDESK_ROOT") or Path(__file__).resolve().parent.parent)
LOG = ROOT / ".tophap-patrol-watchdog.log"
ENV_FILE = ROOT / ".env"
STATUS_URL = "https://dealdesk.vertciti.com/api/tophap/status"
FLOOR = 1800


def local_remaining():
    try:
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("TOPHAP_TOKEN_EXPIRES_AT="):
                return int(float(line.split("=", 1)[1].strip())) - int(time.time())
    except Exception:
        return None
    return None


def fetch_status():
    req = urllib.request.Request(STATUS_URL, headers={"User-Agent": "tophap-patrol-watchdog/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def domain_state():
    data = None
    for attempt in (1, 2):
        try:
            data = fetch_status()
            break
        except Exception:
            if attempt == 1:
                time.sleep(3)
    if data is None:
        return "unreachable"
    if data.get("token_expired") is False and data.get("core_ready") is True:
        return "ok"
    return "unhealthy"


def main():
    remaining = local_remaining()
    state = domain_state()
    remaining_val = remaining if remaining is not None else -99999
    verdict = "OK" if (remaining is not None and remaining >= FLOOR and state == "ok") else "FLAG"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{ts} verdict={verdict} domains={state} remaining_sec={remaining_val} floor={FLOOR}"
    print(line)
    with LOG.open("a") as fh:
        fh.write(line + "\n")
    return 0 if verdict == "OK" else 3


if __name__ == "__main__":
    sys.exit(main())
