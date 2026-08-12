from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app


def _client_with_boom() -> TestClient:
    app: FastAPI = create_app()

    @app.get("/api/_boom")
    def _boom() -> None:
        raise RuntimeError("нарочно упали")

    return TestClient(app, raise_server_exceptions=False)


def test_request_id_header_present() -> None:
    client = TestClient(create_app())
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")


def test_unhandled_exception_returns_clean_envelope() -> None:
    response = _client_with_boom().get("/api/_boom")
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal_error"
    assert body["request_id"]
    # Текст исключения наружу не утекает.
    assert "нарочно упали" not in body["detail"]
