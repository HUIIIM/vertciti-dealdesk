#!/usr/bin/env python3
"""TopHap OAuth code 文件通道：执行侧轮询读取端（2026-10-28 通道改造）。

背景：实时 handoff 文本通道会把 code 值送失真、批量通道送达时 code 已超
寿命（2026-10-28 连续 2 轮异常定版根因）。改道：Phase 1 的 redirect_uri
指向 webhook.site 捕获 bin，浏览器点 Allow 后 TopHap 直接把 code 写进捕获
端；本脚本经其 API 轮询读回，state 逐字核对后把 code 落约定文件（0600），
Phase 2 从文件读 code，全程不经任何文本转述。

用法：
  tophap_code_inbox.py --uuid <bin-uuid> --state <本轮 state> \
      --out <code 文件路径> [--timeout 240] [--interval 5]

输出（stdout 只报元数据，绝不打印 code 本体）：
  CODE_READY len=<n> age_s=<s>           成功，code 已落 --out
  CODE_TIMEOUT                           超时未见匹配请求，exit 2
  STATE_MISMATCH_SEEN ...                见到 code 但 state 不符（继续轮询）
网络错误按 NET_TIMEOUT 45s 单次上限重试至总超时。
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

NET_TIMEOUT = 45
API = "https://webhook.site/token/{uuid}/requests?sorting=newest&per_page=5"


def fetch_requests(uuid: str):
    req = urllib.request.Request(
        API.format(uuid=uuid), headers={"Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=NET_TIMEOUT) as resp:
        return json.load(resp).get("data", [])


def parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--uuid", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--interval", type=int, default=5)
    args = ap.parse_args()

    deadline = time.time() + args.timeout
    mismatch_reported = False
    while True:
        try:
            for item in fetch_requests(args.uuid):
                query = item.get("query") or {}
                code = query.get("code")
                state = query.get("state")
                if not code:
                    continue
                if state != args.state:
                    if not mismatch_reported:
                        print(
                            "STATE_MISMATCH_SEEN seen_state_len="
                            f"{len(state or '')} expected_len={len(args.state)}",
                            flush=True,
                        )
                        mismatch_reported = True
                    continue
                created = parse_ts(item.get("created_at"))
                age = int(time.time() - created) if created else -1
                fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w") as fh:
                    fh.write(code)
                print(f"CODE_READY len={len(code)} age_s={age}", flush=True)
                return 0
        except Exception as exc:  # 网络抖动不中断轮询，只记类型
            print(f"POLL_ERR {type(exc).__name__}", flush=True)
        if time.time() >= deadline:
            print("CODE_TIMEOUT", flush=True)
            return 2
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
