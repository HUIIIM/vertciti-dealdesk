# 安全策略
发现漏洞请写信 contact@vertciti.com，标题以“Security”开头。3 个工作日内确认收到。细则见 https://vertciti.com/security/ 。

## 供应链钉版与 SBOM (SEC-A5)
- GitHub Actions 全部以 commit SHA 引用 (禁浮动 tag)，由 tests/test_supply_chain_pins.py 守门。
- Python 生产依赖在 requirements.txt 逐行 == 精确钉版，完整传递闭包锁定于 requirements.lock.txt (可复现安装: pip install -r requirements.lock.txt)；开发/CI 依赖在 requirements-dev.txt 同口径钉版。
- SBOM: tools/generate_sbom.py 自 requirements.lock.txt 生成 CycloneDX 1.5 清单；仓库根 sbom.cdx.json 为存档实例，CI 的 SBOM 工作流每次运行另产 artifact 存档 (保留 90 天)。
