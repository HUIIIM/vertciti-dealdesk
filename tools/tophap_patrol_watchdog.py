#!/usr/bin/env python3
"""TopHap patrol watchdog (protocol team, census fifth-face ticket 1, 2026-11-03).

Independent liveness check for the tophap-token-watch patrol chain.
Design rule: the watchdog NEVER refreshes or repairs anything. It only
observes production truth from outside the patrol pipeline, so a dead
patrol cannot mask itself. Two signals:

  1. production status on both domains (token_expired / core_ready)
  2. local .env token remaining seconds (patrol must refresh by 2700s;
     remaining <= 1800s means at least one refresh window was missed)

Verdict OK only if both domains are healthy AND remaining > 1800s.
Appends one line per run to .tophap-patrol-watchdog.log (timestamps and
booleans only, never token values). Exit 0 = OK, 3 = FLAG.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(BASE, ".env")
LOG_FILE = os.path.join(BASE, ".tophap-patrol-watchdog.log")
URLS = [
    "https://dealdesk.vertciti.com/api/tophap/status",
    "https://vertciti-dealdesk.vercel.app/api/tophap/status",
]
REMAINING_FLOOR_SEC = 1800


def fetch_status(url: str) -> dict | None:
    env = dict(os.environ)
    env["NO_PROXY"] = "localhost,127.0.0.1"
    env["no_proxy"] = "localhost,127.0.0.1"
    # 确认重取（2026-11-03 晚补）：单次传输失败先隔 3 秒重取一次，两次皆败才判
    # unreachable——首夜 7 轮中 2 轮单域 unreachable 且次轮自清，属瞬时网络噪声，
    # 与舰队 F2/F4 口径同向（探针未知先定界、不以单次失败定性）。
    for attempt in range(2):
        try:
            out = subprocess.run(
                ["curl", "-s", "--max-time", "25", url],
                capture_output=True, text=True, env=env, timeout=35,
            )
            return json.loads(out.stdout)
        except Exception:
            if attempt == 0:
                time.sleep(3)
    return None


def local_remaining() -> int | None:
    try:
        for line in open(ENV_FILE):
            if line.startswith("TOPHAP_TOKEN_EXPIRES_AT="):
                return int(line.split("=", 1)[1].strip()) - int(time.time())
    except Exception:
        return None
    return None


def main() -> int:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    states = []
    healthy = True
    for url in URLS:
        st = fetch_status(url)
        if st is None:
            states.append("unreachable")
            healthy = False
            continue
        ok = (st.get("token_expired") is False) and (st.get("core_ready") is True)
        states.append("ok" if ok else "unhealthy")
        healthy = healthy and ok
    remaining = local_remaining()
    missed_window = remaining is not None and remaining <= REMAINING_FLOOR_SEC
    flag = (not healthy) or missed_window or remaining is None
    verdict = "FLAG" if flag else "OK"
    line = (
        f"{now} verdict={verdict} domains={','.join(states)} "
        f"remaining_sec={remaining} floor={REMAINING_FLOOR_SEC}"
    )
    with open(LOG_FILE, "a") as fh:
        fh.write(line + "\n")
    print(line)
    return 3 if flag else 0


if __name__ == "__main__":
    sys.exit(main())
