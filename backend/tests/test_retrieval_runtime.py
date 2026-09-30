"""Healthcheck не будит inference, ошибки дочернего процесса сохраняют HTTP-контракт."""

from concurrent.futures import Future

import pytest
from fastapi.testclient import TestClient

from app.retrieval import runtime


@pytest.fixture(autouse=True)
def idle_mode(monkeypatch):
    """Граница процесса проверяется независимо от штатного выбора быстрого поиска."""
    monkeypatch.setattr(runtime.settings, "retrieval_model_idle_seconds", 600)


def test_health_does_not_start_process():
    with TestClient(runtime.app) as client:
        assert not runtime._pool.loaded
        health = client.get("/health").json()
        assert health["loaded_transformer_models"] == 0
        assert not runtime._pool.loaded


def test_missing_model_error_crosses_process_boundary():
    with TestClient(runtime.app) as client:
        response = client.post("/embed", json={"model": "test/missing-model", "input": ["текст"]})
        assert response.status_code == 422
        assert "не установлена" in response.json()["detail"]
    assert not runtime._pool.loaded


def test_runtime_keeps_all_response_formats(monkeypatch):
    expected = {
        "embeddings": {"data": [{"index": 0, "embedding": [1.0]}]},
        "embed": {"dimension": 1, "vectors": [[1.0]]},
        "rerank": {"results": [{"index": 0, "score": 0.9}]},
    }

    def submit(handler, operation, command):
        future = Future()
        future.set_result((expected[operation], {"loaded_transformer_models": 1}))
        return future

    monkeypatch.setattr(runtime._pool, "submit", submit)
    with TestClient(runtime.app) as client:
        for path, operation, payload in (
            ("/v1/embeddings", "embeddings", {"model": "test/model", "input": "текст"}),
            ("/embed", "embed", {"model": "test/model", "input": ["текст"]}),
            ("/rerank", "rerank", {
                "model": "test/model", "query": "текст", "documents": ["текст"],
            }),
        ):
            response = client.post(path, json=payload)
            assert response.status_code == 200
            assert response.json() == expected[operation]


def test_default_mode_keeps_models_warm_without_extra_process(monkeypatch):
    monkeypatch.setattr(runtime.settings, "retrieval_model_idle_seconds", 0)
    monkeypatch.setattr(runtime, "run_inference", lambda operation, command: (
        {"vectors": [[1.0]]}, {"loaded_transformer_models": 1},
    ))
    with TestClient(runtime.app) as client:
        response = client.post("/embed", json={"model": "test/model", "input": ["текст"]})
        assert response.status_code == 200
        assert not runtime._pool.loaded
        assert client.get("/health").json()["loaded_transformer_models"] == 1
