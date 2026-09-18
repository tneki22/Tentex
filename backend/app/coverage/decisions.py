"""Долговечные личные запреты для существующего binding API и его undo."""

from sqlalchemy import select

from app.coverage.snapshots import fingerprint
from app.models import BindingStatus, CoverageDecision, MaterialFragment, MaterialPage, Project


def remember_binding_choice(session, binding, *, action_id=None):
    """Вызывается в транзакции ручного действия, никогда из машинного издателя."""
    key = f"{binding.program_node_id}:{binding.fragment_id}"
    decision = session.scalar(
        select(CoverageDecision).where(
            CoverageDecision.project_id == binding.project_id,
            CoverageDecision.kind == "reject_link",
            CoverageDecision.target_key == key,
        )
    )
    fragment = session.get(MaterialFragment, binding.fragment_id)
    page = session.get(MaterialPage, fragment.page_id) if fragment else None
    if decision is None:
        decision = CoverageDecision(
            project_id=binding.project_id, kind="reject_link", target_key=key, version=0
        )
        session.add(decision)
    decision.version += 1
    decision.action_id = action_id
    decision.source_revision = page.revision if page else None
    decision.anchor_fingerprint = fingerprint(fragment.text) if fragment else None
    decision.payload = {
        "rejected": binding.status == BindingStatus.REMOVED,
        "topic_id": str(binding.program_node_id),
        "material_id": str(binding.material_id),
        "fragment_id": str(binding.fragment_id),
    }
    project = session.get(Project, binding.project_id)
    project.coverage_revision += 1


def link_rejected(session, project_id, topic_id, fragment) -> bool:
    """При неоднозначном переносе запрета автоматическое восстановление запрещено."""
    decisions = session.scalars(
        select(CoverageDecision).where(
            CoverageDecision.project_id == project_id, CoverageDecision.kind == "reject_link"
        )
    )
    text_hash = fingerprint(fragment.text)
    for decision in decisions:
        payload = decision.payload
        if not payload.get("rejected") or payload.get("topic_id") != str(topic_id):
            continue
        if payload.get("material_id") != str(fragment.material_id):
            continue
        if (
            payload.get("fragment_id") == str(fragment.id)
            or decision.anchor_fingerprint == text_hash
        ):
            return True
        # Изменённый текст не доказывает, что прежний запрет относился к другому месту.
        page = session.get(MaterialPage, fragment.page_id)
        if page.revision != decision.source_revision:
            return True
    return False
