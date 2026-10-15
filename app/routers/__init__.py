"""DealDesk 域路由包（台账第 14 项，2026-10-15 起）。

冻结线：app/main.py 不再新增端点——新端点一律写进本包的域模块
（routers/<域>.py），由 main.py include_router 装配。既有 main.py
端点按域分批迁入（迁一个域、验一个域），不许一次性大搬家。
"""
