"""仓库内固定路径（分层搬家后，模块不再各自用 __file__ 推算相对位置）。"""
from __future__ import annotations

from pathlib import Path

APP_DIR = Path(__file__).resolve().parent          # app/
REPO_ROOT = APP_DIR.parent                         # 仓库根（.env、dealdesk.db、static/ 所在）
FONT_DIR = APP_DIR / "fonts"
STATIC_DIR = REPO_ROOT / "static"
