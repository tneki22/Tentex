"""Лестница опор П5 и изоляция ошибок до одного target, без сети и БД."""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from uuid import UUID

from pydantic import ValidationError

from app.coverage.schemas import BlockDecision, Disposition, Evidence
from app.materials.page_numbers import is_page_number

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
# Содержательные исходы части и их сила: связь content сильнее mention и context.
CONTENT_OUTCOMES = {"content", "mention", "context"}
OUTCOME_STRENGTH = ["context", "mention", "content"]


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


def _with_page_numbers(decision: BlockDecision, units: dict[str, Unit]) -> BlockDecision:
    """Номер страницы — служебная часть блока, о которой модель не спрашивают.

    Разбор PDF оставляет «27» отдельным фрагментом, и модель раньше размечала его как
    содержание: на «Мат логике» так набралось 29 связей. Теперь фрагмент в пакет не
    попадает, а его исход `service` дописывает сервер; связь и ответ модели о нём,
    если они всё же пришли (сохранённый ответ старой версии), отбрасываются.
    """
    numbers = {ref for ref, unit in units.items() if is_page_number(unit.text)}
    if not numbers:
        return decision
    position = {ref: index for index, ref in enumerate(units)}
    dispositions = [d for d in decision.dispositions if str(d.fragment_id) not in numbers]
    dispositions += [
        Disposition(fragment_id=UUID(ref), start=0, end=len(units[ref].text), outcome="service")
        for ref in numbers
    ]
    dispositions.sort(key=lambda d: (position.get(str(d.fragment_id), len(position)), d.start))
    links = [link for link in decision.links if str(link.fragment_id) not in numbers]
    return decision.model_copy(update={"dispositions": dispositions, "links": links})


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
    """Негодная связь снимается отдельно: блок не отвечает за одну свою строку."""
    links = []
    for link in decision.links:
        ref = str(link.fragment_id)
        if str(link.topic_id) not in topics or ref not in units:
            # Связь мимо программы или мимо блока — одна строка ответа, а не приговор
            # всему разбору: остальные связи блока проверяются как обычно.
            diagnostics.append({"reason": "link_scope", "ref": ref})
            continue
        if link.semantic_kind != "content" and set(link.roles) != {"reference"}:
            # Вес несодержательной связи задаёт semantic_kind, а роль у неё по контракту
            # ровно одна. Имя роли не стоит разбора блока: роль приводится к контракту.
            diagnostics.append({"reason": "reference_roles", "ref": ref})
            link = link.model_copy(update={"roles": ["reference"]})
        if _unavailable_visual(units[ref], inspected):
            # Рисунок никто не смотрел: снимается связь этого фрагмента, а не раздел,
            # в котором он стоит. Текст вокруг картинки разобран и публикуется.
            diagnostics.append({"reason": "visual_unavailable", "ref": ref})
            continue
        evidence = _repair_all(link.evidence, seen, inspected, diagnostics)
        if not evidence:
            continue
        if link.semantic_kind == "content":
            if units[ref].kind in {"heading", "title"}:
                # Заголовок не раскрывает тему — но и не отменяет разбор всего блока.
                # Модель помечает ведущий заголовок content вместе с телом раздела, и
                # отклонение target уносило разом все верные связи семидесяти абзацев.
                diagnostics.append({"reason": "heading_content", "ref": ref})
                continue
            if not any(_supports_target(e, {ref: units[ref]}, inspected) for e in evidence):
                diagnostics.append({"reason": "content_without_target", "ref": ref})
                continue
        links.append({**link.model_dump(mode="json"), "evidence": evidence})
    return links


def _unavailable_visual(unit: Unit, inspected: set[str]) -> bool:
    """Рисунок без визуального разбора: его нельзя ни связать, ни признать служебным."""
    return unit.kind == "image" and unit.page_ref not in inspected


def _link_outcome(link: dict) -> str:
    """Исход части, который подтверждает эта связь."""
    return "context" if link["semantic_kind"] == "prerequisite" else link["semantic_kind"]


def derive_outcome(outcomes) -> str:
    """Агрегат выводится из проверенных частей, а не берётся у модели на веру.

    Части валидируются пофрагментно и являются истиной; объявленный моделью исход —
    избыточные данные. `linked` при служебной части — это `mixed_resolved`, и сервер
    называет это сам вместо того, чтобы отклонить весь разбор блока.
    """
    outcomes = set(outcomes)
    if not outcomes or "unresolved" in outcomes:
        return "unresolved"
    if outcomes == {"service"}:
        return "service"
    if outcomes == {"outside_program"}:
        return "outside_program"
    if outcomes <= CONTENT_OUTCOMES:
        return "linked"
    return "mixed_resolved"


def _align_dispositions(dispositions, links, units, inspected):
    """Часть следует за своими проверенными связями; без связи она unresolved."""
    by_ref: dict[str, set[str]] = {}
    for link in links:
        by_ref.setdefault(link["fragment_id"], set()).add(_link_outcome(link))
    aligned, changes = [], []
    for part in dispositions:
        ref, outcome, reason = str(part.fragment_id), part.outcome, ""
        if _unavailable_visual(units[ref], inspected):
            outcome, reason = "unresolved", "visual_unavailable"
        elif ref in by_ref:
            # Связь прошла лестницу опор целиком, а исход части — просто её имя.
            outcome, reason = max(by_ref[ref], key=OUTCOME_STRENGTH.index), "disposition_realigned"
        elif outcome in CONTENT_OUTCOMES:
            outcome, reason = "unresolved", "unsupported_evidence"
        if outcome != part.outcome:
            changes.append({"reason": reason, "ref": ref})
            part = part.model_copy(update={"outcome": outcome})
        aligned.append(part)
    return aligned, changes


def _block_reason(decision, outcome: str, changes: list[dict]) -> str:
    """Причина unresolved: своя у модели, иначе — та, по которой сервер снял часть."""
    own = decision.reason.strip()
    if outcome != "unresolved":
        return decision.reason
    if own and any(part.outcome == "unresolved" for part in decision.dispositions):
        return own
    for reason in ("visual_unavailable", "unsupported_evidence"):
        if any(change["reason"] == reason for change in changes):
            return reason
    return own or "unresolved_remainder"


def _check_evidence_keys(items: list[dict]) -> None:
    """Ключ опоры становится её публичным адресом: двусмысленный адрес роняет блок.

    На alias-протоколе ключи выдаёт сервер и они уникальны по построению; проверка
    остаётся для решений углубления, где ключ приходит от модели.
    """
    keys: dict[str, dict] = {}
    for item in items:
        for evidence in item["evidence"]:
            if keys.setdefault(evidence["key"], evidence) != evidence:
                raise ValueError("duplicate_evidence_key")


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
        decision = _with_page_numbers(decision, units)
        _check_ranges(decision, units)
        links = _check_links(decision, units, seen, inspected, topics, diagnostics)
        dispositions, changes = _align_dispositions(decision.dispositions, links, units, inspected)
        diagnostics.extend(changes)
        outcome = derive_outcome(part.outcome for part in dispositions)
        # Непроверенный остаток не заменяет собой уже готовый разбор блока.
        replacement_allowed = not any(part.outcome == "unresolved" for part in dispositions)
        findings = []
        for finding in decision.findings:
            evidence = _repair_all(finding.evidence, seen, inspected, diagnostics)
            if not evidence:
                # Предложение по программе — не покрытие: негодная опора снимает
                # предложение, а не разбор блока.
                diagnostics.append({"reason": "unsupported_finding"})
                continue
            findings.append({**finding.model_dump(mode="json"), "evidence": evidence})
        _check_evidence_keys(links + findings)
        return CheckedDecision(
            str(target_id),
            True,
            outcome,
            _block_reason(decision, outcome, changes),
            [d.model_dump(mode="json") for d in dispositions],
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
