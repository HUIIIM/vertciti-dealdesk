"""pytest 插件：录下测试套件经 TestClient 发出的全部 JSON 请求体（金标准 API 输入集）。"""
import json, os
from starlette.testclient import TestClient
OUT = os.environ["CAPTURE_OUT"]
_orig = TestClient.request
def request(self, method, url, *a, **kw):
    if "json" in kw and kw["json"] is not None:
        try:
            with open(OUT, "a") as f:
                f.write(json.dumps({"method": method, "url": str(url), "json": kw["json"]}, ensure_ascii=False, default=str) + "\n")
        except Exception:
            pass
    return _orig(self, method, url, *a, **kw)
TestClient.request = request
