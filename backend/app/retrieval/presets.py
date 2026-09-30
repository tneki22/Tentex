from dataclasses import dataclass

from app.models import RetrievalPreset


@dataclass(frozen=True)
class PresetConfig:
    lexical_candidates: int
    semantic_candidates: int
    final_results: int
    rerank_depth: int
    rrf_k: int = 60


PRESETS = {
    RetrievalPreset.FAST: PresetConfig(30, 30, 8, 0),
    RetrievalPreset.BALANCED: PresetConfig(50, 50, 10, 0),
    # Qwen3 Reranker на CPU читает кусок ≈ 1,2 с: десять мест — предел ожидания.
    # Пулы как у «Сбалансированно»: reranker переставляет ту же десятку. Пул 80+80
    # меняет RRF и вытеснял из десятки верные места раньше, чем их прочтёт модель.
    RetrievalPreset.ACCURATE: PresetConfig(50, 50, 12, 10),
}
