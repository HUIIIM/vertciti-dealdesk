"""pytest 插件：包裹纯计算模块公开函数，录下测试套件实际传入的参数（金标准输入集）。"""
import functools, hashlib, importlib, inspect, json, os
OUT = os.environ["FN_CAPTURE_OUT"]
MODS = {
 "finance": None, "scoring_residential": None, "scoring_commercial": None,
 "uw_commercial": None, "sensitivity": None, "verdict": None, "confidence": None,
 "condition_adjust": None, "commercial_plus": None, "report_narrative": None,
 "charts": None, "demand_validation": None, "validators": None,
 "workbench": {"pull_comps"},  # 排除：走网络
}
seen = set()
def wrap(modname, name, fn):
    @functools.wraps(fn)
    def w(*a, **kw):
        try:
            payload = json.dumps({"a": a, "kw": kw}, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            payload = None
        r = fn(*a, **kw)
        if payload is not None:
            key = hashlib.sha256(f"{modname}.{name}:{payload}".encode()).hexdigest()
            if key not in seen:
                seen.add(key)
                with open(OUT, "a") as f:
                    f.write(json.dumps({"mod": modname, "fn": name, "args": json.loads(payload)}, ensure_ascii=False) + "\n")
        return r
    return w
for modname, excl in MODS.items():
    m = importlib.import_module("app." + modname)
    for name, obj in list(vars(m).items()):
        if name.startswith("_") or not inspect.isfunction(obj) or obj.__module__ != m.__name__:
            continue
        if excl and name in excl:
            continue
        setattr(m, name, wrap(modname, name, obj))
