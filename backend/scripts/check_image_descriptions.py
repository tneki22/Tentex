"""Проверка конвейера изображений на закреплённом наборе страниц.

Шаги, как в плане `docs/superpowers/plans/2026-09-26-image-recognition-and-descriptions.md`:

    offline  — бесплатно и без сети: маршрут страниц, кандидаты и число будущих
               вызовов в каждой стратегии; сверка с `expect` из manifest.
    prepare  — изолированная копия данных: снимок SQLite, ключ установки,
               миграции и модели оценки в каталоге копии (провайдер закреплён,
               рассуждение низкое, у автовыбора — потолок цены).
    run      — одна модель на копии. Сначала верхняя оценка по тем же счётчикам;
               вызовы идут только с `--execute` и под жёстким пределом суммы и
               числа вызовов, который резервируется до сети. Варианты —
               `--param` поверх каталога, `--raster-scale`, `--concurrency`.
    compare  — отчёты рядом: деньги, время по видам вызовов, сбои и сходство
               страниц бенчмарка с эталоном `tentex-ocr-bench/ground_truth`.

Примеры (из `backend/`):

    python scripts/check_image_descriptions.py offline
    python scripts/check_image_descriptions.py prepare --out ../../tentex-eval-data \\
        --enable-external
    python scripts/check_image_descriptions.py run --data-dir ../../tentex-eval-data \\
        --model qwen/qwen3.8-flash --cases clean-p2,synthetic-repeated-logo \\
        --max-usd 0.10 --max-calls 12 --execute
    python scripts/check_image_descriptions.py run --data-dir ../../tentex-eval-data \\
        --model openai/gpt-6-luna --set dev --max-usd 0.10 --max-calls 40 --execute \\
        --tag flex --param reasoning_effort=off \\
        --param 'provider={"order":["openai/flex","openai"],"allow_fallbacks":true}'
    python scripts/check_image_descriptions.py compare a.json b.json --out cmp.md

Реальная папка `data/` для `run` запрещена: платный прогон пишет ревизии,
вырезы и журнал вызовов только в копию.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND.parent


def _main_checkout() -> Path:
    """Корень основной рабочей копии: у worktree своя пустая `data/`, а база — там."""
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return PROJECT_ROOT
    return Path(common).parent


REAL_DATA = _main_checkout() / "data"
# Папки, в которые платный прогон писать не может: реальные данные и `data/` worktree.
FORBIDDEN_DATA = {REAL_DATA.resolve(), (PROJECT_ROOT / "data").resolve()}
MANIFEST = Path(__file__).with_name("image_eval_manifest.json")
STRATEGIES = ("economy", "auto", "page")

# Модели оценки. Цены OpenRouter сверены 26.09.2026 (USD за токен); `params`
# уходят в тело запроса через `default_parameters` каталога копии.
EVAL_MODELS: dict[str, dict[str, Any]] = {
    "qwen/qwen3.8-flash": {
        "prices": ("0.00000015", "0.00000047"),
        "params": {
            "provider": {"order": ["alibaba"], "allow_fallbacks": False},
            "reasoning_effort": "off",
        },
    },
    "qwen/qwen3-vl-30b-a3b-instruct": {
        # Самый дешёвый эндпоинт — Alibaba; DeepInfra $0.15/$0.60 — запасной.
        "prices": ("0.00000015", "0.0000006"),
        "params": {"provider": {"max_price": {"prompt": 0.15, "completion": 0.6}}},
    },
    "openai/gpt-6-luna": {
        # У модели несколько тарифов одного провайдера ($0.05…$0.20 вход):
        # потолок держит запрос на стандартном, а не на приоритетном.
        "prices": ("0.0000001", "0.0000005"),
        "params": {
            "provider": {"max_price": {"prompt": 0.1, "completion": 0.5}},
            "reasoning_effort": "low",
        },
    },
    "google/gemini-3.8-flash": {
        # Дорогой контроль: только для провалов дешёвых моделей и в конце.
        "prices": ("0.00000075", "0.00000375"),
        "params": {
            "provider": {"max_price": {"prompt": 0.75, "completion": 3.75}},
            "reasoning_effort": "low",
        },
    },
    "openrouter/auto": {
        # Цена автовыбора неизвестна заранее: в каталог копии пишется потолок —
        # самая дорогая из разрешённых моделей, — и по нему резервируется предел.
        "prices": ("0.00000015", "0.0000006"),
        "params": {
            "plugins": [
                {
                    "id": "auto-router",
                    "cost_tier": "low",
                    "allowed_models": [
                        "qwen/qwen3.8-flash",
                        "qwen/qwen3-vl-30b-a3b-instruct",
                        "openai/gpt-6-luna",
                    ],
                }
            ],
            "provider": {"max_price": {"prompt": 0.15, "completion": 0.6}},
        },
    },
}

# Сколько токенов уходит в один вызов каждого вида — для верхней оценки.
PAGE_INPUT_TOKENS = 1850
REGION_INPUT_TOKENS = 700
IMAGE_INPUT_TOKENS = 1600
PAGE_MAX_OUTPUT = 8000
IMAGE_MAX_OUTPUT = 3000


def _use_data_dir(path: Path) -> None:
    """Переключить приложение на папку данных до первого импорта `app`."""
    if "app.config" in sys.modules:
        raise RuntimeError("папку данных нужно выбрать до импорта app")
    os.environ["TENTEX_DATA_DIR"] = str(path)
    os.environ.setdefault("TENTEX_SEED_DEMO_PROJECT", "false")
    sys.path.insert(0, str(BACKEND))


def _refuse_real_data(path: Path) -> None:
    if path.resolve() in FORBIDDEN_DATA:
        raise SystemExit("Отказ: платный прогон и копия не могут жить в реальной папке data/")


# ── Набор ────────────────────────────────────────────────────────────────────


def _load_cases(names: str | None, case_set: str | None) -> list[dict[str, Any]]:
    cases = json.loads(MANIFEST.read_text(encoding="utf-8"))["cases"]
    if names:
        wanted = {name.strip() for name in names.split(",") if name.strip()}
        unknown = wanted - {case["id"] for case in cases}
        if unknown:
            raise SystemExit(f"Нет в manifest: {', '.join(sorted(unknown))}")
        cases = [case for case in cases if case["id"] in wanted]
    if case_set:
        cases = [case for case in cases if case["set"] == case_set]
    return cases


def _png(size: tuple[int, int], seed: int) -> bytes:
    from io import BytesIO

    from PIL import Image, ImageDraw

    image = Image.new("RGB", size, color="white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((4, 4, size[0] - 4, size[1] - 4), outline="black", width=3)
    for step in range(0, size[0], max(8, size[0] // 6)):
        draw.line((step, seed % size[1], size[0] - step, size[1] - 1), fill="black", width=2)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


PROSE = (
    "Сетевой уровень отвечает за доставку пакетов между узлами разных сетей. "
    "Маршрутизатор выбирает путь по таблице маршрутизации и метрике. "
) * 6


def _synthetic(kind: str, folder: Path) -> Path:
    """Детерминированные PDF для случаев, которых нет в бенчмарке (один раз за прогон)."""
    import pymupdf as fitz

    path = folder / f"{kind}.pdf"
    if path.exists():
        return path
    document = fitz.open()
    if kind == "repeated-logo":
        logo, diagram = _png((120, 40), 1), _png((500, 300), 2)
        for number in range(3):
            page = document.new_page(width=595, height=842)
            page.insert_image(fitz.Rect(40, 20, 160, 60), stream=logo)
            page.insert_textbox(fitz.Rect(60, 90, 540, 400), PROSE, fontsize=11)
            if number == 1:
                page.insert_image(fitz.Rect(80, 450, 520, 720), stream=diagram)
    elif kind == "partial-layer":
        page = document.new_page(width=595, height=842)
        page.insert_image(page.rect, stream=_png((600, 840), 3))
        page.insert_text((60, 820), "Страница 12. Глава 3, раздел о маршрутизации", fontsize=9)
    elif kind == "mojibake":
        page = document.new_page(width=595, height=842)
        text = PROSE.encode("cp1251").decode("latin-1")
        page.insert_textbox(fitz.Rect(60, 60, 540, 800), text, fontsize=11)
    elif kind == "small-legend":
        page = document.new_page(width=595, height=842)
        page.insert_textbox(fitz.Rect(60, 60, 540, 380), PROSE, fontsize=11)
        page.insert_image(fitz.Rect(250, 420, 330, 460), stream=_png((160, 80), 4))
        page.insert_text((250, 478), "Рис. 1. Легенда условных обозначений", fontsize=10)
        page.insert_image(fitz.Rect(520, 790, 528, 798), stream=_png((12, 12), 5))
    else:
        raise SystemExit(f"Неизвестная синтетика: {kind}")
    document.save(path)
    document.close()
    return path


def _source(case: dict[str, Any], folder: Path) -> Path:
    source = str(case["source"])
    if source.startswith("synthetic:"):
        return _synthetic(source.split(":", 1)[1], folder)
    path = PROJECT_ROOT / source
    if not path.exists():
        raise SystemExit(f"{case['id']}: нет файла {path}")
    return path


# ── Счётчик вызовов без сети ─────────────────────────────────────────────────


@dataclass
class CountingRecognizer:
    """Порт распознавания без сети: считает, что ушло бы наружу."""

    pages: int = 0
    regions: int = 0
    region_requests: int = 0
    described: int = 0
    # Счётчик по одному вызову на страницу: чтение наперёд ему ни к чему.
    concurrency: int = 1

    def prefetch_pages(self, pages: Sequence[Any]) -> None:
        del pages

    def recognize_page(self, image: bytes, page_number: int, width: float, height: float):
        from app.materials.parsers.base import ParsedElement, ParsedPage

        del image
        self.pages += 1
        element = ParsedElement("paragraph", "(ответ модели страницы)", (0.1, 0.1, 0.9, 0.2))
        return ParsedPage(page_number, width, height, element.text, element.text, "ocr",
                          (element,), (), 0.9)

    def recognize_regions(self, regions: Sequence[Any], page_number: int):
        from app.materials.parsers.base import RecognizedRegion
        from app.materials.parsers.cloud_vlm import MAX_REGIONS_PER_REQUEST

        del page_number
        self.regions += len(regions)
        self.region_requests += -(-len(regions) // MAX_REGIONS_PER_REQUEST)
        return [RecognizedRegion(region.index, region.kind, "", 0.0) for region in regions]

    def describe_images(self, images: Sequence[Any]):
        self.described += len({image.crop_hash for image in images})
        return []


def _image_summary(pages: Sequence[Any]) -> dict[str, Any]:
    from app.materials.image_meta import element_meta

    roles: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    routes: list[str] = []
    for page in pages:
        routes.extend(item for item in page.diagnostics if item.startswith("route"))
        for element in page.elements:
            meta = element_meta(element)
            if meta is None:
                continue
            roles[meta.role] += 1
            reasons.update(meta.reasons)
    return {"roles": dict(roles), "reasons": dict(reasons), "routes": routes}


def _count(case: dict[str, Any], strategy: str, folder: Path) -> dict[str, Any]:
    from app.materials.parsers.native import iter_pages
    from app.models import ParserMode
    from app.ocr.engines import OcrRuntimeParams

    counter = CountingRecognizer()
    params = OcrRuntimeParams(cloud_strategy=strategy, image_mode="describe")  # type: ignore[arg-type]
    pages = list(
        iter_pages(_source(case, folder), ParserMode.CLOUD, params=params,
                   page_numbers=case["pages"], recognizer=counter)
    )
    return {
        "page_calls": counter.pages,
        "region_calls": counter.region_requests,
        "region_crops": counter.regions,
        "describe": counter.described,
        "quality": [page.quality for page in pages],
        **_image_summary(pages),
    }


def _check(expect: dict[str, Any], observed: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if "page_calls" in expect and observed["page_calls"] != expect["page_calls"]:
        problems.append(f"страниц {observed['page_calls']} вместо {expect['page_calls']}")
    if "describe" in expect:
        low, high = expect["describe"]
        if not low <= observed["describe"] <= high:
            problems.append(f"описаний {observed['describe']} вне {low}…{high}")
    return problems


def offline(args: argparse.Namespace) -> int:
    folder = Path(tempfile.mkdtemp(prefix="tentex-image-eval-"))
    _use_data_dir(folder)
    failures = 0
    report: list[dict[str, Any]] = []
    for case in _load_cases(args.cases, args.set):
        for strategy in args.strategies.split(","):
            observed = _count(case, strategy, folder)
            problems = _check(case.get("expect", {}).get(strategy, {}), observed)
            failures += bool(problems)
            report.append({"case": case["id"], "strategy": strategy, **observed,
                           "problems": problems})
            mark = "FAIL" if problems else "ok"
            print(
                f"{mark:4} {case['id']:26} {strategy:8} страниц={observed['page_calls']} "
                f"вырезов={observed['region_crops']}/{observed['region_calls']} запр. "
                f"описаний={observed['describe']} "
                f"роли={observed['roles']} {'; '.join(problems)}"
            )
    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    shutil.rmtree(folder, ignore_errors=True)
    print(f"\nИтого: {len(report)} проверок, провалов {failures}")
    return 1 if failures else 0


# ── Изолированная копия ──────────────────────────────────────────────────────


def prepare(args: argparse.Namespace) -> int:
    out = Path(args.out).resolve()
    _refuse_real_data(out)
    source = Path(args.source).resolve()
    out.mkdir(parents=True, exist_ok=True)
    target = out / "tentex.sqlite"
    if target.exists() and not args.force:
        raise SystemExit(f"{target} уже есть; --force перезапишет копию")
    original = source / "tentex.sqlite"
    if not original.is_file() or original.stat().st_size == 0:
        raise SystemExit(f"Нет базы {original} — укажите --source с настоящей папкой данных")
    # Резервная копия SQLite API, а не копирование файла: живая база в WAL
    # иначе дала бы несогласованный снимок. `mode=ro` — источник не создаётся
    # и не меняется, даже если путь указан неверно.
    with (sqlite3.connect(f"{original.as_uri()}?mode=ro", uri=True) as src,
          sqlite3.connect(target) as dst):
        src.backup(dst)
    secret = source / "installation.secret"
    if secret.exists():
        shutil.copy2(secret, out / "installation.secret")
    _use_data_dir(out)

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.db import engine, upgrade_database
    from app.models import AiModelCatalogEntry, AiProviderConnection, AiSettings, utc_now

    upgrade_database()
    with Session(engine) as session:
        provider = session.scalar(
            select(AiProviderConnection).where(AiProviderConnection.catalog_profile == "openrouter")
        )
        if provider is None:
            raise SystemExit("В копии нет подключения OpenRouter — добавьте его в Параметрах ИИ")
        now = utc_now()
        for model_id, spec in EVAL_MODELS.items():
            row = session.get(AiModelCatalogEntry, (provider.id, model_id))
            if row is None:
                row = AiModelCatalogEntry(provider_id=provider.id, model_id=model_id,
                                          display_name=model_id, catalog_snapshot_at=now)
                session.add(row)
            prompt, completion = spec["prices"]
            row.context_length = row.context_length or 128_000
            row.max_completion_tokens = row.max_completion_tokens or 16_000
            row.supported_parameters = sorted(
                {*(row.supported_parameters or []), "response_format", "structured_outputs"}
            )
            row.input_modalities = sorted({*(row.input_modalities or []), "text", "image"})
            row.output_modalities = row.output_modalities or ["text"]
            row.prompt_price_usd = Decimal(prompt)
            row.completion_price_usd = Decimal(completion)
            row.pricing_snapshot_at = now
            row.default_parameters = spec["params"]
            row.is_manually_added = True
            row.is_available = True
        settings_row = session.get(AiSettings, 1)
        if args.enable_external and settings_row is not None:
            # Только в копии: реальная установка остаётся с тем выбором, что был.
            settings_row.external_models_enabled = True
        enabled = bool(settings_row and settings_row.external_models_enabled)
        label = provider.label
        session.commit()
    print(f"Копия готова: {out}")
    print(f"Модели оценки в каталоге провайдера «{label}»: {', '.join(EVAL_MODELS)}")
    if not enabled:
        print("Внимание: внешние модели в копии выключены — повторите prepare с --enable-external")
    return 0


# ── Платный прогон ───────────────────────────────────────────────────────────


@dataclass
class HardBudget:
    """Предел прогона в памяти: резерв до сети, расход по `usage`."""

    max_usd: Decimal
    max_calls: int
    calls: int = 0
    spent: Decimal = Decimal(0)
    open: dict[str, Decimal] = field(default_factory=dict)

    def reserve(self, tokens: int, cost: Decimal | None) -> str:
        from app.projects.errors import ProjectConflictError

        del tokens
        if cost is None:
            raise ProjectConflictError("Цена неизвестна", code="run_budget_unknown_price")
        committed = self.spent + sum(self.open.values())
        if self.calls >= self.max_calls or committed + cost > self.max_usd:
            raise ProjectConflictError("Предел прогона исчерпан", code="run_budget_exhausted")
        self.calls += 1
        receipt = f"r{self.calls}"
        self.open[receipt] = cost
        return receipt

    def settle(self, receipt_id: str, usage: Any) -> None:
        reserved = self.open.pop(receipt_id, Decimal(0))
        actual = getattr(usage, "cost_usd", None) if usage is not None else None
        self.spent += actual if actual is not None else reserved


def _upper(counts: dict[str, int], prompt: Decimal, completion: Decimal) -> Decimal:
    return (
        counts["page_calls"] * (prompt * PAGE_INPUT_TOKENS + completion * PAGE_MAX_OUTPUT)
        + counts["region_crops"] * prompt * REGION_INPUT_TOKENS
        + counts["region_calls"] * completion * PAGE_MAX_OUTPUT
        + counts["describe"] * (prompt * IMAGE_INPUT_TOKENS + completion * IMAGE_MAX_OUTPUT)
    )


def _element_report(element: Any) -> dict[str, Any]:
    from app.materials.image_meta import description_to_json, element_meta

    meta = element_meta(element)
    item: dict[str, Any] = {"kind": element.kind, "text": element.text[:600],
                            "bbox": [round(value, 3) for value in element.bbox],
                            "asset": element.asset_path, "confidence": element.confidence}
    if meta is not None:
        item |= {"role": meta.role, "processing": meta.processing, "review": meta.review,
                 "reasons": list(meta.reasons), "caption": meta.caption,
                 "description": description_to_json(meta.description)
                 if meta.description else None}
    return item


def _override_parameters(items: Sequence[str]) -> None:
    """Параметры запроса поверх каталога копии — только в этом процессе.

    Вариант (рассуждение, тариф провайдера) меняет и хеш запроса, так что кэш
    одного варианта другому ответ не отдаст.
    """
    from app.ai.gateway import ModelGateway

    overrides: dict[str, Any] = {}
    for item in items:
        key, _, raw = item.partition("=")
        try:
            overrides[key] = json.loads(raw)
        except json.JSONDecodeError:
            overrides[key] = raw
    original = ModelGateway._parameters

    def patched(resolved: Any, request_parameters: dict[str, object]) -> dict[str, object]:
        return original(resolved, request_parameters) | overrides

    ModelGateway._parameters = staticmethod(patched)  # type: ignore[method-assign]


def _track_runs() -> set[Any]:
    """ID записей журнала, заведённых этим процессом (в том числе из кэша)."""
    from app.ai.gateway import ModelGateway

    seen: set[Any] = set()
    start, cached = ModelGateway._start_run, ModelGateway._cached_result

    def start_run(self: Any, *args: Any, **kwargs: Any) -> Any:
        run = start(self, *args, **kwargs)
        seen.add(run.id)
        return run

    def cached_result(self: Any, *args: Any, **kwargs: Any) -> Any:
        result = cached(self, *args, **kwargs)
        seen.add(result.run_id)
        return result

    ModelGateway._start_run = start_run  # type: ignore[method-assign]
    ModelGateway._cached_result = cached_result  # type: ignore[method-assign]
    return seen


def _call_kind(run: Any) -> str:
    """Вид вызова по роли и форме ответа: страница, пачка вырезов или описание."""
    if run.role == "material_image_description":
        return "describe"
    payload = run.response_payload or {}
    if "regions" in payload:
        return "regions"
    if "elements" in payload:
        return "page"
    return "page?"


def _call_report(runs: Sequence[Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Каждый вызов из журнала и сводка по видам: время, токены, деньги, сбои."""
    calls: list[dict[str, Any]] = []
    summary: dict[str, dict[str, Any]] = {}
    for item in sorted(runs, key=lambda row: row.created_at):
        kind = _call_kind(item)
        cost = item.actual_cost_usd or Decimal(0)
        calls.append({
            "kind": kind, "status": item.status, "error": item.error_code,
            "model": item.actual_model_id, "ms": item.duration_ms,
            "in": item.input_tokens, "out": item.output_tokens,
            "reasoning": item.reasoning_tokens, "usd": str(cost),
            # Кэш провайдера (OpenAI, Alibaba) по повторному префиксу: повтор тех же
            # страниц в течение часа стоит дешевле, и цена такого прогона занижена.
            "provider_cached_in": item.provider_cached_tokens or 0,
            "cached": item.cached_from_run_id is not None,
        })
        bucket = summary.setdefault(kind, {"calls": 0, "failed": 0, "cached": 0, "usd": Decimal(0),
                                           "in": 0, "out": 0, "reasoning": 0,
                                           "provider_cached_in": 0, "ms": []})
        bucket["calls"] += 1
        bucket["failed"] += item.status not in {"succeeded", "cached"}
        bucket["cached"] += item.cached_from_run_id is not None
        bucket["usd"] += cost
        bucket["in"] += item.input_tokens or 0
        bucket["out"] += item.output_tokens or 0
        bucket["reasoning"] += item.reasoning_tokens or 0
        bucket["provider_cached_in"] += item.provider_cached_tokens or 0
        if item.duration_ms and item.cached_from_run_id is None:
            bucket["ms"].append(item.duration_ms)
    for bucket in summary.values():
        durations = sorted(bucket.pop("ms"))
        bucket["usd"] = str(bucket["usd"])
        bucket["ms_median"] = durations[len(durations) // 2] if durations else None
        bucket["ms_max"] = durations[-1] if durations else None
    return calls, summary


def run(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir).resolve()
    _refuse_real_data(data_dir)
    if not (data_dir / "tentex.sqlite").exists():
        raise SystemExit("Нет копии: сначала prepare")
    _use_data_dir(data_dir)

    from sqlalchemy import delete, select
    from sqlalchemy.orm import Session

    from app.ai.schemas import AiModelSelection
    from app.db import engine
    from app.materials.parsers.cloud_vlm import CloudRecognizer
    from app.materials.parsers.native import iter_pages
    from app.models import (
        AiCacheEntry,
        AiModelCatalogEntry,
        AiProviderConnection,
        AiRun,
        ParserMode,
        utc_now,
    )
    from app.ocr.engines import OcrRuntimeParams

    cases = _load_cases(args.cases, args.set)
    folder = data_dir / "eval-sources"
    folder.mkdir(exist_ok=True)
    planned = Counter()
    for case in cases:
        counts = _count(case, args.strategy, folder)
        planned.update(
            {key: counts[key] for key in ("page_calls", "region_calls", "region_crops", "describe")}
        )

    with Session(engine, expire_on_commit=False) as session:
        row = session.scalar(
            select(AiModelCatalogEntry)
            .join(AiProviderConnection, AiProviderConnection.id == AiModelCatalogEntry.provider_id)
            .where(AiModelCatalogEntry.model_id == args.model,
                   AiProviderConnection.catalog_profile == "openrouter")
        )
        if row is None or row.prompt_price_usd is None or row.completion_price_usd is None:
            raise SystemExit(f"{args.model}: нет в каталоге копии или без цены — prepare")
        upper = _upper(planned, row.prompt_price_usd, row.completion_price_usd)
        calls = planned["page_calls"] + planned["region_calls"] + planned["describe"]
        max_usd = Decimal(str(args.max_usd))
        print(f"План {args.model} · {args.strategy}: страниц {planned['page_calls']}, "
              f"вырезов {planned['region_crops']} в {planned['region_calls']} запр., "
              f"описаний {planned['describe']} "
              f"(описания сканов зависят от ответа модели — их ограничивает предел)")
        print(f"Верхняя оценка ${upper:.4f}; предел ${max_usd} и {args.max_calls} вызовов")
        if upper > max_usd or calls > args.max_calls:
            print("Отказ: оценка выше предела — сократите набор или поднимите предел явно")
            return 2
        if not args.execute:
            print("Сухой прогон: вызовов не было. Для запуска добавьте --execute")
            return 0

        selection = AiModelSelection(provider_id=row.provider_id, model_id=row.model_id)
        budget = HardBudget(max_usd=max_usd, max_calls=args.max_calls)
        if args.fresh:
            # Кэш по содержимому отдал бы повтор бесплатно и без времени ответа;
            # для замера скорости и стабильности он мешает.
            own = select(AiRun.id).where(AiRun.requested_model_id == args.model)
            session.execute(delete(AiCacheEntry).where(AiCacheEntry.source_run_id.in_(own)))
            session.commit()
        started = utc_now()
        session.rollback()
        if args.param:
            _override_parameters(args.param)
        own_runs = _track_runs()
        recognizer = CloudRecognizer(session, page_model=selection, description_model=selection,
                                     budget=budget, retry_backoff=(3.0,),
                                     concurrency=args.concurrency)
        results: list[dict[str, Any]] = []
        try:
            params = OcrRuntimeParams(cloud_strategy=args.strategy, image_mode="describe",  # type: ignore[arg-type]
                                      **({"raster_scale": args.raster_scale}
                                         if args.raster_scale else {}))
            for case in cases:
                clock = time.monotonic()
                pages = list(iter_pages(_source(case, folder), ParserMode.CLOUD, params=params,
                                        page_numbers=case["pages"], recognizer=recognizer))
                seconds = round(time.monotonic() - clock, 1)
                results.append({
                    "case": case["id"],
                    "why": case.get("why"),
                    "seconds": seconds,
                    "pages": [
                        {"page": page.page_number, "quality": page.quality,
                         "confidence": page.confidence,
                         "diagnostics": list(page.diagnostics),
                         "markdown": page.markdown[:6000],
                         "elements": [_element_report(item) for item in page.elements
                                      if item.kind in {"image", "formula", "table"}]}
                        for page in pages
                    ],
                })
                print(f"{case['id']}: {seconds} с, ${budget.spent:.4f}, вызовов {budget.calls}")
        finally:
            recognizer.close()
        session.rollback()
        # Только свои вызовы: параллельные прогоны на одной копии не смешиваются,
        # даже если у них одна модель.
        mine = select(AiRun).where(AiRun.id.in_(own_runs))
        runs = list(session.scalars(mine)) if own_runs else []
    calls, by_kind = _call_report(runs)
    cost = sum((Decimal(item["usd"]) for item in calls), Decimal(0))
    report = {
        "model": args.model,
        "tag": args.tag,
        "strategy": args.strategy,
        "variant": {"param": args.param, "raster_scale": args.raster_scale,
                    "concurrency": args.concurrency},
        "started_at": started.isoformat(),
        "seconds": round(sum(case["seconds"] for case in results), 1),
        "budget": {"max_usd": str(max_usd), "spent_usd": str(budget.spent), "calls": budget.calls},
        "ai_runs": {
            "count": len(runs),
            "cost_usd": str(cost),
            "cached": sum(item.cached_from_run_id is not None for item in runs),
            "statuses": dict(Counter(item.status for item in runs)),
            "actual_models": dict(Counter(item.actual_model_id or "?" for item in runs)),
            "by_kind": by_kind,
        },
        "calls": calls,
        "cases": results,
    }
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    name = args.model.replace("/", "_") + (f"-{args.tag}" if args.tag else "")
    out = Path(args.report) if args.report else data_dir / f"image-eval-{name}-{stamp}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Отчёт: {out}\nВызовов по журналу: {len(runs)}, стоимость ${cost:.5f}, "
          f"время {report['seconds']} с")
    for kind, bucket in by_kind.items():
        print(f"  {kind:9} вызовов {bucket['calls']} (сбоев {bucket['failed']}, "
              f"кэш {bucket['cached']}) ${Decimal(bucket['usd']):.5f} "
              f"токены {bucket['in']}/{bucket['out']} (рассужд. {bucket['reasoning']}, "
              f"из кэша провайдера {bucket['provider_cached_in']}) "
              f"медиана {bucket['ms_median']} мс, максимум {bucket['ms_max']} мс")
    return 0


GROUND_TRUTH = PROJECT_ROOT / "tentex-ocr-bench" / "ground_truth"
# Исходники бенчмарка, у которых страница N описана эталоном `page_NN.md`:
# чистый мастер — это те же страницы 1–10 без скана.
BENCH_SOURCES = (
    "tentex-ocr-bench/tentex_ocr_bench_v2_24p.pdf",
    "tentex-ocr-bench/clean_master.pdf",
)
FORMULA_RE = re.compile(r"\$\$(.+?)\$\$|\$(.+?)\$", re.S)
TEX_NOISE_RE = re.compile(r"\\[,;:! ]|\\(?:left|right|displaystyle)|\\tag\{[^}]*\}|\s+")


def _plain(markdown: str) -> str:
    """Текст страницы без разметки: для сравнения с эталоном по символам."""
    markdown = re.sub(r"\A---\n.*?\n---\n", "", markdown, flags=re.S)
    markdown = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", markdown)
    markdown = re.sub(r"^\s*\|?\s*:?-{3,}.*$", " ", markdown, flags=re.M)
    markdown = re.sub(r"[#*_>|$`]", " ", markdown)
    return re.sub(r"\s+", " ", markdown).strip()


def _formulas(markdown: str) -> set[str]:
    """Формулы страницы без пробелов, отступов и точки или запятой в конце.

    Знак препинания после выносной формулы эталон ставит внутрь `$$`, а модель
    — то внутрь, то после; на смысл формулы это не влияет.
    """
    return {
        TEX_NOISE_RE.sub("", display or inline).rstrip(".,;:")
        for display, inline in FORMULA_RE.findall(markdown)
        if (display or inline).strip()
    }


def _score(case: dict[str, Any], page: dict[str, Any]) -> dict[str, float] | None:
    """Сходство текста страницы с эталоном и доля эталонных формул, найденных дословно."""
    from difflib import SequenceMatcher

    source = next((item for item in BENCH_SOURCES if case.get("source") == item), None)
    truth_path = GROUND_TRUTH / f"page_{int(page['page']):02d}.md"
    if source is None or not truth_path.exists() or not page.get("markdown"):
        return None
    truth = truth_path.read_text(encoding="utf-8")
    text = SequenceMatcher(None, _plain(truth), _plain(page["markdown"]), autojunk=False).ratio()
    expected = _formulas(truth)
    found = _formulas(page["markdown"])
    formulas = len(expected & found) / len(expected) if expected else 1.0
    return {"text": round(text, 3), "formulas": round(formulas, 3)}


def compare(args: argparse.Namespace) -> int:
    """Отчёты нескольких прогонов рядом: деньги, время, сбои и ответы по случаям."""
    reports = [json.loads(Path(item).read_text(encoding="utf-8")) for item in args.reports]
    names = [f"{item['model']}{'·' + item['tag'] if item.get('tag') else ''}" for item in reports]
    sources = {case["id"]: case for case in _load_cases(None, None)}
    lines = ["# Сравнение прогонов", "",
             "| Прогон | Вызовов | Сбоев | $ | Время, с | Текст к эталону | Формулы дословно |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    scores: dict[str, dict[tuple[str, int], dict[str, float]]] = {}
    for name, item in zip(names, reports, strict=True):
        runs = item["ai_runs"]
        failed = sum(
            call["status"] not in {"succeeded", "cached"} for call in item.get("calls", [])
        )
        own = scores.setdefault(name, {})
        for case in item["cases"]:
            for page in case["pages"]:
                score = _score(sources.get(case["case"], {}), page)
                if score is not None:
                    own[(case["case"], page["page"])] = score
        mean_text = sum(row["text"] for row in own.values()) / len(own) if own else 0
        mean_formulas = sum(row["formulas"] for row in own.values()) / len(own) if own else 0
        lines.append(f"| {name} | {runs['count']} | {failed} | {Decimal(runs['cost_usd']):.5f} "
                     f"| {item.get('seconds', '?')} | {mean_text:.3f} | {mean_formulas:.3f} |")
    pages = sorted({key for own in scores.values() for key in own})
    if pages:
        lines += ["", "## Страницы с эталоном (текст / формулы)", "",
                  "| Страница | " + " | ".join(names) + " |",
                  "| --- |" + " ---: |" * len(names)]
        for key in pages:
            cells = []
            for name in names:
                score = scores[name].get(key)
                cells.append(f"{score['text']:.3f} / {score['formulas']:.2f}" if score else "—")
            lines.append(f"| {key[0]} с. {key[1]} | " + " | ".join(cells) + " |")
    lines += ["", "## По видам вызовов", "",
              "| Прогон | Вид | Вызовов | $ | Вход/выход | Медиана, мс | Максимум, мс |",
              "| --- | --- | ---: | ---: | --- | ---: | ---: |"]
    for name, item in zip(names, reports, strict=True):
        for kind, bucket in item["ai_runs"].get("by_kind", {}).items():
            lines.append(f"| {name} | {kind} | {bucket['calls']} | {Decimal(bucket['usd']):.5f} | "
                         f"{bucket['in']}/{bucket['out']} | {bucket['ms_median']} | "
                         f"{bucket['ms_max']} |")
    cases = {case["case"]: case for case in reports[0]["cases"]}
    for case_id, first in cases.items():
        lines += ["", f"## {case_id}", "", first.get("why") or ""]
        for name, item in zip(names, reports, strict=True):
            case = next((row for row in item["cases"] if row["case"] == case_id), None)
            if case is None:
                continue
            lines += ["", f"### {name} · {case.get('seconds', '?')} с"]
            for page in case["pages"]:
                lines.append(f"- стр. {page['page']}: {page['quality']}, "
                             f"уверенность {page.get('confidence')}; "
                             f"{', '.join(page['diagnostics'])}")
                for element in page["elements"]:
                    description = element.get("description") or {}
                    head = (f"  - {element['kind']} {element.get('role', '')} "
                            f"{element.get('review', '')} {','.join(element.get('reasons', []))}")
                    lines.append(head.rstrip())
                    if element["kind"] != "image":
                        lines.append(f"    `{element['text'][:300]}`")
                    elif description:
                        lines.append(f"    **{description.get('title')}** — "
                                     f"{description.get('summary')}")
                        if description.get("labels"):
                            lines.append(f"    надписи: {'; '.join(description['labels'])}")
                if args.text and page.get("markdown"):
                    lines += ["", "```text", page["markdown"][: args.text], "```"]
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Сравнение: {args.out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    offline_cmd = commands.add_parser("offline", help="бесплатная диагностика без сети")
    offline_cmd.add_argument("--cases", help="ID через запятую")
    offline_cmd.add_argument("--set", choices=("dev", "control"))
    offline_cmd.add_argument("--strategies", default="economy,auto,page")
    offline_cmd.add_argument("--report", help="куда сохранить JSON")
    offline_cmd.set_defaults(handler=offline)

    prepare_cmd = commands.add_parser("prepare", help="изолированная копия данных")
    prepare_cmd.add_argument("--out", required=True)
    prepare_cmd.add_argument("--source", default=str(REAL_DATA))
    prepare_cmd.add_argument("--force", action="store_true")
    prepare_cmd.add_argument("--enable-external", action="store_true",
                             help="включить внешние модели в копии")
    prepare_cmd.set_defaults(handler=prepare)

    run_cmd = commands.add_parser("run", help="прогон одной модели на копии")
    run_cmd.add_argument("--data-dir", required=True)
    run_cmd.add_argument("--model", required=True, choices=sorted(EVAL_MODELS))
    run_cmd.add_argument("--cases", help="ID через запятую")
    run_cmd.add_argument("--set", choices=("dev", "control"))
    run_cmd.add_argument("--strategy", default="auto", choices=STRATEGIES)
    run_cmd.add_argument("--max-usd", type=float, required=True)
    run_cmd.add_argument("--max-calls", type=int, required=True)
    run_cmd.add_argument("--execute", action="store_true", help="без флага — только оценка")
    run_cmd.add_argument("--fresh", action="store_true",
                         help="без кэша Tentex для этой модели (замер времени); кэш "
                              "префикса у провайдера живёт около часа и не чистится")
    run_cmd.add_argument("--tag", help="метка варианта в имени отчёта")
    run_cmd.add_argument("--param", action="append", default=[],
                         help='параметр запроса поверх каталога: reasoning_effort=off, '
                              'provider=\'{"order":["openai/flex"]}\'')
    run_cmd.add_argument("--raster-scale", type=float,
                         help="множитель растра страницы (2.0 — 300 dpi, 1.34 — 200 dpi)")
    run_cmd.add_argument("--concurrency", type=int, default=4,
                         help="одновременных вызовов (1 — по очереди, как раньше)")
    run_cmd.add_argument("--report", help="куда сохранить JSON")
    run_cmd.set_defaults(handler=run)

    compare_cmd = commands.add_parser("compare", help="отчёты прогонов рядом, в Markdown")
    compare_cmd.add_argument("reports", nargs="+")
    compare_cmd.add_argument("--out", required=True)
    compare_cmd.add_argument("--text", type=int, default=0,
                             help="сколько символов текста страницы показать")
    compare_cmd.set_defaults(handler=compare)

    args = parser.parse_args()
    return int(args.handler(args))


if __name__ == "__main__":
    sys.exit(main())
