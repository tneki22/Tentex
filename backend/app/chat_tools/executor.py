"""Детерминированный executor: один путь для любого Tool, включая будущие.

```
найти spec → проверить доступность → валидировать вход → проверить
проект/сессию → создать ChatToolRun → выполнить handler → валидировать
результат → сохранить итог → создать типизированный блок чата
```

Модельный tool calling позже станет лишь способом выбрать `tool_key` и
`input` — сама последовательность ниже не меняется (AI-CHATS.md §17.2).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.chat_tools.registry import ToolContext, get_tool_spec
from app.exam import chat as chat_service
from app.models import ChatMessageRole, ChatPayloadKind, ChatToolRun, ChatToolRunState, utc_now
from app.projects.errors import ProjectDomainError


def run_tool(
    session: Session,
    project_id: UUID,
    session_id: UUID,
    tool_key: str,
    raw_input: dict[str, object],
) -> ChatToolRun:
    spec = get_tool_spec(tool_key)
    if spec is None:
        raise ProjectDomainError(
            "Такого Tool не существует", status=404, code="chat_tool_not_found"
        )
    if not spec.available or spec.handler is None:
        raise ProjectDomainError(
            f"«{spec.title}» пока недоступен",
            status=422,
            code="chat_tool_unavailable",
            context={"reason": spec.unavailable_reason},
        )
    with session.begin():
        chat_service._require_exam_project(session, project_id)
        chat = chat_service._require_session(session, project_id, session_id)
        if chat.mode.value not in spec.modes:
            raise ProjectDomainError(
                f"«{spec.title}» недоступен в этом режиме чата",
                status=422,
                code="chat_tool_unavailable",
                context={"reason": "mode_mismatch"},
            )
        try:
            tool_input = spec.input_model.model_validate(raw_input)
        except ValidationError as error:
            raise ProjectDomainError(
                "Некорректные параметры Tool",
                status=422,
                code="chat_tool_input_invalid",
                context={"errors": error.errors(include_input=False)},
            ) from error

        run = ChatToolRun(
            project_id=project_id,
            session_id=session_id,
            tool_key=tool_key,
            state=ChatToolRunState.RUNNING,
            tool_input=tool_input.model_dump(mode="json"),
        )
        session.add(run)
        session.flush()

        # confirmation policy: "never" выполняется сразу; "always" в первой
        # итерации не реализован — все опубликованные с handler Tools имеют
        # confirmation="never" (AI-CHATS.md §17.4), проверка здесь — не заглушка,
        # а явная граница на случай будущей политики "always".
        if spec.confirmation == "always":
            run.state = ChatToolRunState.FAILED
            run.error_code = "chat_tool_confirmation_required"
            run.completed_at = utc_now()
            session.flush()
            raise ProjectDomainError(
                f"«{spec.title}» требует подтверждения — это пока не реализовано",
                status=422,
                code="chat_tool_confirmation_required",
            )

        ctx = ToolContext(session=session, project_id=project_id, chat=chat)
        try:
            output = spec.handler(ctx, tool_input)
        except ProjectDomainError as error:
            run.state = ChatToolRunState.FAILED
            run.error_code = error.code
            run.completed_at = utc_now()
            session.flush()
            raise
        result = spec.output_model.model_validate(output).model_dump(mode="json")

        run.state = ChatToolRunState.SUCCEEDED
        run.result = result
        run.completed_at = utc_now()
        message = chat_service._append_message_row(
            session,
            chat,
            role=ChatMessageRole.EXAMINER,
            payload_kind=ChatPayloadKind.TOOL_RESULT,
            payload={
                "tool_key": tool_key,
                "output_kind": spec.output_kind,
                "state": "succeeded",
                "input": run.tool_input,
                "result": result,
            },
            skill=tool_key,
        )
        run.message_id = message.id
        session.flush()
        session.refresh(run)
    return run
