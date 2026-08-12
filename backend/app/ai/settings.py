from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.ai.credentials import decrypt_secret, encrypt_secret
from app.ai.roles import ROLE_SPECS, AiRoleSpec, get_role_spec, validate_role_parameters
from app.ai.schemas import (
    AiConnectionRead,
    AiConnectionWrite,
    AiFavoritesWrite,
    AiGlobalSettingsWrite,
    AiModelRead,
    AiRoleRead,
    AiRoleWrite,
    AiSettingsRead,
    AiTodayUsage,
)
from app.models import (
    AiConnection,
    AiModelCatalogEntry,
    AiRoleSetting,
    AiRun,
    AiSettings,
    utc_now,
)
from app.projects.errors import ProjectDomainError

Modality = Literal["text", "speech"]


class AiGatewayError(ProjectDomainError):
    def __init__(
        self,
        detail: str,
        *,
        code: str,
        status: int = 422,
        context: dict[str, object] | None = None,
    ) -> None:
        super().__init__(detail, status=status, code=code, context=context)


@dataclass(frozen=True)
class ResolvedModel:
    role: AiRoleSpec
    connection: AiConnection
    model_id: str
    source: Literal["request", "role_override", "text_default", "speech_default"]
    parameters: dict[str, object]


def _ensure_rows(session: Session) -> tuple[AiSettings, list[AiConnection]]:
    row = session.get(AiSettings, 1)
    if row is None:
        row = AiSettings(id=1)
        session.add(row)
    connections = []
    defaults = {
        "text": ("Текстовые модели", "https://openrouter.ai/api/v1"),
        "speech": ("Распознавание речи", ""),
    }
    for modality, (label, base_url) in defaults.items():
        connection = session.get(AiConnection, modality)
        if connection is None:
            connection = AiConnection(modality=modality, label=label, base_url=base_url)
            session.add(connection)
        connections.append(connection)
    session.flush()
    return row, connections


def validate_base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ProjectDomainError(
            "URL подключения должен начинаться с http:// или https://",
            status=422,
            code="ai_base_url_invalid",
        )
    if parsed.username or parsed.password:
        raise ProjectDomainError(
            "Логин и пароль нельзя передавать внутри URL",
            status=422,
            code="ai_base_url_credentials_forbidden",
        )
    return value


def credential_status(session: Session, modality: Modality) -> bool:
    connection = session.get(AiConnection, modality)
    return bool(connection and connection.api_key_ciphertext)


def credential(session: Session, modality: Modality) -> str:
    connection = session.get(AiConnection, modality)
    if connection is None or not connection.api_key_ciphertext:
        raise AiGatewayError(
            "Ключ внешней модели не настроен",
            code="ai_credentials_missing",
        )
    return decrypt_secret(connection.api_key_ciphertext)


def update_global_settings(session: Session, command: AiGlobalSettingsWrite) -> AiSettingsRead:
    with session.begin():
        row, _ = _ensure_rows(session)
        if (command.usd_rub_rate is None) != (command.usd_rub_rate_date is None):
            raise ProjectDomainError(
                "Курс USD/RUB и дата снимка задаются вместе",
                status=422,
                code="ai_fx_snapshot_incomplete",
            )
        for field, value in command.model_dump().items():
            setattr(row, field, value)
        row.updated_at = utc_now()
    return read_settings(session)


def update_connection(
    session: Session, modality: Modality, command: AiConnectionWrite
) -> AiConnectionRead:
    with session.begin():
        _, _ = _ensure_rows(session)
        row = session.get(AiConnection, modality)
        assert row is not None
        if command.label is not None:
            row.label = command.label
        if command.base_url is not None:
            row.base_url = validate_base_url(command.base_url)
        if command.api_key:
            row.api_key_ciphertext = encrypt_secret(command.api_key)
        if "default_model_id" in command.model_fields_set:
            row.default_model_id = command.default_model_id or None
        row.updated_at = utc_now()
    return connection_read(row)


def delete_credential(session: Session, modality: Modality) -> None:
    with session.begin():
        _, _ = _ensure_rows(session)
        row = session.get(AiConnection, modality)
        assert row is not None
        row.api_key_ciphertext = None
        row.last_test_status = None
        row.updated_at = utc_now()


def update_role(session: Session, role: str, command: AiRoleWrite) -> AiSettingsRead:
    validate_role_parameters(role, command.parameters)
    get_role_spec(role)
    with session.begin():
        row = session.get(AiRoleSetting, role)
        if row is None:
            row = AiRoleSetting(role=role)
            session.add(row)
        row.enabled = command.enabled
        row.model_override = command.model_override or None
        row.parameters = command.parameters
        row.updated_at = utc_now()
    return read_settings(session)


def update_favorites(session: Session, command: AiFavoritesWrite) -> AiSettingsRead:
    ids = list(dict.fromkeys(command.model_ids))
    with session.begin():
        existing = set(
            session.scalars(
                select(AiModelCatalogEntry.model_id).where(
                    AiModelCatalogEntry.modality == "text",
                    AiModelCatalogEntry.model_id.in_(ids),
                )
            )
        )
        missing = sorted(set(ids) - existing)
        if missing:
            raise ProjectDomainError(
                "В избранное передана модель вне локального каталога",
                status=422,
                code="ai_model_not_in_catalog",
                context={"model_ids": missing},
            )
        session.execute(update(AiModelCatalogEntry).values(is_favorite=False))
        if ids:
            session.execute(
                update(AiModelCatalogEntry)
                .where(
                    AiModelCatalogEntry.modality == "text",
                    AiModelCatalogEntry.model_id.in_(ids),
                )
                .values(is_favorite=True)
            )
    return read_settings(session)


def resolve_model(
    session: Session, role: str, request_override: str | None = None
) -> ResolvedModel:
    spec = get_role_spec(role)
    global_row, _ = _ensure_rows(session)
    if not global_row.external_models_enabled:
        raise AiGatewayError("Внешние модели выключены", code="ai_disabled")
    role_row = session.get(AiRoleSetting, role)
    if role_row is not None and not role_row.enabled:
        raise AiGatewayError("Эта функция ИИ выключена", code="ai_role_disabled")
    if request_override and not spec.allow_request_model_override:
        raise AiGatewayError(
            "Для этой функции нельзя выбрать модель в самом вызове",
            code="ai_model_override_forbidden",
        )
    connection = session.get(AiConnection, spec.modality)
    assert connection is not None
    if request_override:
        model_id, source = request_override, "request"
    elif role_row is not None and role_row.model_override:
        model_id, source = role_row.model_override, "role_override"
    else:
        model_id = connection.default_model_id
        source = f"{spec.modality}_default"
    if not model_id:
        raise AiGatewayError(
            "Модель для функции не настроена",
            code="ai_model_not_configured",
            context={"role": role},
        )
    parameters = validate_role_parameters(role, role_row.parameters if role_row else {})
    return ResolvedModel(spec, connection, model_id, source, parameters)  # type: ignore[arg-type]


def connection_read(row: AiConnection) -> AiConnectionRead:
    return AiConnectionRead(
        modality=row.modality,
        label=row.label,
        base_url=row.base_url,
        has_api_key=bool(row.api_key_ciphertext),
        default_model_id=row.default_model_id,
        last_test_status=row.last_test_status,
        last_tested_at=row.last_tested_at,
        last_catalog_refresh_at=row.last_catalog_refresh_at,
        updated_at=row.updated_at,
    )


def _today_usage(session: Session) -> AiTodayUsage:
    start = datetime.combine(date.today(), time.min)
    rows = list(session.scalars(select(AiRun).where(AiRun.created_at >= start)))
    succeeded = [row for row in rows if row.status == "succeeded"]
    return AiTodayUsage(
        input_tokens=sum(row.input_tokens or 0 for row in succeeded),
        output_tokens=sum(row.output_tokens or 0 for row in succeeded),
        actual_cost_usd=sum(
            (row.actual_cost_usd or Decimal("0") for row in succeeded), Decimal("0")
        ),
        actual_cost_rub=sum(
            (row.actual_cost_rub or Decimal("0") for row in succeeded), Decimal("0")
        ),
        cache_hits=sum(row.status == "cached" for row in rows),
    )


def read_settings(session: Session) -> AiSettingsRead:
    row, connections = _ensure_rows(session)
    models = list(
        session.scalars(
            select(AiModelCatalogEntry).order_by(
                AiModelCatalogEntry.modality, AiModelCatalogEntry.display_name
            )
        )
    )
    roles = []
    for spec in ROLE_SPECS.values():
        role_row = session.get(AiRoleSetting, spec.key)
        model_override = role_row.model_override if role_row else None
        connection = next(item for item in connections if item.modality == spec.modality)
        resolved = model_override or connection.default_model_id
        source = (
            "role_override"
            if model_override
            else (f"{spec.modality}_default" if resolved else None)
        )
        roles.append(
            AiRoleRead(
                role=spec.key,
                title=spec.title,
                description=spec.description,
                modality=spec.modality,
                enabled=role_row.enabled if role_row else True,
                model_override=model_override,
                resolved_model=resolved,
                model_source=source,
                required_capabilities=sorted(spec.required_capabilities),
                parameters=validate_role_parameters(
                    spec.key, role_row.parameters if role_row else {}
                ),
            )
        )
    return AiSettingsRead(
        external_models_enabled=row.external_models_enabled,
        daily_limit_usd=row.daily_limit_usd,
        operation_limit_usd=row.operation_limit_usd,
        confirm_input_tokens=row.confirm_input_tokens,
        usd_rub_rate=row.usd_rub_rate,
        usd_rub_rate_date=row.usd_rub_rate_date,
        connections=[connection_read(item) for item in connections],
        roles=roles,
        models=[AiModelRead.model_validate(item) for item in models],
        today_usage=_today_usage(session),
    )
