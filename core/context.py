# core/context.py
from contextvars import ContextVar

student_ctx: ContextVar[dict | None] = ContextVar("student_ctx", default=None)
user_roles_ctx: ContextVar[list] = ContextVar("user_roles_ctx", default=[])