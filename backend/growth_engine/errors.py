"""Stable English error codes; the panel and the bots translate by code."""


class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, extra: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra or {}  # more machine-readable detail (e.g. retry_after)


class NotFound(AppError):
    def __init__(self, what: str) -> None:
        super().__init__(f"{what}_not_found", f"{what.replace('_', ' ').capitalize()} not found", 404)


class Forbidden(AppError):
    def __init__(self, code: str = "forbidden", message: str = "Not allowed") -> None:
        super().__init__(code, message, 403)
