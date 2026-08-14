from pathlib import Path
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.ai.catalog import add_catalog_model, search_catalog
from app.ai.credentials import decrypt_secret, encrypt_secret
from app.ai.provider import FakeTransport, ProviderModel
from app.ai.router import router
from app.ai.schemas import (
    AiCatalogModelWrite,
    AiDefaultWrite,
    AiManualModelWrite,
    AiModelFavoritesWrite,
    AiModelSelection,
    AiProviderWrite,
    AiRoleWrite,
)
from app.ai.settings import (
    create_provider,
    delete_provider,
    resolve_model,
    set_default,
    update_model_favorites,
    update_provider,
    update_role,
    upsert_manual_model,
    validate_base_url,
)
from app.config import settings
from app.db import get_session
from app.models import AiModelCatalogEntry, AiProviderConnection, AiRoleSetting, AiSettings
from app.projects.errors import ProjectDomainError


def test_credentials_are_encrypted_and_survive_session_restart(
    session: Session, ai_config: str
) -> None:
    del ai_config
    provider = session.query(AiProviderConnection).one()
    assert provider.api_key_ciphertext is not None
    assert decrypt_secret(provider.api_key_ciphertext) == "test-secret"
    database = Path(str(session.bind.url.database))
    assert b"test-secret" not in database.read_bytes()


def test_wrong_installation_secret_is_diagnostic(
    session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "secret_key", Fernet.generate_key().decode())
    encrypted = encrypt_secret("provider-key")
    monkeypatch.setattr(settings, "secret_key", Fernet.generate_key().decode())
    with pytest.raises(ProjectDomainError, match="расшифровать") as caught:
        decrypt_secret(encrypted)
    assert caught.value.code == "ai_secret_mismatch"


def test_model_resolution_and_role_override(session: Session, ai_config: str) -> None:
    inherited = resolve_model(session, "material_text_cleanup")
    assert inherited.model_id == ai_config
    assert inherited.source == "text_default"
    session.rollback()
    provider_id = session.query(AiProviderConnection.id).scalar()
    session.rollback()
    update_role(
        session,
        "material_text_cleanup",
        AiRoleWrite(
            enabled=True,
            provider_override_id=provider_id,
            model_override=ai_config,
            parameters={"max_output_tokens": 7000},
        ),
    )
    overridden = resolve_model(session, "material_text_cleanup")
    assert overridden.model_id == ai_config
    assert overridden.source == "role_override"
    assert overridden.parameters["max_output_tokens"] == 7000


def test_disabled_and_request_override_rules(session: Session, ai_config: str) -> None:
    del ai_config
    global_settings = session.get(AiSettings, 1)
    assert global_settings is not None
    global_settings.external_models_enabled = False
    session.commit()
    with pytest.raises(ProjectDomainError) as caught:
        resolve_model(session, "material_text_cleanup")
    assert caught.value.code == "ai_disabled"
    global_settings.external_models_enabled = True
    session.add(AiRoleSetting(role="material_text_cleanup", enabled=False, parameters={}))
    session.commit()
    with pytest.raises(ProjectDomainError) as caught:
        resolve_model(session, "material_text_cleanup")
    assert caught.value.code == "ai_role_disabled"
    role = session.get(AiRoleSetting, "material_text_cleanup")
    assert role is not None
    role.enabled = True
    session.commit()
    with pytest.raises(ProjectDomainError) as caught:
        resolve_model(
            session,
            "material_text_cleanup",
            AiModelSelection(
                provider_id=session.query(AiProviderConnection).one().id,
                model_id="test/inline",
            ),
        )
    assert caught.value.code == "ai_model_override_forbidden"


@pytest.mark.parametrize(
    "value",
    ["file:///tmp/model", "example.com/v1", "https://user:pass@example.com/v1"],
)
def test_base_url_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(ProjectDomainError):
        validate_base_url(value)
    assert validate_base_url("http://localhost:11434/v1/") == "http://localhost:11434/v1"


def test_http_never_returns_secret(session: Session, ai_config: str) -> None:
    del ai_config
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)
    response = client.get("/api/settings/ai")
    assert response.status_code == 200
    serialized = response.text
    assert "test-secret" not in serialized
    assert "ciphertext" not in serialized
    provider = response.json()["providers"][0]
    assert provider["has_api_key"] is True
    session.rollback()
    response = client.put(
        f"/api/settings/ai/providers/{provider['id']}",
        json={
            "label": "Test provider",
            "catalog_profile": "openai_compatible",
            "api_key": "rotated-secret",
            "base_url": "https://example.test/v2",
        },
    )
    assert response.status_code == 200
    assert "rotated-secret" not in response.text
    row = session.get(AiProviderConnection, UUID(provider["id"]))
    assert row is not None and row.api_key_ciphertext is not None
    assert decrypt_secret(row.api_key_ciphertext) == "rotated-secret"


def test_empty_key_on_put_keeps_existing_key(session: Session, ai_config: str) -> None:
    del ai_config
    provider = session.query(AiProviderConnection).one()
    before = provider.api_key_ciphertext
    provider_id = provider.id
    provider_label = provider.label
    provider_base_url = provider.base_url
    session.rollback()
    update_provider(
        session,
        provider_id,
        AiProviderWrite(
            label=provider_label,
            catalog_profile="openai_compatible",
            base_url=provider_base_url,
            api_key="",
        ),
    )
    after = session.get(AiProviderConnection, provider_id).api_key_ciphertext
    assert after == before


def test_same_model_id_is_scoped_by_provider(session: Session, ai_config: str) -> None:
    first = session.query(AiProviderConnection).one()
    first_id = first.id
    session.rollback()
    snapshot = create_provider(
        session,
        AiProviderWrite(
            label="Second provider",
            catalog_profile="openai_compatible",
            base_url="https://second.example/v1",
            api_key="second-secret",
        ),
    )
    second = next(
        provider for provider in snapshot.providers if provider.label == "Second provider"
    )
    session.rollback()
    upsert_manual_model(
        session,
        second.id,
        AiManualModelWrite(
            model_id=ai_config,
            display_name="Same id, second provider",
            context_length=32_000,
            prompt_price_usd="0.000003",
        ),
    )
    session.rollback()
    selection = AiModelSelection(provider_id=second.id, model_id=ai_config)
    set_default(session, "text", AiDefaultWrite(selection=selection))
    resolved = resolve_model(session, "material_text_cleanup")
    assert resolved.provider.id == second.id
    assert resolved.model_id == ai_config
    session.rollback()
    favorites = update_model_favorites(
        session,
        AiModelFavoritesWrite(
            models=[
                AiModelSelection(provider_id=first_id, model_id=ai_config),
                selection,
            ]
        ),
    )
    ordered = sorted(
        (model for model in favorites.models if model.favorite_order is not None),
        key=lambda model: model.favorite_order or 0,
    )
    assert [model.provider_id for model in ordered] == [first_id, second.id]


def test_provider_delete_reports_default_dependency(session: Session, ai_config: str) -> None:
    del ai_config
    provider = session.query(AiProviderConnection).one()
    provider_id = provider.id
    session.rollback()
    with pytest.raises(ProjectDomainError) as caught:
        delete_provider(session, provider_id)
    assert caught.value.code == "ai_provider_in_use"
    assert caught.value.status == 409
    assert caught.value.context == {"defaults": ["text"], "roles": []}


@pytest.mark.asyncio
async def test_model_search_does_not_fill_saved_catalog(
    session: Session, ai_config: str
) -> None:
    provider = session.query(AiProviderConnection).one()
    provider_id = provider.id
    session.rollback()
    fake = FakeTransport(
        models=[
            ProviderModel(model_id="catalog/one", display_name="Catalog one"),
            ProviderModel(model_id="catalog/two", display_name="Catalog two"),
        ]
    )

    found = await search_catalog(session, provider_id, fake)

    assert [model.model_id for model in found] == ["catalog/one", "catalog/two"]
    assert all(model.is_added is False for model in found)
    assert session.query(AiModelCatalogEntry).count() == 1
    assert session.get(AiModelCatalogEntry, (provider_id, ai_config)) is not None


@pytest.mark.asyncio
async def test_model_search_treats_dynamic_negative_price_as_unknown(
    session: Session, ai_config: str
) -> None:
    del ai_config
    provider_id = session.query(AiProviderConnection.id).scalar()
    session.rollback()
    fake = FakeTransport(
        models=[
            ProviderModel(
                model_id="router/dynamic",
                display_name="Dynamic router",
                prompt_price_usd=-1,
                completion_price_usd=-1,
            )
        ]
    )

    found = await search_catalog(session, provider_id, fake)

    assert found[0].prompt_price_usd is None
    assert found[0].completion_price_usd is None


def test_catalog_model_is_saved_only_after_explicit_add(
    session: Session, ai_config: str
) -> None:
    del ai_config
    provider_id = session.query(AiProviderConnection.id).scalar()
    session.rollback()

    snapshot = add_catalog_model(
        session,
        provider_id,
        AiCatalogModelWrite(
            model_id="catalog/selected",
            display_name="Selected model",
            context_length=64_000,
            input_modalities=["text"],
            output_modalities=["text"],
            prompt_price_usd="0.000001",
            completion_price_usd="0.000004",
        ),
    )

    assert any(model.model_id == "catalog/selected" for model in snapshot.models)
    assert snapshot.providers[0].model_count == 2
    row = session.get(AiModelCatalogEntry, (provider_id, "catalog/selected"))
    assert row is not None
    assert row.is_manually_added is False
