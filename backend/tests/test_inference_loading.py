"""Параллельный холодный запрос не загружает одну модель несколько раз."""

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from app.retrieval import inference


def test_cold_load_is_shared_between_concurrent_requests(tmp_path, monkeypatch):
    calls = []
    tokenizer = object()
    model = SimpleNamespace(eval=lambda: model)

    def load_tokenizer(*args, **kwargs):
        calls.append("tokenizer")
        time.sleep(0.05)
        return tokenizer

    def load_model(*args, **kwargs):
        calls.append("model")
        return model

    monkeypatch.setattr(inference, "model_path", lambda _: tmp_path)
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(
        AutoTokenizer=SimpleNamespace(from_pretrained=load_tokenizer),
        AutoModel=SimpleNamespace(from_pretrained=load_model),
    ))
    inference._cached_transformer_model.cache_clear()
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(inference._transformer_model, ["test/model"] * 8))
        assert calls == ["tokenizer", "model"]
        assert all(result == (tokenizer, model) for result in results)
        assert inference.model_cache_state()["loaded_transformer_models"] == 1
    finally:
        inference._cached_transformer_model.cache_clear()
