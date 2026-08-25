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

MODEL_NAME = os.getenv("TENTEX_TEXTBOOK_MODEL", "PaddleOCR-VL-1.6-0.9B")
DEVICE = os.getenv("TENTEX_TEXTBOOK_DEVICE", "gpu")
EXECUTOR_MODE = os.getenv("TENTEX_TEXTBOOK_EXECUTOR", "auto")
_lock = threading.Lock()
_pipeline: Any = None
_executor: str | None = None
_reason = "Модель ещё загружается."


class ParseRequest(BaseModel):
    image_base64: str
    page_number: int


def _is_oom(error: BaseException) -> bool:
    message = str(error).lower()
    return "out of memory" in message or "resourceexhausted" in message or "cuda oom" in message


def _load_vl() -> tuple[Any, str]:
    from paddleocr import PaddleOCRVL

    pipeline = PaddleOCRVL(
        pipeline_version="v1.6",
        device=DEVICE,
        precision="fp16",
        use_queues=False,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
    )
    return pipeline, "PaddleOCR-VL-1.6-0.9B"


def _load_fallback() -> tuple[Any, str]:
    from paddleocr import PPStructureV3

    pipeline = PPStructureV3(
        device=DEVICE,
        precision="fp16",
        lang="ru",
        formula_recognition_model_name="PP-FormulaNet_plus-M",
        formula_recognition_batch_size=1,
        text_recognition_batch_size=1,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        use_chart_recognition=False,
    )
    return pipeline, "PP-StructureV3 + PP-FormulaNet Plus M"


def _activate_fallback(error: BaseException) -> None:
    global _pipeline, _executor, _reason
    log.warning("PaddleOCR-VL exceeded GPU memory; activating fallback: %s", error)
    _pipeline = None
    try:
        _pipeline, _executor = _load_fallback()
        _reason = ""
    except Exception as fallback_error:
        _reason = f"Не удалось загрузить запасной GPU-исполнитель: {fallback_error}"
        log.exception(_reason)


@app.on_event("startup")
def load_pipeline() -> None:
    global _pipeline, _executor, _reason
    try:
        _pipeline, _executor = (
            _load_fallback() if EXECUTOR_MODE == "structure" else _load_vl()
        )
        _reason = ""
    except Exception as error:
        if _is_oom(error):
            _activate_fallback(error)
        else:
            target = (
                "PP-StructureV3 + PP-FormulaNet Plus M"
                if EXECUTOR_MODE == "structure"
                else MODEL_NAME
            )
            _reason = f"Не удалось загрузить {target}: {error}"
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
        score = None
        if isinstance(boxes, list):
            matching = [
                item
                for item in boxes
                if isinstance(item, dict)
                and str(item.get("label") or "") == label
                and _plain(item.get("coordinate")) == bbox
            ]
            if matching:
                score = matching[0].get("score")
        result.append(
            {
                "label": label,
                "content": str(block.get("block_content") or ""),
                "bbox": bbox,
                "confidence": float(score) if score is not None else None,
                "order": block.get("block_order"),
            }
        )
    result.sort(key=lambda item: (item["order"] is None, item["order"] or 0))
    return result


def _predict(path: Path) -> dict[str, Any]:
    if _pipeline is None:
        raise RuntimeError(_reason)
    try:
        result = next(iter(_pipeline.predict(str(path))))
    except Exception as error:
        if _executor == "PaddleOCR-VL-1.6-0.9B" and _is_oom(error):
            _activate_fallback(error)
            if _pipeline is None:
                raise RuntimeError(_reason) from error
            result = next(iter(_pipeline.predict(str(path))))
        else:
            raise
    payload = _result_json(result)
    return {
        "width": int(payload.get("width") or 1),
        "height": int(payload.get("height") or 1),
        "markdown": _markdown(result),
        "elements": _elements(payload),
        "diagnostics": [f"textbook_executor:{_executor}"],
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ready": _pipeline is not None,
        "model": MODEL_NAME,
        "executor": _executor,
        "label": f"{_executor} · GPU" if _executor else "Локально · GPU",
        "reason": _reason,
        "concurrency": 1,
        "precision": "fp16",
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
