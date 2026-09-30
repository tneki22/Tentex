"""План одного запуска обработки: снимок настроек, оценка расхода и предел.

Снимок стратегии, режима изображений, OCR-настроек, моделей и версий промптов
кладётся в checkpoint задачи при постановке: пауза, повтор и смена общих
настроек не меняют ход уже начатого запуска.

Оценка — верхняя, а не средняя: каждый вызов считается с потолком ответа
своей роли, изображение — плитками выреза. Запуск не ждёт анализа страниц:
без готовой оценки использует отдельный быстрый предел по числу страниц и
ценам каталога. Неизвестная цена требует явного согласия.
"""

from __future__ import annotations

import math
import os
import shutil
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from multiprocessing import get_context
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from typing import Any

import pymupdf as fitz
from sqlalchemy.orm import Session

from app.ai.job_budget import budget_state
from app.ai.roles import get_role_spec
from app.ai.schemas import AiModelSelection
from app.materials.parsers.cloud_vlm import (
    IMAGE_PROMPT_VERSION,
    IMAGE_ROLE,
    MAX_REGIONS_PER_REQUEST,
    ROLE,
)
from app.materials.parsers.formula_zones import find_zones
from app.materials.parsers.native import MIN_IMAGE_SIDE, repeated_image_xrefs
from app.materials.parsers.text_layer import diagnose
from app.materials.schemas import ProcessingEstimateRead, ProcessingStart
from app.materials.storage import material_path
from app.models import AiModelCatalogEntry, AiSettings, Material, MaterialSourceKind, ParserMode
from app.ocr.engines import OcrRuntimeParams
from app.ocr.settings import runtime_params
from app.projects.errors import ProjectConflictError, ProjectDomainError

# Сколько страниц диагностируется для оценки. Больше — дольше ответ API на
# книге в тысячу страниц без выигрыша в точности: остальное экстраполируется.
MAX_SAMPLED_PAGES = 60
# Один и тот же диалог может запросить оценку несколько раз. Диагностика PDF
# дорогая, поэтому одинаковые запросы делят результат, а не читают файл параллельно.
_shape_lock = Lock()
_shape_executor: ProcessPoolExecutor | None = None
# Токены инструкции со схемой ответа у одного вызова (текст, без картинки).
PAGE_PROMPT_TOKENS = 900
REGION_PROMPT_TOKENS = 600
IMAGE_PROMPT_TOKENS = 900
IMAGE_TILE_TOKENS = 258
TILE_PX = 768
# Типичный ответ: плотная страница, пачка формул, одно описание.
PAGE_TYPICAL_OUTPUT = 1300
REGION_TYPICAL_OUTPUT = 300
IMAGE_TYPICAL_OUTPUT = 900
# Длинная сторона выреза на описание (`native.DESCRIBE_MAX_SIDE_PX`): не больше
# четырёх плиток на изображение.
IMAGE_TILES_UPPER = 4
# Доля текстовых страниц, где обычно есть формулы на транскрипцию.
REGION_TYPICAL_SHARE = Decimal("0.3")
# Запас попыток сверх расчёта по страницам.
CALLS_SLACK = 4
# Векторные схемы находит разметчик уже при разборе; заранее на каждую
# текстовую страницу закладывается доля описания.
VECTOR_PICTURE_ALLOWANCE = Decimal("0.3")
# Нижняя граница суммы предела, чтобы нулевая оценка не запрещала всё.
MIN_BUDGET_USD = Decimal("0.01")
# Без подробной оценки ограничиваем каждый запуск и числом попыток, и суммой.
# На страницу допускаем несколько пачек вырезов, описаний и повторов.
QUICK_CALLS_PER_PAGE = 20
QUICK_MAX_COST_USD = Decimal("10")


@dataclass(frozen=True)
class _Shape:
    """Что оценка знает о выбранных страницах."""

    pages: int
    whole_pages: int
    text_pages: int
    suspicious_pages: int
    images: int
    page_tokens: int
    sampled: bool
    # Пачки вырезов формул и таблиц: на странице методички из Word их бывает
    # три-четыре, а не одна. `None` — по пачке на текстовую страницу.
    region_calls: int | None = None


def page_model(session: Session) -> AiModelSelection | None:
    """Модель страниц «Облака» — зрительная модель по умолчанию."""
    row = session.get(AiSettings, 1)
    if row is None or row.default_vision_provider_id is None or not row.default_vision_model_id:
        return None
    return AiModelSelection(
        provider_id=row.default_vision_provider_id, model_id=row.default_vision_model_id
    )


def description_model(session: Session, command: ProcessingStart) -> AiModelSelection | None:
    """Модель описаний: явный выбор запуска или модель страниц."""
    if command.description_provider_id and command.description_model_id:
        selection = AiModelSelection(
            provider_id=command.description_provider_id, model_id=command.description_model_id
        )
        _require_vision(session, selection)
        return selection
    return page_model(session)


def _require_vision(session: Session, selection: AiModelSelection) -> AiModelCatalogEntry:
    row = session.get(AiModelCatalogEntry, (selection.provider_id, selection.model_id))
    if row is None:
        raise ProjectDomainError(
            "Модели описаний нет в каталоге", status=422, code="ai_model_not_found"
        )
    if "image" not in (row.input_modalities or []):
        raise ProjectDomainError(
            "Модель описаний не принимает изображения",
            status=422,
            code="ai_model_modality_unsupported",
        )
    return row


def run_options(
    session: Session, material: Material, command: ProcessingStart
) -> dict[str, Any]:
    """Снимок настроек запуска для checkpoint задачи."""
    params = runtime_params(session)
    options: dict[str, Any] = {
        "cloud_strategy": command.cloud_strategy or params.cloud_strategy,
        "image_mode": command.image_mode,
        "quality_threshold": params.quality_threshold,
        "raster_scale": params.raster_scale,
        "fast_model_id": params.fast_model_id,
        "cpu_profile": params.cpu_profile,
    }
    if command.parser_mode == ParserMode.CLOUD and material.source_kind != MaterialSourceKind.AUDIO:
        pages = page_model(session)
        described = description_model(session, command)
        options |= {
            "page_model": pages.model_dump(mode="json") if pages else None,
            "description_model": described.model_dump(mode="json") if described else None,
            "page_prompt_version": get_role_spec(ROLE).prompt_version,
            "image_prompt_version": IMAGE_PROMPT_VERSION,
        }
    return options


def params_from_options(options: dict[str, Any], current: OcrRuntimeParams) -> OcrRuntimeParams:
    """Параметры парсера из снимка задачи; у старых задач без снимка — текущие."""
    if not options:
        return current
    return OcrRuntimeParams(
        quality_threshold=float(options.get("quality_threshold", current.quality_threshold)),
        raster_scale=float(options.get("raster_scale", current.raster_scale)),
        fast_language=current.fast_language,
        fast_model_id=str(options.get("fast_model_id") or current.fast_model_id),
        cpu_profile=options.get("cpu_profile") or current.cpu_profile,
        cloud_strategy=options.get("cloud_strategy") or current.cloud_strategy,
        image_mode=options.get("image_mode"),
    )


def selection_from_options(options: dict[str, Any], key: str) -> AiModelSelection | None:
    value = (options or {}).get(key)
    return AiModelSelection.model_validate(value) if value else None


def _tiles(width_px: float, height_px: float) -> int:
    return max(1, math.ceil(width_px / TILE_PX) * math.ceil(height_px / TILE_PX))


def _lower_estimate_priority() -> None:
    """Фоновая диагностика уступает процессор разбору и ответам приложения."""
    if hasattr(os, "nice"):
        os.nice(10)


@lru_cache(maxsize=32)
def _cached_pdf_shape(
    path: Path, size: int, modified_ns: int, pages: tuple[int, ...],
    strategy: str, raster_scale: float,
) -> _Shape:
    """Диагностика живёт вне API-процесса: PyMuPDF задерживает его потоки."""
    global _shape_executor
    if _shape_executor is None:
        _shape_executor = ProcessPoolExecutor(
            max_workers=1, mp_context=get_context("spawn"),
            initializer=_lower_estimate_priority,
        )
    return _shape_executor.submit(
        _calculate_pdf_shape, path, pages, strategy, raster_scale
    ).result()


def _calculate_pdf_shape(
    path: Path, pages: tuple[int, ...], strategy: str, raster_scale: float
) -> _Shape:
    """Диагноз выборки выбранных страниц PDF, экстраполированный на все."""
    # Случайное чтение PDF через bind mount Windows в разы медленнее: у 30 МБ
    # файла четыре страницы занимали около минуты вместо долей секунды.
    with TemporaryDirectory(prefix="tentex-estimate-") as temporary:
        local_path = Path(temporary) / "source.pdf"
        shutil.copyfile(path, local_path)
        return _local_pdf_shape(local_path, pages, strategy, raster_scale)


def _local_pdf_shape(
    path: Path, pages: tuple[int, ...], strategy: str, raster_scale: float
) -> _Shape:
    """Читать страницы с локального диска процесса оценки."""
    whole_by_strategy = strategy == "page"
    step = max(1, math.ceil(len(pages) / MAX_SAMPLED_PAGES))
    sample = pages[::step]
    with fitz.open(path) as document:
        repeated: frozenset[int] | None = None
        whole = text = suspicious = images = batches = 0
        page_tokens = 0
        for number in sample:
            page = document[number - 1]
            dpi = 150.0 * raster_scale
            page_tokens = max(
                page_tokens,
                _tiles(page.rect.width / 72 * dpi, page.rect.height / 72 * dpi)
                * IMAGE_TILE_TOKENS,
            )
            route = diagnose(page).route
            if route == "blank" and not whole_by_strategy:
                continue
            goes_whole = (
                whole_by_strategy
                or route == "scan"
                or (route in {"partial", "broken"} and strategy == "auto")
            )
            suspicious += route in {"partial", "broken"}
            if goes_whole:
                whole += 1
                continue
            text += 1
            zones = find_zones(page)
            batches += max(1, math.ceil(len(zones) / MAX_REGIONS_PER_REQUEST))
            if repeated is None:
                repeated = repeated_image_xrefs(document)
            images += sum(
                1
                for info in page.get_image_info(xrefs=True)
                if info.get("xref") not in repeated
                and _side_ok(info.get("bbox"))
            )
    factor = len(pages) / max(1, len(sample))
    return _Shape(
        pages=len(pages),
        whole_pages=round(whole * factor),
        text_pages=round(text * factor),
        suspicious_pages=round(suspicious * factor),
        images=round(images * factor),
        page_tokens=page_tokens or 20 * IMAGE_TILE_TOKENS,
        sampled=step > 1,
        region_calls=round(batches * factor),
    )


def _pdf_shape(path: Path, pages: list[int], params: OcrRuntimeParams) -> _Shape:
    """Повторные запросы к неизменившемуся PDF используют один диагноз."""
    stat = path.stat()
    # lru_cache защищает словарь, но не сливает одновременные cache miss.
    with _shape_lock:
        return _cached_pdf_shape(
            path, stat.st_size, stat.st_mtime_ns, tuple(pages),
            params.cloud_strategy, params.raster_scale,
        )


def _side_ok(bbox: object) -> bool:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return False
    return min(bbox[2] - bbox[0], bbox[3] - bbox[1]) >= MIN_IMAGE_SIDE


def _shape(material: Material, pages: list[int], params: OcrRuntimeParams) -> _Shape:
    path = material_path(material.storage_path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _pdf_shape(path, pages, params)
    if suffix in {".jpg", ".jpeg", ".png"}:
        return _Shape(1, 1, 0, 0, 0, 20 * IMAGE_TILE_TOKENS, False)
    if suffix == ".docx":
        from docx import Document

        images = len(Document(path).inline_shapes)
        return _Shape(1, 0, 1, 0, images, 0, False)
    return _Shape(1, 0, 1, 0, 0, 0, False)


def _price(session: Session, selection: AiModelSelection | None) -> tuple[Decimal, Decimal] | None:
    if selection is None:
        return None
    row = session.get(AiModelCatalogEntry, (selection.provider_id, selection.model_id))
    if row is None or row.prompt_price_usd is None or row.completion_price_usd is None:
        return None
    if row.prompt_price_usd < 0 or row.completion_price_usd < 0:
        return None
    return row.prompt_price_usd, row.completion_price_usd


def _max_output(role: str) -> int:
    return int(get_role_spec(role).default_parameters.get("max_output_tokens", 4000))


def estimate(
    session: Session, material: Material, command: ProcessingStart, pages: list[int]
) -> ProcessingEstimateRead:
    """Что уйдёт наружу на этом запуске и верхняя оценка стоимости."""
    params = params_from_options(run_options(session, material, command), runtime_params(session))
    image_mode = params.images_for(command.parser_mode.value)
    shape = _shape(material, pages, params)
    notes: list[str] = []
    if command.parser_mode != ParserMode.CLOUD:
        if shape.suspicious_pages:
            notes.append("Страницы с неполным или испорченным слоем прочитает локальный OCR")
        return ProcessingEstimateRead(
            parser_mode=command.parser_mode,
            cloud_strategy=params.cloud_strategy,
            image_mode=image_mode,
            pages=shape.pages,
            whole_pages=shape.whole_pages,
            text_pages=shape.text_pages,
            suspicious_pages=shape.suspicious_pages,
            image_candidates=shape.images,
            requests_upper=0,
            page_model_id=None,
            description_model_id=None,
            price_known=True,
            cost_typical_usd=Decimal(0),
            cost_upper_usd=Decimal(0),
            sampled=shape.sampled,
            notes=notes,
        )
    pages_model = page_model(session)
    images_model = description_model(session, command)
    describe = image_mode == "describe"
    # На странице целиком схему режет модель; в «Описывать» у каждой такой
    # страницы закладывается одно описание выреза.
    image_calls = (
        shape.images
        + shape.whole_pages
        + math.ceil(shape.text_pages * VECTOR_PICTURE_ALLOWANCE)
        if describe
        else 0
    )
    region_calls = shape.text_pages if shape.region_calls is None else shape.region_calls
    requests_upper = shape.whole_pages + region_calls + image_calls
    page_price = _price(session, pages_model)
    image_price = _price(session, images_model) if describe else page_price
    price_known = page_price is not None and (not describe or image_price is not None)
    typical = upper = None
    if price_known and page_price is not None:
        page_in = shape.page_tokens + PAGE_PROMPT_TOKENS
        region_in = 2 * IMAGE_TILE_TOKENS + REGION_PROMPT_TOKENS
        image_in = IMAGE_TILES_UPPER * IMAGE_TILE_TOKENS + IMAGE_PROMPT_TOKENS
        p_in, p_out = page_price
        i_in, i_out = image_price or page_price
        upper = (
            shape.whole_pages * (p_in * page_in + p_out * _max_output(ROLE))
            + region_calls * (p_in * region_in + p_out * _max_output(ROLE))
            + image_calls * (i_in * image_in + i_out * _max_output(IMAGE_ROLE))
        )
        typical = (
            shape.whole_pages * (p_in * page_in + p_out * PAGE_TYPICAL_OUTPUT)
            + region_calls
            * REGION_TYPICAL_SHARE
            * (p_in * region_in + p_out * REGION_TYPICAL_OUTPUT)
            + image_calls * (i_in * image_in + i_out * IMAGE_TYPICAL_OUTPUT)
        )
    else:
        notes.append("Цена модели неизвестна: предел запуска считается только по числу вызовов")
    if shape.sampled:
        notes.append(f"Оценка по выборке {MAX_SAMPLED_PAGES} страниц из {shape.pages}")
    if describe:
        notes.append(
            "Векторные схемы находит разметчик при разборе: на них заложен запас, "
            "а сверх предела изображения останутся без описания"
        )
    return ProcessingEstimateRead(
        parser_mode=command.parser_mode,
        cloud_strategy=params.cloud_strategy,
        image_mode=image_mode,
        pages=shape.pages,
        whole_pages=shape.whole_pages,
        text_pages=shape.text_pages,
        suspicious_pages=shape.suspicious_pages,
        image_candidates=shape.images,
        requests_upper=requests_upper,
        page_model_id=pages_model.model_id if pages_model else None,
        description_model_id=images_model.model_id if images_model and describe else None,
        price_known=price_known,
        cost_typical_usd=typical.quantize(Decimal("0.0001")) if typical is not None else None,
        cost_upper_usd=upper.quantize(Decimal("0.0001")) if upper is not None else None,
        sampled=shape.sampled,
        notes=notes,
    )


def run_budget(
    session: Session, command: ProcessingStart, pages: int, image_mode: str
) -> dict[str, Any] | None:
    """Быстрый предел облачного запуска без чтения содержимого файла."""
    if command.parser_mode != ParserMode.CLOUD:
        return None
    page_selection = page_model(session)
    page_price = _price(session, page_selection)
    image_price = (
        _price(session, description_model(session, command))
        if image_mode == "describe" else page_price
    )
    price_known = page_price is not None and image_price is not None
    if not price_known and not command.confirm_unknown_price:
        raise ProjectConflictError(
            "Цена модели неизвестна: подтвердите запуск без оценки стоимости",
            code="ai_price_unknown",
            context={"model_id": page_selection.model_id if page_selection else None},
        )
    max_calls = pages * QUICK_CALLS_PER_PAGE + CALLS_SLACK
    max_cost = command.max_cost_usd
    if max_cost is None and price_known:
        # Предел без оценки намеренно широкий: реальные вызовы резервируют свой
        # собственный максимум, а общий потолок защищает от бесконечного расхода.
        max_cost = QUICK_MAX_COST_USD
    if max_cost is not None:
        max_cost = max(max_cost, MIN_BUDGET_USD)
    return budget_state(
        max_cost_usd=max_cost,
        max_calls=max_calls,
        allow_unknown_price=command.confirm_unknown_price,
    )
