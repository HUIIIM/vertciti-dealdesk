#!/usr/bin/env python3
"""TopHap token 过期监控（给 cron 每天跑一次）。

逻辑：
- 调 tophap.token_expiry_report() 拿剩余小时数
- < 24h（或已过期）→ 写警告到 stderr + 返回 exit 1（cron 会告警）
- 正常 → 静默（exit 0）

注意：绝不自动重授权——OAuth 需要浏览器里点 Approve，必须人工触发。
人工收到警告后跑：.venv/bin/python tools/tophap_oauth_setup.py --manual
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app import tophap


def main() -> int:
    report = tophap.token_expiry_report()
    status = report["status"]
    if status in ("expired", "expiring_soon", "unknown"):
        print(f"[TopHap token 监控] {status}：剩余 {report['hours_left']} 小时", file=sys.stderr)
        print(f"[TopHap token 监控] 建议动作：{report['action']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
