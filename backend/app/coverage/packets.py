"""Детерминированные пакеты первичного обзора поверх manifest прохода 2."""

import math
import re
from dataclasses import dataclass

from app.coverage.snapshots import material_units

# Рабочие значения И3: запас отделяет вход от structured output и reasoning.
# Они не являются измеренным продуктовым порогом и вынесены сюда для последующей калибровки.
FALLBACK_CONTEXT_TOKENS = 32_000
OUTPUT_RESERVE_TOKENS = 8_000
REASONING_RESERVE_TOKENS = 4_000
MAX_PACKET_INPUT_TOKENS = 16_000
MIN_PACKET_INPUT_TOKENS = 2_000
MAX_PACKET_TARGETS = 16


@dataclass(frozen=True)
class PacketSpec:
    """Один вызов обзора; повтор block ID означает следующий интервал того же блока."""

    key: str
    targets: list[str]
    checkpoint: dict


def input_token_budget(context_length: int | None, overhead_tokens: int = 0) -> int:
    """Оставляет место ответу, reasoning и постоянной части запроса.

    Постоянная часть — правила, схема ответа и всё дерево тем — уходит в модель
    с каждым пакетом. На программе в шестьсот тем она весит больше самого текста
    блоков, и без её вычета «16 000 токенов на пакет» превращались в сорок тысяч.
    """
    available = (context_length or FALLBACK_CONTEXT_TOKENS) - (
        OUTPUT_RESERVE_TOKENS + REASONING_RESERVE_TOKENS + overhead_tokens
    )
    return max(MIN_PACKET_INPUT_TOKENS, min(MAX_PACKET_INPUT_TOKENS, available))


def estimate_tokens(text: str) -> int:
    """Консервативная оценка по словам и знакам; точный tokenizer передаётся позже."""
    pieces = re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE)
    return max(1, math.ceil(len(pieces) * 1.35))


def build_packet_specs(session, rows: list[tuple], token_budget: int) -> list[PacketSpec]:
    """Группирует соседние блоки одной структурной области и режет oversized-блоки."""
    # Фрагменты берутся одним запросом на ревизию: иначе книга на 900 блоков
    # читается из SQLite 900 раз, уже после такого же обхода в manifest_rows.
    by_block: dict[str, dict] = {}
    for material_id, revision in {(block.material_id, block.revision) for block, _ in rows}:
        by_block.update(material_units(session, material_id, revision))
    prepared = [
        _prepared_block(block, manifest, by_block.get(str(block.id), {}), token_budget)
        for block, manifest in rows
    ]
    specs: list[PacketSpec] = []
    packet: list[dict] = []
    packet_tokens = 0
    packet_material = None

    def flush() -> None:
        nonlocal packet, packet_tokens
        if not packet:
            return
        specs.append(_packet_spec(len(specs), packet, prepared))
        packet, packet_tokens = [], 0

    for item in prepared:
        if len(item["intervals"]) > 1:
            flush()
            for interval in item["intervals"]:
                interval_item = {**item, "intervals": [interval]}
                specs.append(_packet_spec(len(specs), [interval_item], prepared))
            packet_material = None
            continue
        crosses_boundary = packet and item["material_id"] != packet_material
        would_overflow = packet and packet_tokens + item["tokens"] > token_budget
        reached_target_limit = len(packet) >= MAX_PACKET_TARGETS
        if crosses_boundary or would_overflow or reached_target_limit:
            flush()
        if not packet:
            packet_material = item["material_id"]
        packet.append(item)
        packet_tokens += item["tokens"]
    flush()
    return specs


def _prepared_block(block, manifest: dict, units_by_ref: dict, token_budget: int) -> dict:
    units = list(units_by_ref.values())
    intervals = _intervals(units, token_budget)
    return {
        "block_id": str(block.id),
        "material_id": str(block.material_id),
        "section_key": manifest.get("section_path") or manifest.get("title") or "Без заголовка",
        "tokens": sum(estimate_tokens(unit.text) for unit in units),
        "intervals": intervals,
        "first_ref": units[0].ref if units else None,
        "last_ref": units[-1].ref if units else None,
    }


def _intervals(units, token_budget: int) -> list[dict]:
    if not units:
        return [{"index": 0, "parts": []}]
    intervals: list[dict] = []
    current: list[dict] = []
    used = 0
    for unit in units:
        pieces = _unit_pieces(unit.ref, unit.text, token_budget)
        for piece in pieces:
            cost = estimate_tokens(unit.text[piece["start"] : piece["end"]])
            repeats_fragment = any(part["ref"] == unit.ref for part in current)
            if current and (used + cost > token_budget or repeats_fragment):
                intervals.append({"index": len(intervals), "parts": current})
                current, used = [], 0
            current.append({**piece, "tokens": cost})
            used += cost
    if current:
        intervals.append({"index": len(intervals), "parts": current})
    total = len(intervals)
    return [{**interval, "total": total} for interval in intervals]


def _unit_pieces(ref: str, text: str, token_budget: int) -> list[dict]:
    if estimate_tokens(text) <= token_budget:
        return [{"ref": ref, "start": 0, "end": len(text), "forced": False}]
    boundaries = [0]
    for match in re.finditer(r"(?:\n\s*\n|(?<=[.!?])\s+)", text):
        boundaries.append(match.end())
    boundaries.append(len(text))
    result: list[dict] = []
    chunk_start = boundaries[0]
    chunk_end = chunk_start
    for start, end in zip(boundaries, boundaries[1:], strict=False):
        if end <= start:
            continue
        if estimate_tokens(text[start:end]) > token_budget:
            if chunk_end > chunk_start:
                result.append(
                    {"ref": ref, "start": chunk_start, "end": chunk_end, "forced": False}
                )
            result.extend(_forced_slices(ref, text, start, end, token_budget))
            chunk_start = chunk_end = end
            continue
        candidate_start = chunk_start if chunk_end > chunk_start else start
        if chunk_end > chunk_start and estimate_tokens(text[candidate_start:end]) > token_budget:
            result.append(
                {"ref": ref, "start": chunk_start, "end": chunk_end, "forced": False}
            )
            chunk_start = start
        elif chunk_end == chunk_start:
            chunk_start = start
        chunk_end = end
    if chunk_end > chunk_start:
        result.append({"ref": ref, "start": chunk_start, "end": chunk_end, "forced": False})
    return result


def _forced_slices(ref: str, text: str, start: int, end: int, token_budget: int) -> list[dict]:
    value = text[start:end]
    if estimate_tokens(value) <= token_budget:
        return [{"ref": ref, "start": start, "end": end, "forced": False}]
    # Последняя граница вынужденная и явно остаётся в checkpoint.
    ratio = max(1, math.ceil(estimate_tokens(value) / token_budget))
    width = max(1, math.ceil(len(value) / ratio))
    return [
        {"ref": ref, "start": offset, "end": min(end, offset + width), "forced": True}
        for offset in range(start, end, width)
    ]


def _packet_spec(index: int, items: list[dict], all_items: list[dict]) -> PacketSpec:
    targets = [item["block_id"] for item in items]
    target_specs = {}
    for item in items:
        interval = item["intervals"][0]
        target_specs[item["block_id"]] = {
            "parts": interval["parts"],
            "interval_index": interval["index"],
            "interval_count": interval["total"],
            "section_key": item["section_key"],
        }
    input_tokens = sum(
        part.get("tokens", 0) for item in items for part in item["intervals"][0]["parts"]
    )
    positions = {item["block_id"]: pos for pos, item in enumerate(all_items)}
    context_refs: list[str] = []
    for block_id in targets:
        pos = positions[block_id]
        if pos > 0 and all_items[pos - 1]["material_id"] == all_items[pos]["material_id"]:
            ref = all_items[pos - 1]["last_ref"]
            if ref:
                context_refs.append(ref)
        has_next = pos + 1 < len(all_items)
        next_in_material = has_next and (
            all_items[pos + 1]["material_id"] == all_items[pos]["material_id"]
        )
        if next_in_material:
            ref = all_items[pos + 1]["first_ref"]
            if ref:
                context_refs.append(ref)
    return PacketSpec(
        key=f"overview:{index:06d}",
        targets=targets,
        checkpoint={
            "target_specs": target_specs,
            "context_refs": list(dict.fromkeys(context_refs)),
            # Оценка входа пакета нужна не для отчёта: из неё выводится предел запуска.
            "input_tokens": input_tokens,
        },
    )
