#!/bin/bash
# DealDesk 启动脚本
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/uvicorn ]; then
  echo "未找到虚拟环境，正在创建…"
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
.venv/bin/python -c "from app import db; db.init_db()"
echo "DealDesk 运行中：http://127.0.0.1:8100"
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8100
