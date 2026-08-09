from typing import Any


class ProjectDomainError(Exception):
    def __init__(
        self,
        detail: str,
        *,
        status: int,
        code: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status = status
        self.code = code
        self.context = context or {}


class ProjectNotFoundError(ProjectDomainError):
    def __init__(self, detail: str = "Проект не найден") -> None:
        super().__init__(detail, status=404, code="not_found")


class ProjectConflictError(ProjectDomainError):
    def __init__(
        self,
        detail: str,
        *,
        code: str = "invalid_status_transition",
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail, status=409, code=code, context=context)


class ProjectInvariantError(ProjectDomainError):
    def __init__(self, detail: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(detail, status=422, code="program_invariant", context=context)
