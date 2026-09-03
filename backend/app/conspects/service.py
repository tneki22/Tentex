import mimetypes
from collections import defaultdict
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.conspects.schemas import (
    ConspectImageRead,
    ConspectRead,
    ConspectSummaryEntry,
    ConspectSummaryRead,
    ConspectWrite,
)
from app.materials.storage import material_path, store_namespaced_upload
from app.models import (
    Conspect,
    ConspectImage,
    NodeType,
    ProgramNode,
    Project,
    ProjectStatus,
    WorkspaceVariant,
    utc_now,
)
from app.projects.errors import ProjectConflictError, ProjectDomainError, ProjectNotFoundError

STUDY_NODE_TYPES = {NodeType.TOPIC, NodeType.SUBPOINT}
CONSPECT_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
CONSPECT_IMAGE_MAX_BYTES = 20 * 1024 * 1024


def _require_conspect_project(session: Session, project_id: UUID, *, writable: bool) -> Project:
    project = session.get(Project, project_id)
    if project is None or project.status == ProjectStatus.DRAFT:
        raise ProjectNotFoundError()
    if writable and project.status != ProjectStatus.ACTIVE:
        raise ProjectConflictError(
            "Архивный или завершённый проект нельзя изменять",
            code="project_read_only",
            context={"current_status": project.status.value},
        )
    return project


def _require_conspect_node(session: Session, project_id: UUID, node_id: UUID) -> ProgramNode:
    node = session.get(ProgramNode, node_id)
    if node is None or node.project_id != project_id or node.is_archived:
        raise ProjectNotFoundError("Тема программы не найдена")
    if node.node_type not in STUDY_NODE_TYPES:
        raise ProjectDomainError(
            "Конспект можно вести только по изучаемому узлу",
            status=422,
            code="conspect_requires_study_node",
        )
    return node


def _list_conspect_images(
    session: Session, project_id: UUID, node_id: UUID
) -> list[ConspectImageRead]:
    images = session.scalars(
        select(ConspectImage)
        .where(ConspectImage.project_id == project_id, ConspectImage.program_node_id == node_id)
        .order_by(ConspectImage.created_at)
    )
    return [ConspectImageRead.model_validate(image, from_attributes=True) for image in images]


def get_conspect(session: Session, project_id: UUID, node_id: UUID) -> ConspectRead:
    _require_conspect_project(session, project_id, writable=False)
    _require_conspect_node(session, project_id, node_id)
    conspect = session.get(Conspect, (project_id, node_id))
    return ConspectRead(
        project_id=project_id,
        node_id=node_id,
        content_markdown=conspect.content_markdown if conspect is not None else "",
        revision=conspect.revision if conspect is not None else 0,
        updated_at=conspect.updated_at if conspect is not None else None,
        images=_list_conspect_images(session, project_id, node_id),
    )


def save_conspect(
    session: Session, project_id: UUID, node_id: UUID, command: ConspectWrite
) -> ConspectRead:
    with session.begin():
        _require_conspect_project(session, project_id, writable=True)
        _require_conspect_node(session, project_id, node_id)
        conspect = session.get(Conspect, (project_id, node_id))
        current_revision = conspect.revision if conspect is not None else 0
        if command.expected_revision != current_revision:
            raise ProjectConflictError(
                "Конспект изменился в другом месте",
                code="stale_conspect_revision",
                context={"current_revision": current_revision},
            )

        now = utc_now()
        if conspect is None:
            conspect = Conspect(
                project_id=project_id,
                program_node_id=node_id,
                content_markdown=command.content_markdown,
                revision=1,
                created_at=now,
                updated_at=now,
            )
            session.add(conspect)
        else:
            conspect.content_markdown = command.content_markdown
            conspect.revision += 1
            conspect.updated_at = now

        images = list(
            session.scalars(
                select(ConspectImage).where(
                    ConspectImage.project_id == project_id,
                    ConspectImage.program_node_id == node_id,
                )
            )
        )
        owned_ids = {image.id for image in images}
        foreign_ids = set(command.retained_image_ids) - owned_ids
        if foreign_ids:
            raise ProjectDomainError(
                "Изображение не принадлежит этой теме",
                status=422,
                code="conspect_image_not_found",
            )
        retained_ids = set(command.retained_image_ids)
        to_remove = [image for image in images if image.id not in retained_ids]
        removed_paths = [material_path(image.storage_path) for image in to_remove]
        for image in to_remove:
            session.delete(image)
        session.flush()
        result = ConspectRead(
            project_id=project_id,
            node_id=node_id,
            content_markdown=conspect.content_markdown,
            revision=conspect.revision,
            updated_at=conspect.updated_at,
            images=_list_conspect_images(session, project_id, node_id),
        )
    for path in removed_paths:
        path.unlink(missing_ok=True)
    return result


def _dfs_ordered_nodes(nodes: list[ProgramNode]) -> list[ProgramNode]:
    children: dict[UUID | None, list[ProgramNode]] = defaultdict(list)
    for node in nodes:
        children[node.parent_id].append(node)
    for siblings in children.values():
        siblings.sort(key=lambda node: (node.sort_order, str(node.id)))

    ordered: list[ProgramNode] = []

    def visit(parent_id: UUID | None) -> None:
        for child in children.get(parent_id, []):
            ordered.append(child)
            visit(child.id)

    visit(None)
    return ordered


def list_conspect_summary(session: Session, project_id: UUID) -> ConspectSummaryRead:
    project = _require_conspect_project(session, project_id, writable=False)
    if project.workspace_variant != WorkspaceVariant.EXAM:
        raise ProjectConflictError(
            "Сводный конспект доступен только экзаменационным проектам",
            code="conspect_summary_requires_exam_project",
        )

    all_nodes = list(
        session.scalars(select(ProgramNode).where(ProgramNode.project_id == project_id))
    )
    study_nodes = [
        node
        for node in _dfs_ordered_nodes(all_nodes)
        if node.node_type in STUDY_NODE_TYPES
        and node.is_in_current_program
        and not node.is_archived
    ]
    node_ids = [node.id for node in study_nodes]
    conspects_by_node = (
        {
            conspect.program_node_id: conspect
            for conspect in session.scalars(
                select(Conspect).where(
                    Conspect.project_id == project_id, Conspect.program_node_id.in_(node_ids)
                )
            )
        }
        if node_ids
        else {}
    )

    entries: list[ConspectSummaryEntry] = []
    for position, node in enumerate(study_nodes, start=1):
        conspect = conspects_by_node.get(node.id)
        if conspect is None or conspect.content_markdown.strip() == "":
            continue
        entries.append(
            ConspectSummaryEntry(
                node_id=node.id,
                position=position,
                title=node.title,
                content_markdown=conspect.content_markdown,
                revision=conspect.revision,
                updated_at=conspect.updated_at,
            )
        )
    return ConspectSummaryRead(entries=entries)


async def add_conspect_image(
    session: Session, project_id: UUID, node_id: UUID, upload: UploadFile
) -> ConspectImageRead:
    _require_conspect_project(session, project_id, writable=False)  # ранний отказ до чтения тела
    relative_path, size, original_name = await store_namespaced_upload(
        "conspects",
        str(project_id),
        upload,
        allowed_suffixes=CONSPECT_IMAGE_SUFFIXES,
        max_bytes=CONSPECT_IMAGE_MAX_BYTES,
        unsupported_message="Поддерживаются PNG, JPG, JPEG, WEBP и GIF",
        error_code_prefix="conspect_image",
    )
    # Присланному content_type не доверяем: тип определяем по расширению файла.
    media_type = mimetypes.guess_type(original_name)[0] or "application/octet-stream"
    # Ранняя проверка открыла транзакцию чтения: без rollback() begin() падает
    # с «A transaction is already begun» (тот же приём в projects.answers).
    session.rollback()
    with session.begin():
        _require_conspect_project(session, project_id, writable=True)
        node = _require_conspect_node(session, project_id, node_id)
        image = ConspectImage(
            id=uuid4(),
            project_id=project_id,
            program_node_id=node.id,
            file_name=original_name,
            storage_path=relative_path,
            media_type=media_type,
            size_bytes=size,
            created_at=utc_now(),
        )
        session.add(image)
        session.flush()
        result = ConspectImageRead.model_validate(image, from_attributes=True)
    return result


def conspect_image_path(session: Session, project_id: UUID, image_id: UUID) -> Path:
    _require_conspect_project(session, project_id, writable=False)
    image = session.get(ConspectImage, image_id)
    if image is None or image.project_id != project_id:
        raise ProjectNotFoundError("Изображение не найдено")
    return material_path(image.storage_path)


def _markdown_references_image(content_markdown: str, image_id: UUID) -> bool:
    return str(image_id) in content_markdown


def delete_conspect_image(session: Session, project_id: UUID, image_id: UUID) -> None:
    with session.begin():
        _require_conspect_project(session, project_id, writable=True)
        image = session.get(ConspectImage, image_id)
        if image is None or image.project_id != project_id:
            raise ProjectNotFoundError("Изображение не найдено")
        conspect = session.get(Conspect, (image.project_id, image.program_node_id))
        if conspect is not None and _markdown_references_image(
            conspect.content_markdown, image.id
        ):
            raise ProjectConflictError(
                "Изображение используется в сохранённом конспекте",
                code="conspect_image_in_use",
            )
        path = material_path(image.storage_path)
        session.delete(image)
    path.unlink(missing_ok=True)
