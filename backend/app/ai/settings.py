from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.ai.credentials import decrypt_secret, encrypt_secret
from app.ai.roles import (
    ROLE_SPECS,
    AiModality,
    AiRoleSpec,
    get_role_spec,
    validate_role_parameters,
)
from app.ai.schemas import (
    AiDefaultWrite,
    AiGlobalSettingsWrite,
    AiManualModelWrite,
    AiModelFavoritesWrite,
    AiModelRead,
    AiModelSelection,
    AiProviderFavoritesWrite,
    AiProviderRead,
    AiProviderWrite,
    AiRoleRead,
    AiRoleWrite,
    AiSettingsRead,
    AiTodayUsage,
)
from app.models import (
    AiModelCatalogEntry,
    AiProviderConnection,
    AiRoleSetting,
    AiRun,
    AiSettings,
    utc_now,
)
from app.projects.errors import ProjectDomainError

# Определение одно на весь шлюз и лежит в реестре ролей.
Modality = AiModality


def model_capabilities(row: AiModelCatalogEntry) -> set[str]:
    """Возможности модели, выведенные из каталога.

    Пустой `supported_parameters` — «каталог параметров не заполнен» (так у
    моделей, добавленных вручную), а не «модель не умеет»: гейт срабатывает
    только на положительном свидетельстве. Общая точка для `ModelGateway` и
    для валидации `ChatSession.model_override` — обе стороны должны видеть
    один и тот же набор возможностей одной модели.
    """
    capabilities = {"streaming"}
    if not row.supported_parameters or "response_format" in row.supported_parameters:
        capabilities.add("structured_output")
    if "audio" in row.input_modalities:
        capabilities.add("audio_transcription")
    if "image" in row.input_modalities:
        capabilities.add("image_input")
    return capabilities


def validate_model_selection(
    session: Session, selection: AiModelSelection, *, required: frozenset[str]
) -> AiModelCatalogEntry:
    """Проверяет provider_id+model_id по каталогу и требуемые возможности разом.

    Нужна явному override вне обычного `resolve_model` — сейчас настройкам
    чата (AI-CHATS.md §21.4): одна выбранная модель должна одновременно
    уметь потоковый ответ и structured output, чтобы обслуживать и обычную
    реплику, и судью той же сессии.
    """
    model = _model_for_selection(session, selection, modality="text")
    missing = required - model_capabilities(model)
    if missing:
        raise ProjectDomainError(
            f"Модель «{selection.model_id}» не поддерживает: {', '.join(sorted(missing))}",
            status=422,
            code="ai_capability_unsupported",
            context={"model_id": selection.model_id, "missing": sorted(missing)},
        )
    return model


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
    provider: AiProviderConnection
    model: AiModelCatalogEntry
    source: Literal[
        "request", "role_override", "text_default", "speech_default", "vision_default"
    ]
    parameters: dict[str, object]

    @property
    def model_id(self) -> str:
        return self.model.model_id


def _ensure_row(session: Session) -> AiSettings:
    row = session.get(AiSettings, 1)
    if row is None:
        row = AiSettings(id=1)
        session.add(row)
        session.flush()
    return row


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


def credential_status(session: Session, provider_id: UUID) -> bool:
    provider = session.get(AiProviderConnection, provider_id)
    return bool(provider and provider.api_key_ciphertext)


def credential(session: Session, provider_id: UUID) -> str:
    provider = _provider(session, provider_id)
    if not provider.api_key_ciphertext:
        raise AiGatewayError(
            "Ключ провайдера не настроен",
            code="ai_credentials_missing",
            context={"provider_id": str(provider_id)},
        )
    return decrypt_secret(provider.api_key_ciphertext)


def update_global_settings(session: Session, command: AiGlobalSettingsWrite) -> AiSettingsRead:
    with session.begin():
        row = _ensure_row(session)
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


def create_provider(session: Session, command: AiProviderWrite) -> AiSettingsRead:
    with session.begin():
        _ensure_unique_provider_label(session, command.label)
        provider = AiProviderConnection(
            label=command.label,
            catalog_profile=command.catalog_profile,
            base_url=validate_base_url(command.base_url),
            api_key_ciphertext=encrypt_secret(command.api_key) if command.api_key else None,
        )
        session.add(provider)
    return read_settings(session)


def update_provider(
    session: Session, provider_id: UUID, command: AiProviderWrite
) -> AiSettingsRead:
    with session.begin():
        provider = _provider(session, provider_id)
        _ensure_unique_provider_label(session, command.label, provider_id)
        provider.label = command.label
        provider.catalog_profile = command.catalog_profile
        provider.base_url = validate_base_url(command.base_url)
        if command.api_key:
            provider.api_key_ciphertext = encrypt_secret(command.api_key)
        provider.updated_at = utc_now()
    return read_settings(session)


def delete_provider(session: Session, provider_id: UUID) -> AiSettingsRead:
    with session.begin():
        provider = _provider(session, provider_id)
        global_row = _ensure_row(session)
        defaults = []
        if global_row.default_text_provider_id == provider_id:
            defaults.append("text")
        if global_row.default_speech_provider_id == provider_id:
            defaults.append("speech")
        roles = list(
            session.scalars(
                select(AiRoleSetting.role).where(AiRoleSetting.provider_override_id == provider_id)
            )
        )
        if defaults or roles:
            raise ProjectDomainError(
                "Сначала уберите провайдера из настроек по умолчанию и функций",
                status=409,
                code="ai_provider_in_use",
                context={"defaults": defaults, "roles": roles},
            )
        session.delete(provider)
    return read_settings(session)


def delete_credential(session: Session, provider_id: UUID) -> None:
    with session.begin():
        provider = _provider(session, provider_id)
        provider.api_key_ciphertext = None
        provider.last_test_status = None
        provider.updated_at = utc_now()


def set_default(
    session: Session, modality: Modality, command: AiDefaultWrite
) -> AiSettingsRead:
    with session.begin():
        row = _ensure_row(session)
        selection = command.selection
        if selection is not None:
            _model_for_selection(session, selection, modality=modality)
        setattr(
            row,
            f"default_{modality}_provider_id",
            selection.provider_id if selection else None,
        )
        setattr(row, f"default_{modality}_model_id", selection.model_id if selection else None)
        row.updated_at = utc_now()
    return read_settings(session)


def update_role(session: Session, role: str, command: AiRoleWrite) -> AiSettingsRead:
    spec = get_role_spec(role)
    validate_role_parameters(role, command.parameters)
    if (command.provider_override_id is None) != (command.model_override is None):
        raise ProjectDomainError(
            "Провайдер и модель функции выбираются вместе",
            status=422,
            code="ai_role_selection_incomplete",
        )
    with session.begin():
        if command.provider_override_id is not None and command.model_override is not None:
            _model_for_selection(
                session,
                AiModelSelection(
                    provider_id=command.provider_override_id,
                    model_id=command.model_override,
                ),
                modality=spec.modality,
            )
        row = session.get(AiRoleSetting, role)
        if row is None:
            row = AiRoleSetting(role=role)
            session.add(row)
        row.enabled = command.enabled
        row.provider_override_id = command.provider_override_id
        row.model_override = command.model_override
        row.parameters = command.parameters
        row.updated_at = utc_now()
    return read_settings(session)


def update_provider_favorites(
    session: Session, command: AiProviderFavoritesWrite
) -> AiSettingsRead:
    ids = list(dict.fromkeys(command.provider_ids))
    with session.begin():
        existing = set(
            session.scalars(
                select(AiProviderConnection.id).where(AiProviderConnection.id.in_(ids))
            )
        )
        missing = [str(item) for item in ids if item not in existing]
        if missing:
            raise ProjectDomainError(
                "В избранное передан неизвестный провайдер",
                status=422,
                code="ai_provider_not_found",
                context={"provider_ids": missing},
            )
        session.execute(update(AiProviderConnection).values(is_favorite=False))
        if ids:
            session.execute(
                update(AiProviderConnection)
                .where(AiProviderConnection.id.in_(ids))
                .values(is_favorite=True)
            )
    return read_settings(session)


def update_model_favorites(
    session: Session, command: AiModelFavoritesWrite
) -> AiSettingsRead:
    keys = list(dict.fromkeys((item.provider_id, item.model_id) for item in command.models))
    with session.begin():
        for provider_id, model_id in keys:
            _model_for_selection(
                session, AiModelSelection(provider_id=provider_id, model_id=model_id)
            )
        session.execute(update(AiModelCatalogEntry).values(favorite_order=None))
        for order, (provider_id, model_id) in enumerate(keys):
            session.execute(
                update(AiModelCatalogEntry)
                .where(
                    AiModelCatalogEntry.provider_id == provider_id,
                    AiModelCatalogEntry.model_id == model_id,
                )
                .values(favorite_order=order)
            )
    return read_settings(session)


def upsert_manual_model(
    session: Session, provider_id: UUID, command: AiManualModelWrite
) -> AiSettingsRead:
    with session.begin():
        _provider(session, provider_id)
        row = session.get(AiModelCatalogEntry, (provider_id, command.model_id))
        now = utc_now()
        is_new = row is None
        if row is None:
            row = AiModelCatalogEntry(
                provider_id=provider_id,
                model_id=command.model_id,
                display_name=command.display_name,
                pricing_snapshot_at=now,
                catalog_snapshot_at=now,
                is_manually_added=True,
            )
            session.add(row)
        values = command.model_dump(exclude={"model_id"})
        row.manual_overrides = command.model_dump(mode="json", exclude={"model_id"})
        for field, value in values.items():
            setattr(row, field, value)
        if is_new:
            row.is_manually_added = True
        row.is_available = True
        row.pricing_snapshot_at = now
        row.catalog_snapshot_at = now
    return read_settings(session)


def delete_model(session: Session, provider_id: UUID, model_id: str) -> AiSettingsRead:
    with session.begin():
        row = session.get(AiModelCatalogEntry, (provider_id, model_id))
        if row is None:
            raise ProjectDomainError(
                "Модель не найдена в локальном каталоге провайдера",
                status=404,
                code="ai_model_not_in_catalog",
                context={"provider_id": str(provider_id), "model_id": model_id},
            )
        global_row = _ensure_row(session)
        defaults = [
            modality
            for modality in ("text", "speech")
            if getattr(global_row, f"default_{modality}_provider_id") == provider_id
            and getattr(global_row, f"default_{modality}_model_id") == model_id
        ]
        roles = list(
            session.scalars(
                select(AiRoleSetting.role).where(
                    AiRoleSetting.provider_override_id == provider_id,
                    AiRoleSetting.model_override == model_id,
                )
            )
        )
        if defaults or roles:
            raise ProjectDomainError(
                "Сначала уберите модель из настроек по умолчанию и функций",
                status=409,
                code="ai_model_in_use",
                context={"defaults": defaults, "roles": roles},
            )
        session.delete(row)
    return read_settings(session)


def resolve_model(
    session: Session,
    role: str,
    request_override: AiModelSelection | None = None,
) -> ResolvedModel:
    spec = get_role_spec(role)
    global_row = _ensure_row(session)
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
    if request_override is not None:
        selection, source = request_override, "request"
    elif role_row and role_row.provider_override_id and role_row.model_override:
        selection = AiModelSelection(
            provider_id=role_row.provider_override_id,
            model_id=role_row.model_override,
        )
        source = "role_override"
    else:
        provider_id = getattr(global_row, f"default_{spec.modality}_provider_id")
        model_id = getattr(global_row, f"default_{spec.modality}_model_id")
        if provider_id is None or model_id is None:
            raise AiGatewayError(
                "Модель для функции не настроена",
                code="ai_model_not_configured",
                context={"role": role},
            )
        selection = AiModelSelection(provider_id=provider_id, model_id=model_id)
        source = f"{spec.modality}_default"
    provider = _provider(session, selection.provider_id)
    model = _model_for_selection(session, selection, modality=spec.modality)
    parameters = validate_role_parameters(role, role_row.parameters if role_row else {})
    return ResolvedModel(spec, provider, model, source, parameters)  # type: ignore[arg-type]


def provider_read(session: Session, row: AiProviderConnection, model_count: int) -> AiProviderRead:
    return AiProviderRead(
        id=row.id,
        label=row.label,
        catalog_profile=row.catalog_profile,
        base_url=row.base_url,
        has_api_key=bool(row.api_key_ciphertext),
        is_favorite=row.is_favorite,
        model_count=model_count,
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
    row = _ensure_row(session)
    providers = list(
        session.scalars(
            select(AiProviderConnection).order_by(
                AiProviderConnection.is_favorite.desc(), AiProviderConnection.label
            )
        )
    )
    counts = dict(
        session.execute(
            select(AiModelCatalogEntry.provider_id, func.count())
            .where(AiModelCatalogEntry.is_available.is_(True))
            .group_by(AiModelCatalogEntry.provider_id)
        ).all()
    )
    models = list(
        session.scalars(
            select(AiModelCatalogEntry).order_by(
                AiModelCatalogEntry.favorite_order.is_(None),
                AiModelCatalogEntry.favorite_order,
                AiModelCatalogEntry.display_name,
            )
        )
    )
    roles = []
    for spec in ROLE_SPECS.values():
        if not spec.visible:
            continue
        role_row = session.get(AiRoleSetting, spec.key)
        provider_override = role_row.provider_override_id if role_row else None
        model_override = role_row.model_override if role_row else None
        resolved_provider = provider_override or getattr(
            row, f"default_{spec.modality}_provider_id"
        )
        resolved_model = model_override or getattr(row, f"default_{spec.modality}_model_id")
        source = (
            "role_override"
            if provider_override and model_override
            else (f"{spec.modality}_default" if resolved_provider and resolved_model else None)
        )
        roles.append(
            AiRoleRead(
                role=spec.key,
                title=spec.title,
                description=spec.description,
                modality=spec.modality,
                enabled=role_row.enabled if role_row else True,
                provider_override_id=provider_override,
                model_override=model_override,
                resolved_provider_id=resolved_provider,
                resolved_model=resolved_model,
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
        confirm_cost_usd=row.confirm_cost_usd,
        confirm_input_tokens=row.confirm_input_tokens,
        usd_rub_rate=row.usd_rub_rate,
        usd_rub_rate_date=row.usd_rub_rate_date,
        default_text=_selection(row.default_text_provider_id, row.default_text_model_id),
        default_speech=_selection(row.default_speech_provider_id, row.default_speech_model_id),
        providers=[provider_read(session, item, counts.get(item.id, 0)) for item in providers],
        roles=roles,
        models=[AiModelRead.model_validate(item) for item in models],
        today_usage=_today_usage(session),
    )


def _selection(provider_id: UUID | None, model_id: str | None) -> AiModelSelection | None:
    if provider_id is None or model_id is None:
        return None
    return AiModelSelection(provider_id=provider_id, model_id=model_id)


def _provider(session: Session, provider_id: UUID) -> AiProviderConnection:
    row = session.get(AiProviderConnection, provider_id)
    if row is None:
        raise ProjectDomainError(
            "Провайдер не найден",
            status=404,
            code="ai_provider_not_found",
            context={"provider_id": str(provider_id)},
        )
    return row


def _model_for_selection(
    session: Session,
    selection: AiModelSelection,
    *,
    modality: Modality | None = None,
) -> AiModelCatalogEntry:
    row = session.get(AiModelCatalogEntry, (selection.provider_id, selection.model_id))
    if row is None or not row.is_available:
        raise ProjectDomainError(
            "Модель не найдена в локальном каталоге провайдера",
            status=422,
            code="ai_model_not_in_catalog",
            context={
                "provider_id": str(selection.provider_id),
                "model_id": selection.model_id,
            },
        )
    if modality == "text" and row.output_modalities and "text" not in row.output_modalities:
        raise ProjectDomainError(
            "Модель не поддерживает текстовый ответ",
            status=422,
            code="ai_model_modality_unsupported",
        )
    if modality == "speech" and "audio" not in row.input_modalities:
        raise ProjectDomainError(
            "Модель не принимает аудио",
            status=422,
            code="ai_model_modality_unsupported",
        )
    if modality == "vision" and "image" not in row.input_modalities:
        raise ProjectDomainError(
            "Модель не принимает изображения",
            status=422,
            code="ai_model_modality_unsupported",
        )
    return row


def _ensure_unique_provider_label(
    session: Session, label: str, provider_id: UUID | None = None
) -> None:
    existing = session.scalar(
        select(AiProviderConnection).where(func.lower(AiProviderConnection.label) == label.lower())
    )
    if existing is not None and existing.id != provider_id:
        raise ProjectDomainError(
            "Провайдер с таким названием уже существует",
            status=409,
            code="ai_provider_label_exists",
        )
