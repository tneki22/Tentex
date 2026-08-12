from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.ai.credentials import decrypt_secret, encrypt_secret
from app.ai.router import router
from app.ai.schemas import AiConnectionWrite, AiRoleWrite
from app.ai.settings import resolve_model, update_connection, update_role, validate_base_url
from app.config import settings
from app.db import get_session
from app.models import AiConnection, AiRoleSetting, AiSettings
from app.projects.errors import ProjectDomainError


def test_credentials_are_encrypted_and_survive_session_restart(
    session: Session, ai_config: str
) -> None:
    del ai_config
    connection = session.get(AiConnection, "text")
    assert connection is not None and connection.api_key_ciphertext is not None
    assert decrypt_secret(connection.api_key_ciphertext) == "test-secret"
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
    update_role(
        session,
        "material_text_cleanup",
        AiRoleWrite(
            enabled=True,
            model_override="test/other",
            parameters={"max_output_tokens": 7000},
        ),
    )
    overridden = resolve_model(session, "material_text_cleanup")
    assert overridden.model_id == "test/other"
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
        resolve_model(session, "material_text_cleanup", "test/inline")
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
    assert response.json()["connections"][0]["has_api_key"] is True
    session.rollback()
    response = client.put(
        "/api/settings/ai/connections/text",
        json={"api_key": "rotated-secret", "base_url": "https://example.test/v2"},
    )
    assert response.status_code == 200
    assert "rotated-secret" not in response.text
    connection = session.get(AiConnection, "text")
    assert connection is not None and connection.api_key_ciphertext is not None
    assert decrypt_secret(connection.api_key_ciphertext) == "rotated-secret"


def test_empty_key_on_put_keeps_existing_key(session: Session, ai_config: str) -> None:
    del ai_config
    before = session.get(AiConnection, "text").api_key_ciphertext
    session.rollback()
    update_connection(session, "text", AiConnectionWrite(api_key=""))
    after = session.get(AiConnection, "text").api_key_ciphertext
    assert after == before
