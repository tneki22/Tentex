"""Лестница опор П5 и изоляция ошибок до одного target, без сети и БД."""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.coverage.schemas import BlockDecision, Evidence

# Порог зафиксирован replay-v7, COVERAGE_INTEGRATION/06 §3.
APPROXIMATE_THRESHOLD = 0.75
LATEX_SYMBOLS = {
    "in": "∈",
    "notin": "∉",
    "subset": "⊂",
    "subseteq": "⊆",
    "times": "×",
    "cdot": "·",
    "le": "≤",
    "leq": "≤",
    "ge": "≥",
    "geq": "≥",
    "neq": "≠",
    "to": "→",
    "rightarrow": "→",
    "leftarrow": "←",
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "Sigma": "Σ",
    "sigma": "σ",
    "sum": "∑",
    "lambda": "λ",
    "epsilon": "ε",
    "infty": "∞",
    "cup": "∪",
    "cap": "∩",
}
HOMOGLYPHS = str.maketrans("ABCEHKMOPTXYaceopxy", "АВСЕНКМОРТХУасеорху")


def normalize(text: str) -> str:
    """Сравнимое представление; никогда не используется как опубликованный текст."""
    value = unicodedata.normalize("NFKC", text)
    value = re.sub(r"\\([a-zA-Z]+)", lambda m: LATEX_SYMBOLS.get(m[1], m[1]), value)
    value = re.sub(r"\\[()\[\]]|\$|[{}*_`]", "", value)
    value = re.sub(r"\.{2,}|…|[-—]{2,}", " ", value)
    return " ".join(value.translate(HOMOGLYPHS).casefold().split())


@dataclass(frozen=True)
class Unit:
    """Прочитанный текст снимка с адресом и качеством."""

    ref: str
    text: str
    block_id: str
    page_ref: str
    kind: str = "paragraph"
    quality: str = "native"
    locator: dict = field(default_factory=dict)
    start_offset: int = 0


@dataclass
class CheckedDecision:
    """Валидность отделена от исхода: корректное unresolved — тоже результат."""

    target_id: str
    valid: bool
    outcome: str = "unresolved"
    reason: str = ""
    dispositions: list[dict] = field(default_factory=list)
    links: list[dict] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)
    diagnostics: list[dict] = field(default_factory=list)
    origin: str = "overview"
    replacement_allowed: bool = True


def repair_evidence(evidence: Evidence, seen: dict[str, Unit], inspected: set[str]) -> dict | None:
    """Принимает только прочитанное, сохраняет участок оригинала и ступень починки."""
    if evidence.ref.startswith("page:"):
        if evidence.ref in inspected and evidence.description.strip():
            return {**evidence.model_dump(), "quote": "", "repair": "visual"}
        return None
    unit = seen.get(evidence.ref)
    quote = evidence.quote
    if unit and (not quote or quote in unit.text):
        start = unit.text.index(quote) if quote else 0
        end = start + len(quote) if quote else len(unit.text)
        return _original(evidence, unit, "exact", start, end)
    normalized = normalize(quote)
    if not normalized:
        return None
    if unit and normalized in normalize(unit.text):
        return _original(evidence, unit, "normalized")
    words = Counter(re.findall(r"\w+", normalized))
    if unit and words:
        original = Counter(re.findall(r"\w+", normalize(unit.text)))
        if sum((words & original).values()) / words.total() >= APPROXIMATE_THRESHOLD:
            return _original(evidence, unit, "approximate")
    for neighbor in seen.values():
        if neighbor.ref != evidence.ref and normalized in normalize(neighbor.text):
            return _original(evidence, neighbor, "ref_corrected")
    return None


def _original(evidence: Evidence, unit: Unit, repair: str, start=0, end=None) -> dict:
    end = len(unit.text) if end is None else end
    return {
        **evidence.model_dump(),
        "ref": unit.ref,
        "quote": unit.text[start:end],
        "start": start + unit.start_offset,
        "end": end + unit.start_offset,
        "repair": repair,
        "original_ref": evidence.ref,
        "locator": unit.locator,
    }


def _supports_target(evidence: dict, units: dict[str, Unit], inspected: set[str]) -> bool:
    if evidence["ref"] in units:
        return True
    return any(
        (u.kind in {"image", "formula", "table"} or u.quality == "ocr_low")
        and u.page_ref == evidence["ref"]
        and u.page_ref in inspected
        for u in units.values()
    )


def _check_ranges(decision: BlockDecision, units: dict[str, Unit]) -> None:
    """Полное покрытие диапазонов без перекрытия; пустота не имитирует чтение."""
    if not units or any(str(d.fragment_id) not in units for d in decision.dispositions):
        raise ValueError("fragment_accounting")
    for ref, unit in units.items():
        spans = sorted(
            (d for d in decision.dispositions if str(d.fragment_id) == ref), key=lambda d: d.start
        )
        cursor = 0
        if not spans or not unit.text:
            raise ValueError("empty_or_missing_fragment")
        for span in spans:
            if span.start != cursor or span.end <= span.start or span.end > len(unit.text):
                raise ValueError("range_accounting")
            cursor = span.end
        if cursor != len(unit.text):
            raise ValueError("unread_remainder")


def _repair_all(evidences, seen, inspected, diagnostics) -> list[dict]:
    repaired = []
    for evidence in evidences:
        value = repair_evidence(evidence, seen, inspected)
        if value is None:
            diagnostics.append({"key": evidence.key, "reason": "unread_or_unsupported"})
        else:
            repaired.append(value)
            if value["repair"] != "exact":
                diagnostics.append({"key": evidence.key, "repair": value["repair"]})
    return repaired


def _check_links(decision, units, seen, inspected, topics, diagnostics) -> list[dict]:
    """Плохая опора снимается отдельно; смысловые нарушения отклоняют target."""
    links = []
    for link in decision.links:
        ref = str(link.fragment_id)
        if str(link.topic_id) not in topics or ref not in units:
            raise ValueError("link_scope")
        if link.semantic_kind != "content" and set(link.roles) != {"reference"}:
            raise ValueError("reference_roles")
        evidence = _repair_all(link.evidence, seen, inspected, diagnostics)
        if not evidence:
            continue
        if link.semantic_kind == "content":
            if units[ref].kind in {"heading", "title"}:
                raise ValueError("heading_content")
            if not any(_supports_target(e, {ref: units[ref]}, inspected) for e in evidence):
                raise ValueError("content_without_target")
        links.append({**link.model_dump(mode="json"), "evidence": evidence})
    return links


def _check_outcome(decision, links) -> None:
    outcomes = {d.outcome for d in decision.dispositions}
    if "unresolved" in outcomes and decision.outcome != "unresolved":
        raise ValueError("unresolved_remainder")
    if decision.outcome == "unresolved" and not decision.reason.strip():
        raise ValueError("unresolved_reason")
    expected = {
        "service": {"service"},
        "outside_program": {"outside_program"},
        "linked": {"content", "mention", "context"},
    }
    if decision.outcome in expected and not outcomes <= expected[decision.outcome]:
        raise ValueError("outcome_dispositions")
    if decision.outcome == "mixed_resolved" and (len(outcomes) < 2 or "unresolved" in outcomes):
        raise ValueError("mixed_parts")
    if bool(links) != bool(outcomes & {"content", "mention", "context"}):
        raise ValueError("link_accounting")
    for disposition in decision.dispositions:
        if disposition.outcome not in {"content", "mention", "context"}:
            continue
        if not any(
            str(disposition.fragment_id) == link["fragment_id"]
            and disposition.outcome
            == ("context" if link["semantic_kind"] == "prerequisite" else link["semantic_kind"])
            for link in links
        ):
            raise ValueError("disposition_without_link")


def validate_target(target_id, raw, units, seen, inspected, topics, *, origin="overview"):
    """Проверяет одно решение; исключения схемы не распространяются на соседей."""
    diagnostics = []
    try:
        if len(raw) != 1:
            raise ValueError("missing_or_duplicate_target")
        # Маркер сервера («диапазон с частями», «не сошлись фрагменты», неизвестная тема)
        # не должен превращаться в «ответ не по схеме»: причина уже известна точно.
        if isinstance(raw[0], dict) and raw[0].get("error"):
            raise ValueError(str(raw[0]["error"])[:80])
        decision = BlockDecision.model_validate(raw[0])
        if str(decision.target_id) != str(target_id):
            raise ValueError("target_scope")
        _check_ranges(decision, units)
        if any(u.kind == "image" and u.page_ref not in inspected for u in units.values()):
            raise ValueError("visual_unavailable")
        links = _check_links(decision, units, seen, inspected, topics, diagnostics)
        replacement_allowed = True
        if len(links) < len(decision.links):
            dispositions = []
            for part in decision.dispositions:
                supported = any(str(part.fragment_id) == link["fragment_id"] for link in links)
                if part.outcome in {"content", "mention", "context"} and not supported:
                    part = part.model_copy(update={"outcome": "unresolved"})
                dispositions.append(part)
            if any(part.outcome == "unresolved" for part in dispositions):
                decision = decision.model_copy(
                    update={
                        "outcome": "unresolved",
                        "reason": "unsupported_evidence",
                        "dispositions": dispositions,
                    }
                )
                replacement_allowed = False
        _check_outcome(decision, links)
        findings = []
        for finding in decision.findings:
            evidence = _repair_all(finding.evidence, seen, inspected, diagnostics)
            if not evidence:
                raise ValueError("unsupported_finding")
            findings.append({**finding.model_dump(mode="json"), "evidence": evidence})
        keys = {}
        for item in links + findings:
            for evidence in item["evidence"]:
                if evidence["key"] in keys and keys[evidence["key"]] != evidence:
                    raise ValueError("duplicate_evidence_key")
                keys[evidence["key"]] = evidence
        return CheckedDecision(
            str(target_id),
            True,
            decision.outcome,
            decision.reason,
            [d.model_dump(mode="json") for d in decision.dispositions],
            links,
            findings,
            diagnostics,
            origin,
            replacement_allowed,
        )
    except (ValidationError, ValueError) as error:
        reason = "invalid_schema" if isinstance(error, ValidationError) else str(error)
        return CheckedDecision(
            str(target_id), False, reason=reason, diagnostics=diagnostics, origin=origin
        )


def merge_refinement(primary: CheckedDecision, refinement: CheckedDecision | None):
    """Сбой уточнения не уничтожает уже проверенный результат обзора."""
    if refinement is not None and refinement.valid and refinement.replacement_allowed:
        return refinement
    if primary.valid:
        primary.diagnostics.append({"reason": "refinement_failed", "origin": primary.origin})
    return primary
