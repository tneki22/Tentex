"""Приём файла `.tentex-lessons`: проверка, предпросмотр и создание уроков.

Предпросмотр ничего не пишет: он читает файл, предлагает тему этого проекта для
каждого урока (по формулировке и пути в программе) и ищет материалы по SHA-256.
Импорт создаёт уроки одной записью журнала `lesson_bulk_create`: «Отменить»
уносит уроки и сделанные ими привязки. Кусок, чей материал нашёлся, становится
живой ссылкой с привязками темы; не нашёлся — снимком текста (`snapshot_md`).
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import project_write_transaction
from app.lessons import refs as refs_module
from app.lessons.editing import IMAGE_SUFFIXES, _bind_fragments
from app.lessons.export.package import FORMAT, FORMAT_VERSION
from app.lessons.export.resolve import resolve_bounds
from app.lessons.schemas import LessonSummaryRead
from app.lessons.service import (
    ACTION_LESSON_BULK,
    STUDY_NODE_TYPES,
    _latest_action,
    _load_program,
    _require_lessons_project,
    _require_study_node,
    _source_name,
    lessons_overview,
    titles_match,
)
from app.lessons.task_store import sync_lesson_tasks
from app.materials.schemas import MaterialPurpose
from app.materials.storage import material_path
from app.models import (
    Activity,
    ActivityKind,
    ActivityOrigin,
    Lesson,
    LessonBasis,
    LessonBlock,
    LessonBlockKind,
    LessonBlockOrigin,
    LessonNoteVariant,
    LessonRefRole,
    LessonSourceRef,
    LessonStatus,
    LessonTopic,
    Material,
    ProgramNode,
    ProjectActionLog,
    ProjectMaterial,
    SourceRole,
    StudyTask,
    StudyTaskDifficulty,
    StudyTaskForm,
    utc_now,
)
from app.projects.errors import ProjectDomainError
from app.projects.schemas import ApiModel, LatestUndoableAction

MAX_PACKAGE_BYTES = 200 * 1024 * 1024
MAX_UNPACKED_BYTES = 600 * 1024 * 1024
MAX_LESSONS = 500


def _corrupt(detail: str) -> ProjectDomainError:
    return ProjectDomainError(detail, status=422, code="lesson_package_corrupt")


# --- содержимое файла ---------------------------------------------------------------


class _Loose(BaseModel):
    """Записи файла читаются терпимо: лишнее поле из будущей версии не ошибка."""

    model_config = ConfigDict(extra="ignore")


class PackageRef(_Loose):
    role: LessonRefRole = LessonRefRole.CONTENT
    material: str | None = None
    name: str = "Материал"
    page_from: int = Field(ge=1)
    page_to: int = Field(ge=1)
    from_: dict[str, Any] | None = Field(default=None, alias="from")
    to: dict[str, Any] | None = None
    region_bbox: list[float] | None = None
    always_pages: bool = False
    citation_label: str | None = Field(default=None, max_length=16)
    snapshot_md: str | None = None


class PackageTask(_Loose):
    form: StudyTaskForm
    prompt_md: str
    payload: dict[str, Any] = Field(default_factory=dict)
    answer_key: dict[str, Any] = Field(default_factory=dict)
    reference_md: str | None = None
    explanation_md: str | None = None
    hint_md: str | None = None
    difficulty: StudyTaskDifficulty = StudyTaskDifficulty.UNDERSTAND
    basis: LessonBasis = LessonBasis.SOURCES_AND_MODEL
    source_snapshot: dict[str, Any] = Field(default_factory=dict)


class PackageBlock(_Loose):
    kind: LessonBlockKind
    variant: LessonNoteVariant | None = None
    body_md: str | None = None
    origin: LessonBlockOrigin = LessonBlockOrigin.MANUAL
    basis: LessonBasis | None = None
    collapsed: bool = False
    topic: int | None = None
    refs: list[PackageRef] = Field(default_factory=list)
    media: dict[str, Any] | None = None
    task: PackageTask | None = None


class PackageTopic(_Loose):
    title: str
    path: list[str] = Field(default_factory=list)


class PackageLesson(_Loose):
    key: str
    title: str = Field(min_length=1)
    goal: str | None = None
    status: LessonStatus = LessonStatus.DRAFT
    duration_minutes: int | None = Field(default=None, ge=0)
    build: dict[str, Any] | None = None
    topics: list[PackageTopic] = Field(default_factory=list)
    blocks: list[PackageBlock] = Field(default_factory=list)


class PackageMaterial(_Loose):
    key: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    name: str = "Материал"
    page_count: int | None = None


class PackageManifest(_Loose):
    format: str
    version: int
    app_version: str | None = None
    exported_at: str | None = None
    project: dict[str, Any] = Field(default_factory=dict)
    materials: list[PackageMaterial] = Field(default_factory=list)


@dataclass(slots=True)
class Package:
    manifest: PackageManifest
    lessons: list[PackageLesson]
    archive: zipfile.ZipFile

    def media(self, name: str) -> bytes | None:
        try:
            return self.archive.read(name)
        except KeyError:
            return None


def read_package(raw: bytes) -> Package:
    """Файл уроков после проверки размера, путей, формата и версии."""
    if len(raw) > MAX_PACKAGE_BYTES:
        raise ProjectDomainError("Файл уроков больше 200 МБ", status=413,
                                 code="lesson_package_too_large")
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
        entries = archive.infolist()
    except zipfile.BadZipFile as error:
        raise _corrupt("Это не файл уроков Tentex: архив не читается") from error
    if sum(item.file_size for item in entries) > MAX_UNPACKED_BYTES:
        raise _corrupt("Файл уроков распаковывается в слишком большой объём")
    for item in entries:
        path = PurePosixPath(item.filename)
        if path.is_absolute() or ".." in path.parts or "\\" in item.filename:
            raise _corrupt("В файле уроков недопустимый путь")
    try:
        manifest = PackageManifest.model_validate_json(archive.read("manifest.json"))
    except (KeyError, ValidationError, ValueError) as error:
        raise _corrupt("В файле уроков нет описания или оно повреждено") from error
    if manifest.format != FORMAT:
        raise ProjectDomainError("Это не файл уроков Tentex", status=422,
                                 code="lesson_package_incompatible")
    if manifest.version > FORMAT_VERSION:
        raise ProjectDomainError(
            "Файл уроков сделан более новой версией Tentex — обновите приложение",
            status=422, code="lesson_package_incompatible",
            context={"version": manifest.version, "supported": FORMAT_VERSION},
        )
    try:
        records = json.loads(archive.read("lessons.json"))
        lessons = [PackageLesson.model_validate(item) for item in records]
    except (KeyError, ValidationError, ValueError, TypeError) as error:
        raise _corrupt("Уроки в файле повреждены") from error
    if not lessons or len(lessons) > MAX_LESSONS:
        raise _corrupt("В файле нет уроков")
    return Package(manifest, lessons, archive)


# --- предпросмотр ---------------------------------------------------------------------


MaterialStatus = Literal["project", "library", "missing"]


class LessonImportMaterialRead(ApiModel):
    key: str
    name: str
    status: MaterialStatus
    material_id: UUID | None
    pieces: int


class LessonImportLessonRead(ApiModel):
    key: str
    title: str
    topic_titles: list[str]
    blocks: int
    pieces: int
    tasks: int
    program_node_id: UUID | None


class LessonImportPreviewRead(ApiModel):
    source_project: str
    exported_at: str | None
    lessons: list[LessonImportLessonRead]
    materials: list[LessonImportMaterialRead]


class LessonImportLessonChoice(ApiModel):
    key: str
    program_node_id: UUID


class LessonImportOptions(ApiModel):
    lessons: list[LessonImportLessonChoice] = Field(min_length=1, max_length=MAX_LESSONS)
    # Ключ материала файла → материал этой установки; нет ключа или null — снимок текста.
    materials: dict[str, UUID | None] = Field(default_factory=dict)


def parse_options(raw: str) -> LessonImportOptions:
    try:
        return LessonImportOptions.model_validate_json(raw)
    except ValidationError as error:
        raise ProjectDomainError("Выбор тем для импорта не разобрался", status=422,
                                 code="lesson_import_options") from error


class LessonImportResult(ApiModel):
    lessons: list[LessonSummaryRead]
    latest_undoable_action: LatestUndoableAction | None
    linked_pieces: int
    snapshot_pieces: int
    attached_materials: int


def _study_nodes(session: Session, project_id: UUID) -> list[tuple[ProgramNode, list[str]]]:
    """Темы программы с путём разделов: по пути различаются одноимённые темы."""
    program = _load_program(session, project_id)
    path: list[str] = []
    result: list[tuple[ProgramNode, list[str]]] = []
    for node, depth in program.ordered:
        del path[depth:]
        if node.node_type in STUDY_NODE_TYPES:
            result.append((node, list(path)))
        path.append(node.title)
    return result


def propose_topic(nodes: list[tuple[ProgramNode, list[str]]], topic: PackageTopic | None
                  ) -> UUID | None:
    """Тема этого проекта для урока: совпала формулировка, при равенстве — путь."""
    if topic is None:
        return None
    matches = [(node, path) for node, path in nodes if titles_match(node.title, topic.title)]
    if not matches:
        return None
    for node, path in matches:
        if [item.casefold() for item in path[-len(topic.path):]] == \
                [item.casefold() for item in topic.path] and topic.path:
            return node.id
    return matches[0][0].id


def _material_status(session: Session, project_id: UUID, item: PackageMaterial
                     ) -> tuple[MaterialStatus, UUID | None]:
    material = session.scalar(select(Material).where(Material.sha256 == item.sha256))
    if material is None:
        return "missing", None
    if session.get(ProjectMaterial, (project_id, material.id)) is not None:
        return "project", material.id
    return "library", material.id


def preview_package(session: Session, project_id: UUID, package: Package
                    ) -> LessonImportPreviewRead:
    _require_lessons_project(session, project_id, writable=True)
    nodes = _study_nodes(session, project_id)
    pieces: dict[str, int] = {}
    lessons: list[LessonImportLessonRead] = []
    for lesson in package.lessons:
        refs = [ref for block in lesson.blocks for ref in block.refs
                if block.kind == LessonBlockKind.SOURCE and ref.role == LessonRefRole.CONTENT]
        for ref in refs:
            if ref.material:
                pieces[ref.material] = pieces.get(ref.material, 0) + 1
        lessons.append(LessonImportLessonRead(
            key=lesson.key, title=lesson.title,
            topic_titles=[topic.title for topic in lesson.topics],
            blocks=len(lesson.blocks), pieces=len(refs),
            tasks=sum(1 for block in lesson.blocks if block.task is not None),
            program_node_id=propose_topic(nodes, lesson.topics[0] if lesson.topics else None),
        ))
    materials = []
    for item in package.manifest.materials:
        status, material_id = _material_status(session, project_id, item)
        materials.append(LessonImportMaterialRead(
            key=item.key, name=item.name, status=status, material_id=material_id,
            pieces=pieces.get(item.key, 0),
        ))
    session.rollback()
    return LessonImportPreviewRead(
        source_project=str(package.manifest.project.get("name") or ""),
        exported_at=package.manifest.exported_at, lessons=lessons, materials=materials,
    )


# --- импорт -----------------------------------------------------------------------------


@dataclass(slots=True)
class _Import:
    session: Session
    project_id: UUID
    package: Package
    materials: dict[str, tuple[Material, ProjectMaterial]] = field(default_factory=dict)
    sha_of: dict[str, str] = field(default_factory=dict)
    binding_ids: list[UUID] = field(default_factory=list)
    written: list[Path] = field(default_factory=list)
    linked: int = 0
    snapshots: int = 0
    attached: int = 0

    def prepare_materials(self, choices: dict[str, UUID | None]) -> None:
        """Выбранные материалы; материал Библиотеки вне проекта подключается к нему."""
        for item in self.package.manifest.materials:
            self.sha_of[item.key] = item.sha256
            material_id = choices.get(item.key)
            if material_id is None:
                continue
            material = self.session.get(Material, material_id)
            if material is None:
                raise ProjectDomainError("Материал для сопоставления не найден", status=422,
                                         code="lesson_import_material")
            link = self.session.get(ProjectMaterial, (self.project_id, material.id))
            if link is None:
                link = ProjectMaterial(
                    project_id=self.project_id, material_id=material.id,
                    source_role=SourceRole.ADDITIONAL, priority=0, affects_program=True,
                    purposes=[MaterialPurpose.STUDY_SOURCE.value], created_at=utc_now(),
                )
                self.session.add(link)
                self.session.flush()
                self.attached += 1
            self.materials[item.key] = (material, link)

    def lesson(self, record: PackageLesson, node: ProgramNode,
               nodes: list[tuple[ProgramNode, list[str]]]) -> Lesson:
        now = utc_now()
        build = dict(record.build or {})
        lesson = Lesson(
            id=uuid4(), project_id=self.project_id, title=record.title[:500],
            goal=record.goal, status=record.status, duration_minutes=record.duration_minutes,
            revision=1, build_meta=build or None, created_at=now, updated_at=now,
        )
        self.session.add(lesson)
        # Первая тема — выбранная; остальные темы урока — если нашлись по формулировке.
        topic_ids: list[UUID] = [node.id]
        for topic in record.topics[1:]:
            other = propose_topic(nodes, topic)
            if other is not None and other not in topic_ids:
                topic_ids.append(other)
        titles = {item.id: item.title for item, _ in nodes}
        for order, topic_id in enumerate(topic_ids):
            self.session.add(LessonTopic(
                lesson_id=lesson.id, program_node_id=topic_id, project_id=self.project_id,
                sort_order=order, topic_title_snapshot=titles.get(topic_id, node.title),
            ))
        self.session.flush()
        topic_of = {0: node.id}
        for index, topic in enumerate(record.topics[1:], start=1):
            found = propose_topic(nodes, topic)
            if found in topic_ids:
                topic_of[index] = found
        for order, item in enumerate(record.blocks):
            self._block(lesson, item, order, topic_of.get(item.topic or 0, node.id))
        self.session.flush()
        sync_lesson_tasks(self.session, lesson.id)
        return lesson

    def _block(self, lesson: Lesson, item: PackageBlock, order: int, node_id: UUID) -> None:
        now = utc_now()
        block = LessonBlock(
            id=uuid4(), lesson_id=lesson.id, sort_order=order, kind=item.kind,
            variant=item.variant, body_md=item.body_md, origin=item.origin, basis=item.basis,
            collapsed=item.collapsed, created_at=now, updated_at=now,
            bound_program_node_id=node_id if item.kind == LessonBlockKind.SOURCE else None,
        )
        if item.kind == LessonBlockKind.MEDIA:
            block.media_path = self._media(item.media or {})
            if block.media_path is None:
                return
        if item.kind == LessonBlockKind.ACTIVITY:
            if item.task is None:
                return
            block.activity_id = self._task(lesson, item.task, node_id)
        self.session.add(block)
        self.session.flush()
        for ref in item.refs:
            self._ref(block, ref, node_id)

    def _media(self, media: dict[str, Any]) -> str | None:
        url = media.get("url")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            return url[:2000]
        name = media.get("file")
        if not isinstance(name, str):
            return None
        suffix = Path(name).suffix.lower()
        data = self.package.media(name)
        if suffix not in IMAGE_SUFFIXES or not data:
            return None
        relative = Path("lessons") / str(self.project_id) / f"{uuid4().hex}{suffix}"
        target = material_path(relative.as_posix())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        self.written.append(target)
        return relative.as_posix()

    def _task(self, lesson: Lesson, task: PackageTask, node_id: UUID) -> UUID:
        activity = Activity(project_id=self.project_id, program_node_id=node_id,
                            kind=ActivityKind.STUDY_TASK, evidence_strength=1.0,
                            origin=ActivityOrigin.LESSON)
        self.session.add(activity)
        self.session.flush()
        self.session.add(StudyTask(
            activity_id=activity.id, project_id=self.project_id, lesson_id=lesson.id,
            form=task.form, prompt_md=task.prompt_md, payload=task.payload,
            answer_key=task.answer_key, reference_md=task.reference_md,
            explanation_md=task.explanation_md, hint_md=task.hint_md,
            difficulty=task.difficulty, basis=task.basis, supporting_fragment_ids=[],
            source_snapshot=task.source_snapshot,
        ))
        return activity.id

    def _ref(self, block: LessonBlock, ref: PackageRef, node_id: UUID) -> None:
        anchors = {"from": ref.from_, "to": ref.to}
        row = LessonSourceRef(
            id=uuid4(), block_id=block.id, role=ref.role, material_id=None,
            source_name_snapshot=ref.name[:500], material_revision=None,
            page_from=ref.page_from, page_to=max(ref.page_to, ref.page_from),
            region_bbox=ref.region_bbox, always_pages=ref.always_pages,
            boundary_shifted=False, citation_label=ref.citation_label,
        )
        chosen = self.materials.get(ref.material) if ref.material else None
        resolved = resolve_bounds(self.session, chosen[0], row.page_from, row.page_to, anchors) \
            if chosen else None
        if chosen is None or resolved is None:
            row.snapshot_md = ref.snapshot_md
            row.material_sha256 = self.sha_of.get(ref.material or "")
            row.snapshot_anchors = anchors
            self.session.add(row)
            if ref.role == LessonRefRole.CONTENT:
                self.snapshots += 1
            return
        material, link = chosen
        bounds = resolved.bounds
        row.material_id = material.id
        row.source_name_snapshot = _source_name(material, link, ref.name)
        row.material_revision = material.active_parse_revision or None
        row.page_from, row.page_to = bounds.page_from, bounds.page_to
        row.from_fragment_id, row.to_fragment_id = bounds.from_fragment_id, bounds.to_fragment_id
        row.boundary_shifted = resolved.shifted
        self.session.add(row)
        if ref.role != LessonRefRole.CONTENT:
            return
        self.linked += 1
        order = refs_module.load_order(self.session, material, bounds.page_from, bounds.page_to)
        if ref.region_bbox is not None:
            fragment_ids = refs_module.fragments_in_region(
                self.session, material, bounds.page_from, ref.region_bbox)
        else:
            fragment_ids = refs_module.content_fragment_ids(order, bounds)
        self.binding_ids += _bind_fragments(
            self.session, self.project_id, node_id, material.id, fragment_ids, block.origin)


def import_package(session: Session, project_id: UUID, package: Package,
                   options: LessonImportOptions) -> LessonImportResult:
    by_key = {lesson.key: lesson for lesson in package.lessons}
    chosen = []
    for choice in options.lessons:
        record = by_key.get(choice.key)
        if record is None:
            raise _corrupt("Урока из выбора нет в файле")
        chosen.append((record, choice.program_node_id))
    work = _Import(session, project_id, package)
    try:
        return _import(session, project_id, work, chosen, options)
    except Exception:
        # Транзакция откатилась, а файлы изображений уже на диске — убираем их.
        for path in work.written:
            path.unlink(missing_ok=True)
        raise


def _import(session: Session, project_id: UUID, work: _Import,
            chosen: list[tuple[PackageLesson, UUID]], options: LessonImportOptions
            ) -> LessonImportResult:
    with project_write_transaction(session, project_id):
        project = _require_lessons_project(session, project_id, writable=True)
        nodes = _study_nodes(session, project_id)
        work.prepare_materials(options.materials)
        lesson_ids: list[UUID] = []
        for record, node_id in chosen:
            node = _require_study_node(session, project_id, node_id)
            lesson_ids.append(work.lesson(record, node, nodes).id)
        session.add(ProjectActionLog(
            project_id=project.id, action_type=ACTION_LESSON_BULK, phase="active",
            payload_version=1, target_title=f"Импорт уроков: {len(lesson_ids)}",
            inverse_data={"lesson_ids": [str(item) for item in lesson_ids],
                          "binding_ids": [str(item) for item in work.binding_ids]},
        ))
        session.flush()
        created = set(lesson_ids)
        action = _latest_action(session, project_id)
        return LessonImportResult(
            lessons=[summary for summary in lessons_overview(session, project_id).lessons
                     if summary.id in created],
            latest_undoable_action=(LatestUndoableAction.model_validate(action)
                                    if action is not None else None),
            linked_pieces=work.linked, snapshot_pieces=work.snapshots,
            attached_materials=work.attached,
        )
