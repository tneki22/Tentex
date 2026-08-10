from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ExamFormat,
    ExamKind,
    GoalPassport,
    GoalPurpose,
    GoalRole,
    GoalScope,
    NodeType,
    OriginKind,
    ProgramNode,
    Project,
    ProjectStatus,
    ReferenceAnswer,
    ReferenceAnswerMatchMethod,
    ReferenceAnswerOrigin,
    StartingLevel,
    StudyFormat,
    TargetOutcome,
    TemplateKey,
    WorkspaceState,
    WorkspaceVariant,
)
from app.projects.schemas import WorkspaceStateWrite

DEMO_PROJECT_ID = uuid5(NAMESPACE_URL, "tentex:demo:database-exam:v1")


def _demo_id(name: str) -> UUID:
    return uuid5(DEMO_PROJECT_ID, name)


DEMO_ANSWERS = (
    (
        "ticket-1-question-1",
        "Архитектура системы управления базами данных",
        "СУБД разделяет внешнее, концептуальное и внутреннее представления данных. "
        "Менеджеры запросов, транзакций, буферов и хранения совместно обеспечивают "
        "независимость данных, целостность и конкурентный доступ.",
    ),
    (
        "ticket-1-question-2",
        "Реляционная модель данных и её компоненты",
        "Реляционная модель представляет данные отношениями. Её основные компоненты — "
        "структура таблиц и доменов, ограничения целостности и операции реляционной "
        "алгебры, из которых строятся запросы.",
    ),
    (
        "ticket-2-question-1",
        "Транзакции и свойства ACID",
        "Транзакция — логическая единица работы с базой. Атомарность исключает частичное "
        "выполнение, согласованность сохраняет инварианты, изоляция управляет взаимным "
        "влиянием операций, долговечность сохраняет подтверждённый результат.",
    ),
    (
        "ticket-2-task-1",
        "Нормализовать отношение до третьей нормальной формы",
        "Сначала определяют функциональные зависимости и кандидатные ключи, затем "
        "устраняют частичные зависимости для второй нормальной формы и транзитивные "
        "зависимости неключевых атрибутов для третьей. Декомпозиция должна сохранять "
        "зависимости и соединяться без потерь.",
    ),
)


def _seed_demo_answers(session: Session) -> None:
    for node_key, title, text in DEMO_ANSWERS:
        node_id = _demo_id(node_key)
        if session.get(ProgramNode, node_id) is None:
            continue
        if session.get(ReferenceAnswer, (DEMO_PROJECT_ID, node_id)) is not None:
            continue
        session.add(
            ReferenceAnswer(
                project_id=DEMO_PROJECT_ID,
                program_node_id=node_id,
                text=text,
                origin_kind=ReferenceAnswerOrigin.IMPORT,
                match_method=ReferenceAnswerMatchMethod.EXACT_TITLE,
                matched_title=title,
                is_confirmed=True,
                is_active=True,
                revision=0,
                source_label="Демонстрационный набор Tentex",
            )
        )
    session.flush()


def seed_demo_project(session: Session, *, create_if_missing: bool = True) -> UUID:
    with session.begin():
        if session.get(Project, DEMO_PROJECT_ID) is not None:
            _seed_demo_answers(session)
            return DEMO_PROJECT_ID
        if not create_if_missing:
            return DEMO_PROJECT_ID
        last_active_order = session.scalar(
            select(func.max(Project.sort_order)).where(Project.status == ProjectStatus.ACTIVE)
        )
        project = Project(
            id=DEMO_PROJECT_ID,
            template_key=TemplateKey.EXAM,
            workspace_variant=WorkspaceVariant.EXAM,
            status=ProjectStatus.ACTIVE,
            name="Базы данных — экзамен (пример)",
            description="Готовый пример для знакомства с Программой и Рабочей областью",
            icon="database",
            color=4,
            sort_order=0 if last_active_order is None else last_active_order + 1,
            deadline=None,
            enabled_modules=["plan", "cards", "repetitions", "oral_answers"],
        )
        session.add(project)
        session.flush()
        session.add(
            GoalPassport(
                project_id=project.id,
                subject="Базы данных",
                purpose=GoalPurpose.EXAM,
                scope=GoalScope.WHOLE,
                starting_level=StartingLevel.FAMILIAR,
                current_knowledge="Знаком с основами SQL и реляционной моделью",
                target_outcome=TargetOutcome.APPLICATION,
                goal="Подготовиться к экзамену по базам данных",
                success_criterion="Объяснить теорию и решить типовую задачу без конспекта",
                important="Транзакции, архитектура СУБД и нормализация",
                excluded=None,
                study_format=StudyFormat.THEORY_AND_PRACTICE,
                minutes_per_day=45,
                days_per_week=4,
                session_minutes=45,
                exam_format=ExamFormat.TICKETS,
                expected_item_count=2,
                instructor_requirements=None,
            )
        )

        ticket_1 = _demo_id("ticket-1")
        ticket_2 = _demo_id("ticket-2")
        node_specs = [
            (ticket_1, None, NodeType.SECTION, ExamKind.TICKET, 0, "Билет 1"),
            (
                _demo_id("ticket-1-question-1"),
                ticket_1,
                NodeType.TOPIC,
                ExamKind.QUESTION,
                0,
                "Архитектура системы управления базами данных",
            ),
            (
                _demo_id("ticket-1-question-2"),
                ticket_1,
                NodeType.TOPIC,
                ExamKind.QUESTION,
                1,
                "Реляционная модель данных и её компоненты",
            ),
            (ticket_2, None, NodeType.SECTION, ExamKind.TICKET, 1, "Билет 2"),
            (
                _demo_id("ticket-2-question-1"),
                ticket_2,
                NodeType.TOPIC,
                ExamKind.QUESTION,
                0,
                "Транзакции и свойства ACID",
            ),
            (
                _demo_id("ticket-2-task-1"),
                ticket_2,
                NodeType.TOPIC,
                ExamKind.TASK,
                1,
                "Нормализовать отношение до третьей нормальной формы",
            ),
        ]
        for node_id, parent_id, node_type, exam_kind, sort_order, title in node_specs:
            session.add(
                ProgramNode(
                    id=node_id,
                    project_id=project.id,
                    parent_id=parent_id,
                    node_type=node_type,
                    exam_kind=exam_kind,
                    sort_order=sort_order,
                    title=title,
                    goal_role=GoalRole.TARGET,
                    target_level=TargetOutcome.APPLICATION,
                    is_in_current_program=True,
                    needs_material=False,
                    is_archived=False,
                    origin_kind=OriginKind.IMPORT,
                    origin_note="Демонстрационный набор Tentex",
                )
            )
            session.flush()

        layout = WorkspaceStateWrite.model_validate(
            {
                "schema_version": 1,
                "layout": {
                    "selected_node_id": str(_demo_id("ticket-1-question-1")),
                    "expanded_node_ids": [str(ticket_1), str(ticket_2)],
                    "tree_width": 320,
                    "groups": [
                        {
                            "id": "main",
                            "tabs": [],
                            "active_tab": None,
                        }
                    ],
                    "group_weights": [1],
                },
            }
        )
        session.add(
            WorkspaceState(
                project_id=project.id,
                schema_version=layout.schema_version,
                layout=layout.layout.model_dump(mode="json"),
            )
        )
        session.flush()
        _seed_demo_answers(session)
        return project.id
