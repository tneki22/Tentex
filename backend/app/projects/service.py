from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models import (
    GoalPassport,
    NodeType,
    ProgramNode,
    Project,
    ProjectStatus,
    WizardDraft,
    WorkspaceState,
    utc_now,
)
from app.projects.schemas import (
    GoalPassportRead,
    ProgramNodeCreate,
    ProgramNodeRead,
    ProgramNodeUpdate,
    ProjectDetail,
    ProjectRead,
    ProjectSettingsWrite,
    ProjectSummary,
    WizardDraftCreate,
    WizardDraftDetail,
    WizardDraftRead,
    WizardDraftSummary,
    WizardDraftWrite,
    WorkspaceStateRead,
    WorkspaceStateWrite,
)


class ProjectNotFoundError(Exception):
    pass


class ProjectConflictError(Exception):
    pass


class ProjectInvariantError(Exception):
    pass


def _nodes(session: Session, project_id: UUID) -> list[ProgramNode]:
    return list(
        session.scalars(
            select(ProgramNode)
            .where(ProgramNode.project_id == project_id)
            .order_by(
                ProgramNode.parent_id.is_not(None),
                ProgramNode.parent_id,
                ProgramNode.sort_order,
                ProgramNode.id,
            )
        )
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
        program_nodes=[
            ProgramNodeRead.model_validate(node) for node in _nodes(session, project_id)
        ],
    )


def _project_detail(session: Session, project_id: UUID) -> ProjectDetail:
    project = session.get(Project, project_id)
    if project is None or project.status == ProjectStatus.DRAFT:
        raise ProjectNotFoundError("Проект не найден")
    goal_passport = session.get(GoalPassport, project_id)
    workspace_state = session.get(WorkspaceState, project_id)
    return ProjectDetail(
        project=ProjectRead.model_validate(project),
        goal_passport=(
            GoalPassportRead.model_validate(goal_passport) if goal_passport is not None else None
        ),
        program_nodes=[
            ProgramNodeRead.model_validate(node) for node in _nodes(session, project_id)
        ],
        workspace_state=(
            WorkspaceStateRead.model_validate(workspace_state)
            if workspace_state is not None
            else None
        ),
    )


def create_wizard_draft(session: Session, command: WizardDraftCreate) -> WizardDraftDetail:
    with session.begin():
        project = Project(
            template_key=command.template_key,
            workspace_variant=command.workspace_variant,
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
            project_id=project.id,
            template_key=project.template_key,
            workspace_variant=project.workspace_variant,
            name=project.name,
            current_step=draft.current_step,
            max_completed_step=draft.max_completed_step,
            revision=draft.revision,
            updated_at=draft.updated_at,
        )
        for project, draft in rows
    ]


def get_wizard_draft(session: Session, project_id: UUID) -> WizardDraftDetail:
    return _wizard_detail(session, project_id)


def save_wizard_draft(
    session: Session, project_id: UUID, command: WizardDraftWrite
) -> WizardDraftDetail:
    with session.begin():
        project = session.get(Project, project_id)
        if project is None:
            raise ProjectNotFoundError("Проект не найден")
        if project.status != ProjectStatus.DRAFT:
            raise ProjectConflictError("Активный проект нельзя сохранить как черновик")

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
        )
        if result.rowcount != 1:
            raise ProjectConflictError("Черновик уже изменён в другой вкладке")

        project_data = command.project.model_dump(mode="python")
        project_data["enabled_modules"] = [item.value for item in command.project.enabled_modules]
        for field, value in project_data.items():
            setattr(project, field, value)
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


def _validate_tree(parent_by_id: dict[UUID, UUID | None]) -> None:
    depths: dict[UUID, int] = {}
    for node_id in parent_by_id:
        path: list[UUID] = []
        seen: set[UUID] = set()
        current = node_id
        while current not in depths:
            if current in seen:
                raise ProjectInvariantError("В программе обнаружен цикл")
            seen.add(current)
            path.append(current)
            parent_id = parent_by_id.get(current)
            if parent_id is None:
                base_depth = 0
                break
            if parent_id not in parent_by_id:
                raise ProjectInvariantError("Родитель узла отсутствует в этом проекте")
            current = parent_id
        else:
            base_depth = depths[current]

        for path_node_id in reversed(path):
            base_depth += 1
            if base_depth > 4:
                raise ProjectInvariantError("Глубина программы не может превышать четыре уровня")
            depths[path_node_id] = base_depth


def _validate_parent(
    session: Session,
    project_id: UUID,
    node_id: UUID | None,
    parent_id: UUID | None,
) -> None:
    if parent_id is None:
        return
    current_id = parent_id
    depth = 1
    visited: set[UUID] = set()
    while current_id is not None:
        if current_id == node_id or current_id in visited:
            raise ProjectInvariantError("Узел программы не может быть родителем самому себе")
        visited.add(current_id)
        parent = session.get(ProgramNode, current_id)
        if parent is None or parent.project_id != project_id:
            raise ProjectInvariantError("Родитель узла должен находиться в этом проекте")
        depth += 1
        if depth > 4:
            raise ProjectInvariantError("Глубина программы не может превышать четыре уровня")
        current_id = parent.parent_id


def _require_writable_project(session: Session, project_id: UUID) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError("Проект не найден")
    if project.status not in {ProjectStatus.DRAFT, ProjectStatus.ACTIVE}:
        raise ProjectConflictError("Архивный или завершённый проект нельзя изменять")
    return project


def activate_wizard_draft(
    session: Session, project_id: UUID, expected_revision: int
) -> ProjectDetail:
    with session.begin():
        project = session.get(Project, project_id)
        if project is None:
            raise ProjectNotFoundError("Проект не найден")
        if project.status == ProjectStatus.ACTIVE:
            return _project_detail(session, project_id)
        if project.status != ProjectStatus.DRAFT:
            raise ProjectConflictError("Архивный или завершённый проект нельзя активировать")

        result = session.execute(
            update(WizardDraft)
            .where(
                WizardDraft.project_id == project_id,
                WizardDraft.revision == expected_revision,
            )
            .values(revision=WizardDraft.revision + 1)
        )
        if result.rowcount != 1:
            raise ProjectConflictError("Черновик уже изменён в другой вкладке")

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

        nodes = _nodes(session, project_id)
        if not any(
            node.node_type in {NodeType.TOPIC, NodeType.SUBPOINT}
            and node.is_in_current_program
            and not node.is_archived
            for node in nodes
        ):
            raise ProjectConflictError("Перед активацией добавьте хотя бы одну тему программы")
        _validate_tree({node.id: node.parent_id for node in nodes})

        now = utc_now()
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
        .order_by(Project.sort_order, Project.name, Project.id)
    )
    return [ProjectSummary.model_validate(project) for project in projects]


def get_project(session: Session, project_id: UUID) -> ProjectDetail:
    return _project_detail(session, project_id)


def update_project_settings(
    session: Session, project_id: UUID, command: ProjectSettingsWrite
) -> ProjectDetail:
    with session.begin():
        project = session.get(Project, project_id)
        if project is None or project.status == ProjectStatus.DRAFT:
            raise ProjectNotFoundError("Проект не найден")
        if project.status != ProjectStatus.ACTIVE:
            raise ProjectConflictError("Архивный или завершённый проект нельзя изменять")

        now = utc_now()
        project_data = command.project.model_dump(mode="python", exclude={"enabled_modules"})
        for field, value in project_data.items():
            setattr(project, field, value)
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
        return _project_detail(session, project_id)


def create_program_node(
    session: Session, project_id: UUID, command: ProgramNodeCreate
) -> ProgramNodeRead:
    with session.begin():
        project = _require_writable_project(session, project_id)
        _validate_parent(session, project_id, None, command.parent_id)
        node = ProgramNode(project_id=project_id, **command.model_dump(mode="python"))
        session.add(node)
        project.updated_at = utc_now()
        session.flush()
        return ProgramNodeRead.model_validate(node)


def update_program_node(
    session: Session,
    project_id: UUID,
    node_id: UUID,
    command: ProgramNodeUpdate,
) -> ProgramNodeRead:
    with session.begin():
        project = _require_writable_project(session, project_id)
        node = session.scalar(
            select(ProgramNode).where(
                ProgramNode.id == node_id, ProgramNode.project_id == project_id
            )
        )
        if node is None:
            raise ProjectNotFoundError("Узел программы не найден")

        data = command.model_dump(mode="python", exclude_unset=True)
        nonnullable = {
            "node_type",
            "sort_order",
            "title",
            "is_in_current_program",
            "needs_material",
            "is_archived",
            "origin_kind",
        }
        if any(data.get(field) is None for field in nonnullable & command.model_fields_set):
            raise ProjectInvariantError("Обязательное поле узла нельзя очистить")
        if "parent_id" in command.model_fields_set:
            _validate_parent(session, project_id, node_id, command.parent_id)
        for field, value in data.items():
            setattr(node, field, value)
        now = utc_now()
        node.updated_at = now
        project.updated_at = now
        session.flush()
        return ProgramNodeRead.model_validate(node)


def save_workspace_state(
    session: Session, project_id: UUID, command: WorkspaceStateWrite
) -> WorkspaceStateRead:
    with session.begin():
        project = _require_writable_project(session, project_id)
        node_ids = list(
            dict.fromkeys(
                [command.layout.selected_node_id, *command.layout.expanded_node_ids]
            )
        )
        node_ids = [node_id for node_id in node_ids if node_id is not None]
        if node_ids:
            found_ids = set(
                session.scalars(
                    select(ProgramNode.id).where(
                        ProgramNode.project_id == project_id, ProgramNode.id.in_(node_ids)
                    )
                )
            )
            if found_ids != set(node_ids):
                raise ProjectInvariantError("Раскладка ссылается на узел другого проекта")

        layout = command.layout.model_dump(mode="json")
        layout["expanded_node_ids"] = [
            str(node_id) for node_id in dict.fromkeys(command.layout.expanded_node_ids)
        ]
        workspace_state = session.get(WorkspaceState, project_id)
        if workspace_state is None:
            workspace_state = WorkspaceState(project_id=project_id)
            session.add(workspace_state)
        now = utc_now()
        workspace_state.schema_version = command.schema_version
        workspace_state.layout = layout
        workspace_state.updated_at = now
        project.updated_at = now
        session.flush()
        return WorkspaceStateRead.model_validate(workspace_state)
