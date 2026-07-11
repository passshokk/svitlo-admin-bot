from contextvars import ContextVar

student_ctx: ContextVar[dict | None] = ContextVar("student_ctx", default=None)
user_roles_ctx: ContextVar[str] = ContextVar("user_roles_ctx", default="")