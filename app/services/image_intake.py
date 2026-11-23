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

from app.paths import REPO_ROOT

BASE_DIR = str(REPO_ROOT)
PENDING_DIR = os.path.join(BASE_DIR, "uploads", "pending")

ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp"}
MAX_BYTES = 15 * 1024 * 1024
# Stage 2 回写上限：extracted.json 序列化后不得超过 2MB（路由层先判原始体）。
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024
CONTENT_TYPES = {".png": "image/png", ".jpg": "image/jpeg",
                 ".jpeg": "image/jpeg", ".webp": "image/webp"}


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
            "message": "已收到截图，提取排队中"}


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


def infer_deal_type(fields: list, tenants: list | None = None) -> str:
    """截图提取结果的 deal 类型推断。

    带租户表或商业键（analysis.*/property.*）→ commercial；其余
    （asking_price/building_sf 等住宅键）→ residential。
    """
    if tenants:
        return "commercial"
    keys = {str((f or {}).get("key") or "") for f in fields or []}
    if any(k.startswith(("analysis.", "property.")) for k in keys):
        return "commercial"
    return "residential"


def attach_quality_gate(d: dict) -> dict:
    """截图视觉提取结果附数据质量门。

    此前 pending 队列的视觉提取结果（extracted.json）原样返回、无
    quality_gate，截图路成了门覆盖的盲区（商业浏览器 OCR 路已在
    2026-10-13 补齐）。现统一在取回时现跑门：fail → blocked＋标黄
    字段（yellow_fields），与 PDF/粘贴/OCR 路口径一致。门运行异常
    时不吞结果：附 quality_gate_error 说明，绝不假装已过门。
    """
    try:
        from app.domain import validators
        fields = d.get("fields") or []
        tenants = d.get("tenants") or []
        deal_type = str(d.get("deal_type") or infer_deal_type(fields, tenants))
        if deal_type not in ("commercial", "residential"):
            deal_type = infer_deal_type(fields, tenants)
        raw_text = str(d.get("raw_text") or d.get("text") or "")
        d["quality_gate"] = validators.run_quality_gate(
            deal_type, fields, tenants=tenants, raw_text=raw_text)
    except Exception as e:  # noqa: BLE001
        d["quality_gate_error"] = f"质量门运行失败：{str(e)[:200]}"
    return d


def get_extracted(task_id: str) -> dict:
    """读取某任务的提取结果；防目录穿越。取回时附 quality_gate。"""
    if not re.fullmatch(r"[0-9a-f]{32}", task_id or ""):
        raise ValueError("非法 task_id")
    ep = os.path.join(PENDING_DIR, task_id, "extracted.json")
    if not os.path.isfile(ep):
        raise FileNotFoundError("提取结果尚未生成")
    with open(ep, encoding="utf-8") as f:
        d = json.load(f)
    if not isinstance(d, dict) or not isinstance(d.get("fields"), list):
        raise ValueError("提取结果格式损坏")
    return attach_quality_gate(d)


def _task_dir(task_id: str) -> str:
    """task_id 格式校验 + 任务目录定位（Stage 2 消费腿共用）。

    格式复用现行 [0-9a-f]{32} 口径；再以 realpath 兜底确认目录不逃出
    PENDING_DIR（防目录穿越）。
    """
    if not re.fullmatch(r"[0-9a-f]{32}", task_id or ""):
        raise ValueError("非法 task_id")
    task_dir = os.path.join(PENDING_DIR, task_id)
    base = os.path.realpath(PENDING_DIR)
    if os.path.commonpath([base, os.path.realpath(task_dir)]) != base:
        raise ValueError("非法 task_id")
    return task_dir


def get_original(task_id: str) -> tuple[bytes, str]:
    """读取某任务的原图字节与 Content-Type（按 manifest 的 saved_name 定位）。

    任务不存在（无 manifest）或原图文件缺失 → FileNotFoundError；
    task_id 格式非法 → ValueError。
    """
    task_dir = _task_dir(task_id)
    m = _read_manifest(task_dir)
    if not m:
        raise FileNotFoundError("任务不存在")
    saved = str(m.get("saved_name") or "")
    if not saved or os.path.basename(saved) != saved:
        raise FileNotFoundError("原图记录缺失")
    img_path = os.path.join(task_dir, saved)
    # containment 复核：saved_name 来自 manifest 落盘内容，仍须实证不逃出任务目录
    if os.path.commonpath([os.path.realpath(task_dir),
                            os.path.realpath(img_path)]) != os.path.realpath(task_dir):
        raise FileNotFoundError("原图记录缺失")
    if not os.path.isfile(img_path):
        raise FileNotFoundError("原图文件不存在")
    content_type = CONTENT_TYPES.get(
        os.path.splitext(saved)[1].lower(), "application/octet-stream")
    with open(img_path, "rb") as f:
        return f.read(), content_type


def save_extracted(task_id: str, payload) -> dict:
    """回写视觉提取结果 extracted.json（原子写、幂等覆盖、不改 manifest）。

    契约（与 get_extracted 消费面＋现行 intake 夹具对平）：payload 须为
    JSON 对象；fields 必填且为 list；tenants 在位须为 list，raw_text /
    deal_type 在位须为 str；余键透传。quality_gate / quality_gate_error
    由取回时现跑（attach_quality_gate），生产者自带的同名键一律剥离、
    不落盘。status=done 由 list_tasks 按 extracted.json 在位派生，
    manifest 保持不动。
    """
    task_dir = _task_dir(task_id)
    if _read_manifest(task_dir) is None:
        raise FileNotFoundError("任务不存在")
    if not isinstance(payload, dict):
        raise ValueError("提取结果须为 JSON 对象")
    if not isinstance(payload.get("fields"), list):
        raise ValueError("提取结果缺少 fields 列表")
    if "tenants" in payload and not isinstance(payload["tenants"], list):
        raise ValueError("tenants 须为列表")
    for key in ("raw_text", "deal_type"):
        if key in payload and not isinstance(payload[key], str):
            raise ValueError(f"{key} 须为字符串")
    clean = {k: v for k, v in payload.items()
             if k not in ("quality_gate", "quality_gate_error")}
    text = json.dumps(clean, ensure_ascii=False)
    if len(text.encode("utf-8")) > MAX_EXTRACTED_BYTES:
        raise ValueError("提取结果超过 2MB 上限")
    ep = os.path.join(task_dir, "extracted.json")
    tmp = os.path.join(task_dir, f".extracted.json.tmp-{uuid.uuid4().hex[:8]}")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, ep)
    return {"task_id": task_id, "status": "done"}
