"""Полный контекст активной программы без содержимого эталонных ответов."""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import NodeType, ProgramNode, ReferenceAnswer


def build_program_context(session: Session, project_id: UUID) -> list[dict]:
    """Вернуть все активные узлы в DFS с путём предков и метриками ответа."""
    nodes = list(
        session.scalars(
            select(ProgramNode).where(
                ProgramNode.project_id == project_id,
                ProgramNode.is_in_current_program.is_(True),
                ProgramNode.is_archived.is_(False),
            )
        )
    )
    answers = dict(
        session.execute(
            select(ReferenceAnswer.program_node_id, func.length(ReferenceAnswer.text)).where(
                ReferenceAnswer.project_id == project_id, ReferenceAnswer.is_active.is_(True)
            )
        ).all()
    )
    children = defaultdict(list)
    for node in nodes:
        children[node.parent_id].append(node)
    for siblings in children.values():
        siblings.sort(key=lambda node: (node.sort_order, node.id))
    result = []

    def visit(parent_id: UUID | None, path: list[str]) -> None:
        for node in children[parent_id]:
            result.append(
                {
                    "id": str(node.id),
                    "parent_id": str(node.parent_id) if node.parent_id else None,
                    "node_type": node.node_type.value,
                    "exam_kind": node.exam_kind.value if node.exam_kind else None,
                    "title": node.title,
                    "path": path,
                    "sort_order": node.sort_order,
                    "target_level": node.target_level.value if node.target_level else None,
                    "subpoints": [
                        child.title
                        for child in children[node.id]
                        if child.node_type == NodeType.SUBPOINT
                    ],
                    "has_answer": node.id in answers,
                    "answer_chars": answers.get(node.id, 0),
                }
            )
            visit(node.id, [*path, node.title])

    visit(None, [])
    return result
