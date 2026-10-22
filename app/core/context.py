"""请求上下文：当前操作人与请求编号（中间件写入，持久化层读取写 created_by / audit_log）。"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class Actor:
    username: str
    role: str  # chairman | analyst | viewer
    display_name: str = ""


SYSTEM = Actor("system", "chairman", "system")
_actor: ContextVar[Actor] = ContextVar("dealdesk_actor", default=SYSTEM)
_request_id: ContextVar[str] = ContextVar("dealdesk_request_id", default="")


def current_actor() -> Actor:
    return _actor.get()


def set_actor(a: Actor):  # noqa: ANN201 — 返回 contextvars.Token
    return _actor.set(a)


def reset_actor(token) -> None:  # noqa: ANN001
    _actor.reset(token)


def current_request_id() -> str:
    return _request_id.get()


def set_request_id(rid: str):  # noqa: ANN201
    return _request_id.set(rid)
