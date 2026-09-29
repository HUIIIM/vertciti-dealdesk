"""截图 intake：接收房源页截图（PNG/JPG/WebP），存入 pending 队列.

视觉提取由 cron watcher（独立 agent，带 vision）完成，结果写回
<task_id>/extracted.json，字段格式与 research_pipeline / pdf_intake 的
renderIntake 结构对齐，前端可直接渲染＋一键填表。
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PENDING_DIR = os.path.join(BASE_DIR, "uploads", "pending")

ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp"}
MAX_BYTES = 15 * 1024 * 1024


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def save_screenshot(data: bytes, filename: str) -> dict:
    """校验并保存截图，返回任务信息。"""
    name = (filename or "screenshot.png").strip()
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_EXT:
        raise ValueError(f"只接受截图图片（png/jpg/webp），收到：{name[:60]}")
    if len(data) > MAX_BYTES:
        raise ValueError("截图超过 15MB 上限")
    if len(data) < 67:
        raise ValueError("文件过小或为空")
    # 简单魔数校验
    magic_ok = (
        data[:8] == b"\x89PNG\r\n\x1a\n"
        or data[:2] == b"\xff\xd8"
        or data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    )
    if not magic_ok:
        raise ValueError("文件不是有效的图片")

    task_id = uuid.uuid4().hex
    task_dir = os.path.join(PENDING_DIR, task_id)
    os.makedirs(task_dir, exist_ok=False)
    safe = re.sub(r"[^A-Za-z0-9._\-]", "_", name)[-80:]
    img_path = os.path.join(task_dir, safe)
    with open(img_path, "wb") as f:
        f.write(data)
    manifest = {
        "task_id": task_id,
        "original_name": name,
        "saved_name": safe,
        "received_at": _now(),
        "source": "screenshot",
        "status": "pending",
    }
    with open(os.path.join(task_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return {"task_id": task_id, "status": "pending", "filename": name,
            "received_at": manifest["received_at"],
            "message": "已收到截图，等待提取（约10分钟内）"}


def _read_manifest(task_dir: str) -> dict | None:
    mp = os.path.join(task_dir, "manifest.json")
    if not os.path.isfile(mp):
        return None
    try:
        with open(mp, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def list_tasks() -> list[dict]:
    """列出截图任务（pending/done/failed）。"""
    if not os.path.isdir(PENDING_DIR):
        return []
    out = []
    for task_id in sorted(os.listdir(PENDING_DIR)):
        if not re.fullmatch(r"[0-9a-f]{32}", task_id):
            continue
        task_dir = os.path.join(PENDING_DIR, task_id)
        m = _read_manifest(task_dir)
        if not m:
            continue
        extracted = os.path.join(task_dir, "extracted.json")
        status = m.get("status", "pending")
        if status == "pending" and os.path.isfile(extracted):
            status = "done"
        out.append({
            "task_id": task_id,
            "filename": m.get("original_name", ""),
            "received_at": m.get("received_at", ""),
            "status": status,
            "note": m.get("note", ""),
            "has_result": os.path.isfile(extracted),
        })
    return out


def get_extracted(task_id: str) -> dict:
    """读取某任务的提取结果；防目录穿越。"""
    if not re.fullmatch(r"[0-9a-f]{32}", task_id or ""):
        raise ValueError("非法 task_id")
    ep = os.path.join(PENDING_DIR, task_id, "extracted.json")
    if not os.path.isfile(ep):
        raise FileNotFoundError("提取结果尚未生成")
    with open(ep, encoding="utf-8") as f:
        d = json.load(f)
    if not isinstance(d, dict) or not isinstance(d.get("fields"), list):
        raise ValueError("提取结果格式损坏")
    return d
