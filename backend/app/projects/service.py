from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.materials.schemas import MaterialPurpose
from app.models import (
    Attempt,
    ChatSession,
    GoalPassport,
    Material,
    NodeType,
    ProgramNode,
    Project,
    ProjectMaterial,
    ProjectStatus,
    ReferenceAnswer,
    TemplateKey,
    WizardDraft,
    WorkspaceState,
    WorkspaceVariant,
    utc_now,
)
from app.projects import program
from app.projects.answers import STUDY_NODE_TYPES
from app.projects.errors import (
    ProjectConflictError,
    ProjectInvariantError,
    ProjectNotFoundError,
)
from app.projects.importer import ExamImportError, parse_exam_program
from app.projects.schemas import (
    ExamImportCounts,
    ExamImportResult,
    ExamImportWrite,
    GoalPassportRead,
    ProjectDetail,
    ProjectOrderWrite,
    ProjectRead,
    ProjectSettingsResult,
    ProjectSettingsWrite,
    ProjectStats,
    ProjectSummary,
    WizardDraftCreate,
    WizardDraftDetail,
    WizardDraftRead,
    WizardDraftSummary,
    WizardDraftWrite,
    WorkspaceStateRead,
    WorkspaceStateWrite,
)


def _wizard_detail(session: Session, project_id: UUID) -> WizardDraftDetail:
    project = session.get(Project, project_id)
    draft = session.get(WizardDraft, project_id)
    if project is None or draft is None or project.status != ProjectStatus.DRAFT:
        raise ProjectNotFoundError("Черновик проекта не найден")
    goal_passport = session.get(GoalPassport, project_id)
    return WizardDraftDetail(
        project=ProjectRead.model_validate(project),
        draft=WizardDraftRead.model_validate(draft),
        goal_passport=(
            GoalPassportRead.model_validate(goal_passport) if goal_passport is not None else None
        ),
        program=program.read_program(session, project_id),
        latest_undoable_action=program.latest_undoable_action(
            session, project_id, "draft"
        ),
    )


def _project_detail(session: Session, project_id: UUID) -> ProjectDetail:
    project = session.get(Project, project_id)
    if project is None or project.status == ProjectStatus.DRAFT:
        raise ProjectNotFoundError()
    goal_passport = session.get(GoalPassport, project_id)
    workspace_state = session.get(WorkspaceState, project_id)
    return ProjectDetail(
        project=ProjectRead.model_validate(project),
        goal_passport=(
            GoalPassportRead.model_validate(goal_passport) if goal_passport is not None else None
        ),
        program=program.read_program(session, project_id),
        workspace_state=(
            WorkspaceStateRead.model_validate(workspace_state)
            if workspace_state is not None
            else None
        ),
        latest_undoable_action=program.latest_undoable_action(
            session, project_id, "active"
        ),
    )


def create_wizard_draft(session: Session, command: WizardDraftCreate) -> WizardDraftDetail:
    if command.template_key == TemplateKey.FREE:
        raise ProjectConflictError(
            "Свободное изучение появится на этапе 7", code="unsupported_template"
        )
    variant = (
        WorkspaceVariant.EXAM
        if command.template_key == TemplateKey.EXAM
        else WorkspaceVariant.TEXTBOOK
    )
    with session.begin():
        project = Project(
            template_key=command.template_key,
            workspace_variant=variant,
            status=ProjectStatus.DRAFT,
        )
        session.add(project)
        session.flush()
        session.add(WizardDraft(project_id=project.id))
        session.flush()
        return _wizard_detail(session, project.id)


def list_wizard_drafts(session: Session) -> list[WizardDraftSummary]:
    rows = session.execute(
        select(Project, WizardDraft)
        .join(WizardDraft, WizardDraft.project_id == Project.id)
        .where(Project.status == ProjectStatus.DRAFT)
        .order_by(WizardDraft.updated_at.desc())
    )
    return [
        WizardDraftSummary(
            project_id=project_row.id,
            template_key=project_row.template_key,
            workspace_variant=project_row.workspace_variant,
            name=project_row.name,
            current_step=draft.current_step,
            max_completed_step=draft.max_completed_step,
            revision=draft.revision,
            updated_at=draft.updated_at,
        )
        for project_row, draft in rows
    ]


def get_wizard_draft(session: Session, project_id: UUID) -> WizardDraftDetail:
    return _wizard_detail(session, project_id)


def save_wizard_draft(
    session: Session, project_id: UUID, command: WizardDraftWrite
) -> WizardDraftDetail:
    with session.begin():
        project = session.get(Project, project_id)
        if project is None:
            raise ProjectNotFoundError()
        if project.status != ProjectStatus.DRAFT:
            raise ProjectConflictError(
                "Активный проект нельзя сохранить как черновик",
                context={"current_status": project.status.value},
            )
        now = utc_now()
        result = session.execute(
            update(WizardDraft)
            .where(
                WizardDraft.project_id == project_id,
                WizardDraft.revision == command.expected_revision,
            )
            .values(
                revision=WizardDraft.revision + 1,
                current_step=command.current_step,
                max_completed_step=command.max_completed_step,
                schema_version=command.schema_version,
                state=command.state,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            current = session.scalar(
                select(WizardDraft.revision).where(WizardDraft.project_id == project_id)
            )
            raise ProjectConflictError(
                "Черновик уже изменён в другой вкладке",
                code="stale_draft_revision",
                context={"current_draft_revision": current},
            )
        project_data = command.project.model_dump(mode="python", exclude={"enabled_modules"})
        for field, value in project_data.items():
            setattr(project, field, value.value if hasattr(value, "value") else value)
        project.enabled_modules = [item.value for item in command.project.enabled_modules]
        project.updated_at = now

        if command.goal_passport is not None:
            goal_passport = session.get(GoalPassport, project_id)
            if goal_passport is None:
                goal_passport = GoalPassport(project_id=project_id)
                session.add(goal_passport)
            for field, value in command.goal_passport.model_dump(mode="python").items():
                setattr(goal_passport, field, value)
            goal_passport.updated_at = now
        session.flush()
        return _wizard_detail(session, project_id)


def delete_wizard_draft(session: Session, project_id: UUID, expected_revision: int) -> None:
    with session.begin():
        project = session.get(Project, project_id)
        if project is None:
            raise ProjectNotFoundError("Черновик проекта не найден")
        if project.status != ProjectStatus.DRAFT:
            raise ProjectConflictError(
                "Удалить можно только черновик",
                context={"current_status": project.status.value},
            )
        draft = session.get(WizardDraft, project_id)
        if draft is None:
            raise ProjectNotFoundError("Черновик проекта не найден")
        if draft.revision != expected_revision:
            raise ProjectConflictError(
                "Черновик уже изменён в другой вкладке",
                code="stale_draft_revision",
                context={"current_draft_revision": draft.revision},
            )
        program.delete_program_tree(session, project_id)
        session.delete(project)


def import_exam_program(
    session: Session, project_id: UUID, command: ExamImportWrite
) -> ExamImportResult:
    passport = session.get(GoalPassport, project_id)
    expected_item_count = passport.expected_item_count if passport else None
    session.rollback()
    try:
        parsed = parse_exam_program(
            command.raw_text, command.exam_format, expected_item_count=expected_item_count
        )
    except ExamImportError as error:
        raise ProjectInvariantError(str(error)) from error
    result = program.replace_draft_program(
        session,
        project_id,
        expected_draft_revision=command.expected_revision,
        expected_program_revision=command.expected_program_revision,
        parsed=parsed,
    )
    assert result.draft_revision is not None
    return ExamImportResult(
        revision=result.draft_revision,
        counts=ExamImportCounts(
            tickets=parsed.tickets,
            questions=parsed.questions,
            tasks=parsed.tasks,
            subpoints=parsed.subpoints,
        ),
        warnings=parsed.warnings,
        program=result.program,
        latest_undoable_action=result.latest_undoable_action,
    )


def _normalize_active_order(session: Session) -> int:
    active = list(
        session.scalars(
            select(Project)
            .where(Project.status == ProjectStatus.ACTIVE)
            .order_by(Project.sort_order, Project.created_at, Project.id)
        )
    )
    for index, project in enumerate(active):
        project.sort_order = index
    return len(active)


def activate_wizard_draft(
    session: Session, project_id: UUID, expected_revision: int
) -> ProjectDetail:
    with session.begin():
        project = session.get(Project, project_id)
        if project is None:
            raise ProjectNotFoundError()
        if project.status == ProjectStatus.ACTIVE:
            return _project_detail(session, project_id)
        if project.status != ProjectStatus.DRAFT:
            raise ProjectConflictError(
                "Архивный или завершённый проект нельзя активировать",
                context={"current_status": project.status.value},
            )
        draft = session.get(WizardDraft, project_id)
        if draft is None:
            raise ProjectNotFoundError("Черновик проекта не найден")
        if draft.revision != expected_revision:
            raise ProjectConflictError(
                "Черновик уже изменён в другой вкладке",
                code="stale_draft_revision",
                context={"current_draft_revision": draft.revision},
            )
        goal_passport = session.get(GoalPassport, project_id)
        required_goal_fields = (
            "subject",
            "purpose",
            "starting_level",
            "target_outcome",
            "study_format",
        )
        if project.name is None or not project.name.strip():
            raise ProjectConflictError("Перед активацией укажите название проекта")
        if goal_passport is None or any(
            getattr(goal_passport, field) in {None, ""} for field in required_goal_fields
        ):
            raise ProjectConflictError("Перед активацией заполните паспорт цели")
        assert goal_passport.target_outcome is not None
        program.prepare_for_activation(session, project_id, goal_passport.target_outcome)
        now = utc_now()
        project.sort_order = _normalize_active_order(session)
        project.status = ProjectStatus.ACTIVE
        project.status_changed_at = now
        project.updated_at = now
        session.execute(delete(WizardDraft).where(WizardDraft.project_id == project_id))
        session.flush()
        return _project_detail(session, project_id)


def list_projects(session: Session) -> list[ProjectSummary]:
    projects = session.scalars(
        select(Project)
        .where(Project.status != ProjectStatus.DRAFT)
        .order_by(Project.status, Project.sort_order, Project.name, Project.id)
    )
    return [ProjectSummary.model_validate(project) for project in projects]


def list_project_stats(session: Session) -> list[ProjectStats]:
    """Сводка для карточек главного экрана.

    Пять сгруппированных запросов на все проекты сразу: карточек может быть
    сколько угодно, но обращений к базе от этого не прибавляется.
    """
    projects = list(
        session.scalars(select(Project).where(Project.status != ProjectStatus.DRAFT))
    )
    if not projects:
        return []

    study_node = (
        ProgramNode.node_type.in_(STUDY_NODE_TYPES),
        ProgramNode.is_in_current_program.is_(True),
        ProgramNode.is_archived.is_(False),
    )
    node_counts = dict(
        session.execute(
            select(ProgramNode.project_id, func.count())
            .where(*study_node)
            .group_by(ProgramNode.project_id)
        ).all()
    )
    # Граница «с эталоном» — та же, что у with_answer в карте покрытия: активная
    # строка ответа у узла текущей программы. Пустой текст запрещён констрейнтом.
    answer_counts = dict(
        session.execute(
            select(ReferenceAnswer.project_id, func.count())
            .join(
                ProgramNode,
                (ProgramNode.project_id == ReferenceAnswer.project_id)
                & (ProgramNode.id == ReferenceAnswer.program_node_id),
            )
            .where(ReferenceAnswer.is_active.is_(True), *study_node)
            .group_by(ReferenceAnswer.project_id)
        ).all()
    )
    # Документ, из которого только импортированы вопросы (exam_structure),
    # источником для занятий не считается — это служебный файл, а не то,
    # что разносится по темам. Материал с ещё одним назначением всё же
    # учитывается: в источники не входит только «чистый» вопросник.
    material_rows = session.execute(
        select(ProjectMaterial.project_id, ProjectMaterial.purposes, Material.page_count).join(
            Material, Material.id == ProjectMaterial.material_id
        )
    ).all()
    material_counts: dict[UUID, tuple[int, int | None]] = {}
    for project_id, purposes, page_count in material_rows:
        if purposes == [MaterialPurpose.EXAM_STRUCTURE.value]:
            continue
        count, pages = material_counts.get(project_id, (0, None))
        if page_count is not None:
            pages = (pages or 0) + page_count
        material_counts[project_id] = (count + 1, pages)
    attempt_activity = dict(
        session.execute(
            select(Attempt.project_id, func.max(Attempt.created_at)).group_by(Attempt.project_id)
        ).all()
    )
    chat_activity = dict(
        session.execute(
            select(ChatSession.project_id, func.max(ChatSession.updated_at)).group_by(
                ChatSession.project_id
            )
        ).all()
    )

    stats: list[ProjectStats] = []
    for item in projects:
        materials, pages = material_counts.get(item.id, (0, None))
        is_exam = item.template_key == TemplateKey.EXAM
        is_textbook = item.template_key == TemplateKey.TEXTBOOK
        # Свободное изучение приезжает на этапе 7: считать по нему нечего, и ноль
        # вместо метрики был бы неправдой (FR-P3).
        touched = [
            moment
            for moment in (attempt_activity.get(item.id), chat_activity.get(item.id))
            if moment is not None
        ]
        stats.append(
            ProjectStats(
                project_id=item.id,
                program_nodes=(node_counts.get(item.id, 0) if is_exam or is_textbook else None),
                reference_answers=(answer_counts.get(item.id, 0) if is_exam else None),
                materials=materials,
                material_pages=(pages if is_textbook else None),
                last_activity_at=_latest(touched),
            )
        )
    return stats


def _latest(moments: list[datetime]) -> datetime | None:
    """Пусто — значит занятий ещё не было. `Project.updated_at` сюда не годится:
    он сдвигается от перестановки карточек мышью."""
    return max(moments) if moments else None


def get_project(session: Session, project_id: UUID) -> ProjectDetail:
    return _project_detail(session, project_id)


def update_project_settings(
    session: Session, project_id: UUID, command: ProjectSettingsWrite
) -> ProjectSettingsResult:
    with session.begin():
        project = session.get(Project, project_id)
        if project is None or project.status == ProjectStatus.DRAFT:
            raise ProjectNotFoundError()
        if project.status != ProjectStatus.ACTIVE:
            raise ProjectConflictError(
                "Архивный или завершённый проект нельзя изменять",
                code="project_read_only",
                context={"current_status": project.status.value},
            )
        now = utc_now()
        project_data = command.project.model_dump(mode="python", exclude={"enabled_modules"})
        for field, value in project_data.items():
            setattr(project, field, value.value if hasattr(value, "value") else value)
        project.enabled_modules = [module.value for module in command.project.enabled_modules]
        project.updated_at = now
        goal_passport = session.get(GoalPassport, project_id)
        if goal_passport is None:
            goal_passport = GoalPassport(project_id=project_id)
            session.add(goal_passport)
        for field, value in command.goal_passport.model_dump(mode="python").items():
            setattr(goal_passport, field, value)
        goal_passport.updated_at = now
        session.flush()
        return ProjectSettingsResult(
            project=ProjectRead.model_validate(project),
            goal_passport=GoalPassportRead.model_validate(goal_passport),
        )


def save_project_order(
    session: Session, command: ProjectOrderWrite
) -> list[ProjectSummary]:
    with session.begin():
        active = list(
            session.scalars(select(Project).where(Project.status == ProjectStatus.ACTIVE))
        )
        active_ids = {project.id for project in active}
        if len(command.project_ids) != len(set(command.project_ids)):
            raise ProjectInvariantError("Порядок проектов не должен содержать дубли")
        if set(command.project_ids) != active_ids:
            raise ProjectInvariantError("Порядок должен содержать каждый активный проект один раз")
        by_id = {project.id: project for project in active}
        for index, project_id in enumerate(command.project_ids):
            by_id[project_id].sort_order = index
            by_id[project_id].updated_at = utc_now()
        session.flush()
        return [ProjectSummary.model_validate(by_id[item]) for item in command.project_ids]


def archive_project(session: Session, project_id: UUID) -> ProjectSummary:
    with session.begin():
        project = session.get(Project, project_id)
        if project is None or project.status == ProjectStatus.DRAFT:
            raise ProjectNotFoundError()
        if project.status == ProjectStatus.ARCHIVED:
            return ProjectSummary.model_validate(project)
        if project.status != ProjectStatus.ACTIVE:
            raise ProjectConflictError(
                "Завершённый проект нельзя архивировать",
                context={"current_status": project.status.value},
            )
        now = utc_now()
        project.status = ProjectStatus.ARCHIVED
        project.status_changed_at = now
        project.updated_at = now
        session.flush()
        _normalize_active_order(session)
        session.flush()
        return ProjectSummary.model_validate(project)


def restore_project(session: Session, project_id: UUID) -> ProjectSummary:
    with session.begin():
        project = session.get(Project, project_id)
        if project is None or project.status == ProjectStatus.DRAFT:
            raise ProjectNotFoundError()
        if project.status == ProjectStatus.ACTIVE:
            return ProjectSummary.model_validate(project)
        if project.status != ProjectStatus.ARCHIVED:
            raise ProjectConflictError(
                "Завершённый проект нельзя вернуть в работу",
                context={"current_status": project.status.value},
            )
        now = utc_now()
        project.sort_order = _normalize_active_order(session)
        project.status = ProjectStatus.ACTIVE
        project.status_changed_at = now
        project.updated_at = now
        session.flush()
        return ProjectSummary.model_validate(project)


def delete_project(session: Session, project_id: UUID) -> None:
    """Безвозвратно удаляет живой проект, но не общие файлы библиотеки."""
    with session.begin():
        project = session.get(Project, project_id)
        if project is None or project.status == ProjectStatus.DRAFT:
            raise ProjectNotFoundError()
        was_active = project.status == ProjectStatus.ACTIVE
        # Самоссылка дерева использует RESTRICT, поэтому одного CASCADE от
        # projects недостаточно: сначала удаляем листья, затем сам проект.
        program.delete_program_tree(session, project_id)
        session.delete(project)
        session.flush()
        if was_active:
            _normalize_active_order(session)
            session.flush()


def save_workspace_state(
    session: Session, project_id: UUID, command: WorkspaceStateWrite
) -> WorkspaceStateRead:
    with session.begin():
        project = session.get(Project, project_id)
        if project is None:
            raise ProjectNotFoundError()
        if project.status not in {ProjectStatus.DRAFT, ProjectStatus.ACTIVE}:
            raise ProjectConflictError(
                "Раскладку архивного или завершённого проекта нельзя изменять",
                code="project_read_only",
                context={"current_status": project.status.value},
            )
        referenced_ids = list(
            dict.fromkeys(
                [command.layout.selected_node_id, *command.layout.expanded_node_ids]
            )
        )
        referenced_ids = [node_id for node_id in referenced_ids if node_id is not None]
        found = {
            node.id: node
            for node in session.scalars(
                select(ProgramNode).where(
                    ProgramNode.project_id == project_id,
                    ProgramNode.id.in_(referenced_ids),
                )
            )
        } if referenced_ids else {}
        if set(found) != set(referenced_ids):
            raise ProjectInvariantError("Раскладка ссылается на узел другого проекта")
        if command.layout.selected_node_id is not None:
            selected = found[command.layout.selected_node_id]
            if (
                selected.node_type not in {NodeType.TOPIC, NodeType.SUBPOINT}
                or not selected.is_in_current_program
                or selected.is_archived
            ):
                raise ProjectInvariantError("Выбранным может быть только текущий изучаемый узел")
        layout = command.layout.model_dump(mode="json")
        layout["expanded_node_ids"] = [
            str(node_id) for node_id in dict.fromkeys(command.layout.expanded_node_ids)
        ]
        workspace_state = session.get(WorkspaceState, project_id)
        if workspace_state is None:
            workspace_state = WorkspaceState(project_id=project_id)
            session.add(workspace_state)
        workspace_state.schema_version = command.schema_version
        workspace_state.layout = layout
        workspace_state.updated_at = utc_now()
        session.flush()
        return WorkspaceStateRead.model_validate(workspace_state)
