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
    RetrievalPreset.ACCURATE: PresetConfig(80, 80, 12, 30),
}
