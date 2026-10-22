"""v2 接口的中英切换：按请求语言输出用户可见文案（与前端、v1 static/i18n.js 同一约定）。

- 语言来自前端显式发送的请求头 `X-DD-Lang: en`，由 RequestContextMiddleware 写入上下文；缺省中文。
  不认浏览器自动带的 Accept-Language：英文系统上的中文界面不该收到英文数据。
- `T(中文模板, *参数)`：英文时查词典；模板占位与 str.format 一致（`{0}`、`{0:.2f}`）。参数原样代入。
- `label(中文标签)`：模块级常量标签（阶段名、假设名、指标名…导入时就求值）在**生成处**按语言输出。
- `localize()`：输出兜底，只对少数从不装用户数据的常量字段做精确匹配。用户输入（交易名、地址、来源名、
  任务名、备注、版本说明）任何时候都原样返回，存库内容也与请求语言无关。
- 中文请求完全不经过这里的任何替换：零回归。
"""
from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar, Token
from typing import Any

from app.core.i18n_en import EN

_LANG: ContextVar[str] = ContextVar("dealdesk_lang", default="zh")

# 输出时按精确匹配翻译的字段（只放系统生成的标签 / 说明；用户输入的字段一律不放）
# 输出时兜底翻译的字段：只放**从不装用户数据**的常量标签字段。title / label / note / reason 等可能是用户输入
# （任务名、版本说明、备注），绝不在这里按字面翻译——系统生成的那部分在生成处已用 T() / label() 按语言输出。
LOCALIZED_KEYS = frozenset({
    "stage_label", "status_label", "role_label", "method_label", "confidence_label", "review_label",
    "assumption_source_label", "metric_label", "source_hint",
})


def lang_from_header(value: str | None) -> str:
    return "en" if (value or "").strip().lower().startswith("en") else "zh"


def set_lang(lang: str) -> Token[str]:
    return _LANG.set("en" if lang == "en" else "zh")


def reset_lang(token: Token[str]) -> None:
    _LANG.reset(token)


def current_lang() -> str:
    return _LANG.get()


def T(zh: str, *args: Any) -> str:  # noqa: N802 — 与前端 / v1 的 T() 同名，读代码时一眼认出是可翻译文案
    """可翻译文案。参数原样代入（参数可能是用户数据，不翻译）；固定标签请调用方先用 label() 转好。"""
    tpl = EN.get(zh, zh) if _LANG.get() == "en" else zh
    return tpl.format(*args) if args else tpl


def label(zh: str) -> str:
    """固定标签（阶段名、假设名等常量）按当前语言输出。"""
    return EN.get(zh, zh) if _LANG.get() == "en" else zh


def localize(obj: Any) -> Any:
    """英文请求时，对白名单字段做精确匹配翻译（递归）；中文请求原样返回同一对象。"""
    if _LANG.get() != "en":
        return obj
    return _walk(obj, key=None)


def _walk(obj: Any, key: str | None) -> Any:
    if isinstance(obj, Mapping):
        return {k: _walk(v, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk(v, key) for v in obj]
    if isinstance(obj, str) and key in LOCALIZED_KEYS:
        return EN.get(obj, obj)
    return obj
