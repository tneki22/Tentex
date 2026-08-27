"""Однопоточный локальный HTTP-адаптер PaddleOCR для режима «Учебник»."""

from __future__ import annotations

import base64
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

log = logging.getLogger("tentex.textbook_ocr")
app = FastAPI(title="Tentex textbook OCR", docs_url=None, redoc_url=None)

MODEL_NAME = "PP-StructureV3 + PP-FormulaNet Plus M"
LAYOUT_MODEL = "PP-DocLayout_plus-L"
FORMULA_MODEL = "PP-FormulaNet_plus-M"
DEVICE = os.getenv("TENTEX_TEXTBOOK_DEVICE", "gpu")
_lock = threading.Lock()
_pipeline: Any = None
_executor: str | None = None
_reason = "Модель ещё загружается."


class ParseRequest(BaseModel):
    image_base64: str
    page_number: int


def _load_pipeline() -> tuple[Any, str]:
    from paddleocr import PPStructureV3

    # Модель разметки обязана выделять формулы отдельным классом, иначе
    # `use_formula_recognition` нечего передать в PP-FormulaNet и формула
    # уезжает в обычное распознавание текста «супер криво». PP-DocBlockLayout —
    # блочная модель (текст/таблица/картинка), класса «формула» у неё нет;
    # PP-DocLayout_plus-L различает 20 классов, включая формулы, и является
    # штатной моделью разметки PP-StructureV3.
    pipeline = PPStructureV3(
        device=DEVICE,
        precision="fp16",
        lang="ru",
        layout_detection_model_name=LAYOUT_MODEL,
        formula_recognition_model_name=FORMULA_MODEL,
        formula_recognition_batch_size=1,
        text_recognition_batch_size=1,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        use_seal_recognition=False,
        use_table_recognition=False,
        use_formula_recognition=True,
        use_chart_recognition=False,
        use_region_detection=False,
    )
    return pipeline, "PP-StructureV3 + PP-FormulaNet Plus M"


@app.on_event("startup")
def load_pipeline() -> None:
    global _pipeline, _executor, _reason
    try:
        _pipeline, _executor = _load_pipeline()
        _reason = ""
    except Exception as error:
        _reason = f"Не удалось загрузить {MODEL_NAME}: {error}"
        log.exception(_reason)


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if hasattr(value, "tolist"):
        return _plain(value.tolist())
    if hasattr(value, "item"):
        return value.item()
    return value


def _result_json(result: Any) -> dict[str, Any]:
    payload = getattr(result, "json", None)
    if callable(payload):
        payload = payload()
    payload = _plain(payload)
    if not isinstance(payload, dict):
        raise TypeError("PaddleOCR не вернул структурированный JSON")
    nested = payload.get("res")
    return nested if isinstance(nested, dict) else payload


def _markdown(result: Any) -> str:
    payload = getattr(result, "markdown", None)
    if callable(payload):
        payload = payload()
    if isinstance(payload, dict):
        texts = payload.get("markdown_texts") or payload.get("markdown") or ""
        if isinstance(texts, list):
            return "\n\n".join(str(item) for item in texts)
        return str(texts)
    return str(payload or "")


def _bbox_iou(left: Any, right: Any) -> float:
    if not (
        isinstance(left, list)
        and isinstance(right, list)
        and len(left) == 4
        and len(right) == 4
    ):
        return 0.0
    try:
        left_box = [float(value) for value in left]
        right_box = [float(value) for value in right]
    except (TypeError, ValueError):
        return 0.0
    intersection_width = max(
        0.0, min(left_box[2], right_box[2]) - max(left_box[0], right_box[0])
    )
    intersection_height = max(
        0.0, min(left_box[3], right_box[3]) - max(left_box[1], right_box[1])
    )
    intersection = intersection_width * intersection_height
    left_area = max(0.0, left_box[2] - left_box[0]) * max(
        0.0, left_box[3] - left_box[1]
    )
    right_area = max(0.0, right_box[2] - right_box[0]) * max(
        0.0, right_box[3] - right_box[1]
    )
    union = left_area + right_area - intersection
    return intersection / union if union > 0 else 0.0


def _layout_score(label: str, bbox: Any, boxes: Any) -> Any:
    best_overlap = 0.0
    best_score = None
    for item in boxes if isinstance(boxes, list) else []:
        if not isinstance(item, dict) or str(item.get("label") or "") != label:
            continue
        overlap = _bbox_iou(bbox, _plain(item.get("coordinate")))
        if overlap > best_overlap:
            best_overlap = overlap
            best_score = item.get("score")
    return best_score if best_overlap >= 0.8 else None


def _elements(payload: dict[str, Any]) -> list[dict[str, Any]]:
    parsing = payload.get("parsing_res_list") or []
    layout = payload.get("layout_det_res") or {}
    boxes = layout.get("boxes") if isinstance(layout, dict) else []
    result: list[dict[str, Any]] = []
    for block in parsing if isinstance(parsing, list) else []:
        if not isinstance(block, dict):
            continue
        bbox = _plain(block.get("block_bbox") or block.get("coordinate") or [0, 0, 1, 1])
        label = str(block.get("block_label") or block.get("label") or "text")
        score = _layout_score(label, bbox, boxes)
        result.append(
            {
                "label": label,
                "content": str(block.get("block_content") or ""),
                "bbox": bbox,
                "confidence": float(score) if score is not None else None,
                "order": block.get("block_order"),
            }
        )
    return result


def _predict(path: Path) -> dict[str, Any]:
    if _pipeline is None:
        raise RuntimeError(_reason)
    result = next(iter(_pipeline.predict(str(path))))
    payload = _result_json(result)
    elements = _elements(payload)
    markdown = _markdown(result)
    if not markdown.strip():
        markdown = "\n\n".join(item["content"] for item in elements if item["content"])
    return {
        "width": int(payload.get("width") or 1),
        "height": int(payload.get("height") or 1),
        "markdown": markdown,
        "elements": elements,
        "diagnostics": [f"textbook_executor:{_executor}"],
    }


def _gpu() -> dict[str, Any] | None:
    """Характеристики видеокарты для экрана настроек Tentex.

    Этот процесс — единственный, кто видит GPU напрямую: контейнер API запущен
    без доступа к драйверу и сам определить её не может.
    """
    global _gpu_cache
    if _gpu_cache is not None:
        return _gpu_cache or None
    import shutil
    import subprocess

    _gpu_cache = {}
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    line = next((item for item in result.stdout.splitlines() if item.strip()), "")
    parts = [item.strip() for item in line.split(",")]
    if len(parts) < 2:
        return None
    _gpu_cache = {
        "name": parts[0],
        "vram_mb": int(parts[1]) if parts[1].isdigit() else None,
        "driver": parts[2] if len(parts) > 2 else None,
    }
    return _gpu_cache


_gpu_cache: dict[str, Any] | None = None


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ready": _pipeline is not None,
        "model": MODEL_NAME,
        "layout_model": LAYOUT_MODEL,
        "formula_model": FORMULA_MODEL,
        "executor": _executor,
        "label": _executor or "",
        "reason": _reason,
        "concurrency": 1,
        "precision": "fp16",
        "gpu": _gpu(),
    }


@app.post("/parse")
def parse(command: ParseRequest) -> dict[str, Any]:
    if _pipeline is None:
        raise HTTPException(status_code=503, detail=_reason)
    try:
        image = base64.b64decode(command.image_base64, validate=True)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Некорректное изображение") from error
    with _lock:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temporary:
            temporary.write(image)
            path = Path(temporary.name)
        try:
            return _predict(path)
        except Exception as error:
            log.exception("Page %s failed", command.page_number)
            raise HTTPException(status_code=500, detail=str(error)) from error
        finally:
            path.unlink(missing_ok=True)
