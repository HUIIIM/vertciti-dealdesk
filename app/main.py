"""DealDesk API 装配入口：创建应用、挂载各领域路由与静态前端（v2 蓝图 §7：main.py ≤ 100 行）。

端点实现见 app/api/<领域>.py；计算在 app/domain，编排与数据源在 app/services。
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import ROUTERS
from app.api import v2 as api_v2
from app.api.common import STATIC_DIR
from app.api.common import _parse_rr_date as _parse_rr_date  # noqa: F401  旧测试/脚本的导入路径
from app.api.common import score_input as score_input  # noqa: F401
from app.core.observability import RequestContextMiddleware, configure_logging
from app.services import db

configure_logging()
app = FastAPI(title="DealDesk", description="vertciti 房地产交易核保台", version="2.0.0")
app.add_middleware(RequestContextMiddleware)  # 请求编号 · 身份 · 结构化访问日志 · 错误上报
api_v2.install_error_handlers(app)
for _router in [*ROUTERS, *api_v2.routers()]:
    app.include_router(_router)


@app.on_event("startup")
def _startup():
    db.init_db()


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
