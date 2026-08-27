"""Каталог наборов моделей распознавания.

Продукт ставится с GitHub одним архивом и **без единой модели внутри**: веса
занимают гигабайты, лицензируются отдельно и зависят от железа. Пользователь
открывает «Параметры установки → Распознавание», видит здесь всё, что нужно
знать до нажатия «Установить» — откуда качается, сколько весит, что требует от
машины, под какой лицензией — и ставит только то, что ему подходит.

Поэтому каталог описательный, а не только технический: каждое поле кто-то
читает глазами. Ставить модели откуда попало нельзя — источник один и он
подписанный: репозитории организации PaddlePaddle на Hugging Face.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Единственный разрешённый источник весов. Организация подтверждена Hugging Face
# и является автором PaddleOCR; ссылка ведёт на страницу, которую можно открыть
# и прочитать до установки.
SOURCE_TITLE = "Hugging Face, организация PaddlePaddle"
SOURCE_URL = "https://huggingface.co/PaddlePaddle"
LICENSE_TITLE = "Apache 2.0"
LICENSE_URL = "https://www.apache.org/licenses/LICENSE-2.0"

MB = 1000 * 1000
GB = 1000 * MB

RepoLayout = Literal["paddlex", "hf_cache"]


@dataclass(frozen=True)
class ModelRepo:
    """Один репозиторий Hugging Face внутри набора.

    `layout` решает, куда лягут файлы, и это не наш выбор, а требование того,
    кто их потом читает:

    - `paddlex` — PaddleX ищет веса в `data/models/official_models/<имя>/`
      обычной плоской папкой;
    - `hf_cache` — модель, загружаемая напрямую через `transformers`, то есть из
      стандартного кеша Hugging Face в `data/models/huggingface`.
    """

    repo_id: str
    size_bytes: int
    layout: RepoLayout = "paddlex"

    @property
    def folder(self) -> str:
        return self.repo_id.split("/")[-1]


@dataclass(frozen=True)
class OcrModelSpec:
    key: str
    engine: str
    title: str
    # Что набор делает — одним предложением, без сокращений и терминов.
    summary: str
    # Когда его выбирать. Пользователь сравнивает наборы именно по этой строке.
    good_for: str
    repos: tuple[ModelRepo, ...]
    device: Literal["cpu", "gpu"]
    languages: str
    # Минимум, ниже которого не запустится вовсе, и комфортный объём.
    min_vram_mb: int | None = None
    recommended_vram_mb: int | None = None
    min_ram_mb: int = 4000
    # Предупреждения, которые честнее сказать до установки, а не после.
    notes: tuple[str, ...] = ()
    # Набор, предлагаемый по умолчанию для своего движка.
    recommended: bool = False

    @property
    def size_bytes(self) -> int:
        return sum(repo.size_bytes for repo in self.repos)


OCR_MODELS: tuple[OcrModelSpec, ...] = (
    OcrModelSpec(
        key="fast-ru",
        engine="fast",
        title="Русский и английский",
        summary=(
            "Находит строки на странице и читает их. Смешанный текст в одном "
            "документе разбирает без переключения языка."
        ),
        good_for="Обычный выбор для конспектов, методичек и сканов на русском.",
        repos=(
            ModelRepo("PaddlePaddle/PP-OCRv5_server_det", 88 * MB),
            ModelRepo("PaddlePaddle/eslav_PP-OCRv5_mobile_rec", 8 * MB),
        ),
        device="cpu",
        languages="Русский, английский, украинский, белорусский",
        min_ram_mb=4000,
        recommended=True,
    ),
    OcrModelSpec(
        key="textbook-formulas",
        engine="textbook",
        title="Формулы и структура страницы",
        summary=(
            "Размечает страницу, читает русский текст и переводит печатные формулы в LaTeX."
        ),
        good_for=(
            "Единственный профиль «Учебник» для видеокарты с 8 ГБ: методички и "
            "учебники с формулами."
        ),
        repos=(
            ModelRepo("PaddlePaddle/PP-DocLayout_plus-L", 130 * MB),
            ModelRepo("PaddlePaddle/PP-FormulaNet_plus-M", 624 * MB),
            ModelRepo("PaddlePaddle/PP-OCRv5_server_det", 88 * MB),
            ModelRepo("PaddlePaddle/eslav_PP-OCRv5_mobile_rec", 8 * MB),
        ),
        device="gpu",
        languages="Русский, английский",
        min_vram_mb=6000,
        recommended_vram_mb=8000,
        min_ram_mb=8000,
        notes=(
            "Связка: PP-DocLayout_plus-L размечает страницу и находит формулы отдельным "
            "классом, PP-FormulaNet Plus M переводит их в LaTeX, PP-OCRv5 читает обычный текст.",
            "Распознавание таблиц и диаграмм выключено: так профиль укладывается в 8 ГБ "
            "видеопамяти. Таблица останется текстом, без сетки ячеек.",
            "Обрабатывается одна страница и один фрагмент за раз. Перед запуском закройте "
            "игры и программы, использующие видеокарту.",
        ),
        recommended=True,
    ),
)

MODELS_BY_KEY: dict[str, OcrModelSpec] = {spec.key: spec for spec in OCR_MODELS}


def models_for(engine: str) -> tuple[OcrModelSpec, ...]:
    return tuple(spec for spec in OCR_MODELS if spec.engine == engine)
