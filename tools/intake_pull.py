#!/usr/bin/env python3
"""截图 intake 本机拉取工具（Stage 2 消费腿的确定性部分）。

三子命令：
- list：列 pending 队列任务（task_id / 状态 / 文件名 / 接收时间）
- fetch <task_id>：取原图字节落本机工作目录，打印路径 + MD5
- push <task_id> <extracted.json>：把本机视觉提取结果回写任务目录

连接配置自仓根 .env 读：DEALDESK_BASE_URL（服务基址）、
DEALDESK_API_TOKEN（访问令牌，只进 Authorization 头，绝不打印/入日志）；
环境变量同名键优先于 .env。视觉提取步不在本工具内（由 extractor
cron 的 agent 视觉面完成），本工具只做确定性的列队/拉取/回写。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_EXT_BY_CONTENT_TYPE = {"image/png": ".png", "image/jpeg": ".jpg",
                        "image/webp": ".webp"}


def _load_env() -> dict:
    env: dict = {}
    env_file = REPO_ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    for key in ("DEALDESK_BASE_URL", "DEALDESK_API_TOKEN"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


class _Client:
    def __init__(self, base_url: str, token: str):
        self.base = base_url.rstrip("/")
        self.token = token

    def request(self, method: str, path: str,
                body: bytes | None = None) -> tuple[int, dict, bytes]:
        req = urllib.request.Request(self.base + path, data=body, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        if body is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:200]
            raise SystemExit(f"HTTP {e.code} {method} {path}：{detail}")
        except urllib.error.URLError as e:
            raise SystemExit(f"连接失败 {method} {path}：{e.reason}")


def _client_from_env() -> _Client:
    env = _load_env()
    base = env.get("DEALDESK_BASE_URL", "")
    token = env.get("DEALDESK_API_TOKEN", "")
    if not base or not token:
        raise SystemExit(
            "缺少 DEALDESK_BASE_URL / DEALDESK_API_TOKEN（仓根 .env 或环境变量）")
    return _Client(base, token)


def cmd_list(client: _Client) -> int:
    _, _, raw = client.request("GET", "/api/wb/intake/pending")
    d = json.loads(raw.decode("utf-8"))
    for t in d.get("tasks", []):
        print(f"{t.get('task_id', '')}  {t.get('status', '')}  "
              f"{t.get('filename', '')}  {t.get('received_at', '')}")
    return 0


def cmd_fetch(client: _Client, task_id: str, out_dir: Path) -> int:
    _, headers, data = client.request("GET", f"/api/wb/intake/original/{task_id}")
    ctype = headers.get("Content-Type", "").split(";")[0].strip()
    ext = _EXT_BY_CONTENT_TYPE.get(ctype, ".bin")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{task_id}{ext}"
    path.write_bytes(data)
    print(f"{path}  md5={hashlib.md5(data).hexdigest()}  bytes={len(data)}")
    return 0


def cmd_push(client: _Client, task_id: str, file: Path) -> int:
    body = file.read_bytes()
    _, _, raw = client.request(
        "POST", f"/api/wb/intake/extracted/{task_id}", body=body)
    print(raw.decode("utf-8"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="截图 intake 本机拉取工具")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="列 pending 队列任务")
    pf = sub.add_parser("fetch", help="取原图落本机工作目录")
    pf.add_argument("task_id")
    pf.add_argument("--out-dir", default="intake_work")
    pp = sub.add_parser("push", help="回写 extracted.json")
    pp.add_argument("task_id")
    pp.add_argument("file")
    args = ap.parse_args()
    client = _client_from_env()
    if args.cmd == "list":
        return cmd_list(client)
    if args.cmd == "fetch":
        return cmd_fetch(client, args.task_id, Path(args.out_dir))
    return cmd_push(client, args.task_id, Path(args.file))


if __name__ == "__main__":
    sys.exit(main())
