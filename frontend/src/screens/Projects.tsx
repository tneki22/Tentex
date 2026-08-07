import { useState } from "react";
import type { DragEvent } from "react";
import { Link } from "react-router";
import { Button, Card, Disclosure, PageHead } from "../components/ui";
import { ProjectChip } from "../components/domain";
import { DEMO_TEXTBOOK_PROJECT_ID } from "../app/screens";
import type { ProjectColor, ProjectIconName } from "../components/domain";

/**
 * Дашборд «Проекты» — вход в приложение. Описание: SCREENS.md, раздел «Проекты».
 * Данные выдуманные: API появится на этапе 3.
 *
 * На этом входном экране карточка показывает только опознавательный знак и
 * название. Метрики будут в карточке покрытия конкретного проекта.
 */

interface DemoProject {
  id: string;
  name: string;
  icon: ProjectIconName;
  color: ProjectColor;
}

const DEMO_PROJECTS: DemoProject[] = [
  {
    id: "trps",
    name: "ТРПС — курсовая",
    icon: "scale",
    color: 7,
  },
  {
    id: "db-exam",
    name: "Базы данных — экзамен",
    icon: "database",
    color: 2,
  },
  {
    id: DEMO_TEXTBOOK_PROJECT_ID,
    name: "Индексы в векторных базах данных",
    icon: "sigma",
    color: 4,
  },
  {
    id: "astronomy",
    name: "Астрономия",
    icon: "atom",
    color: 5,
  },
];

const DEMO_ARCHIVE = [
  {
    id: "chem",
    name: "Химия — коллоквиум",
    icon: "flask" as ProjectIconName,
    color: 8 as ProjectColor,
    note: "завершён 15.06.2026",
  },
];

const TEMPLATES = [
  {
    id: "exam",
    title: "Экзамен по билетам",
    description: "Дедлайн, вопросы и ответы, план до даты. Работает без внешних моделей.",
  },
  {
    id: "textbook",
    title: "Учебник",
    description: "Один большой файл, программа по оглавлению или проходом по материалу.",
  },
  {
    id: "free",
    title: "Свободное изучение",
    description: "Без дедлайна, программа из каталога, материалы добавляются позже.",
  },
];

export function Projects() {
  const [projects, setProjects] = useState(DEMO_PROJECTS);
  const [draggedId, setDraggedId] = useState<string | null>(null);

  function moveProject(targetId: string) {
    if (!draggedId || draggedId === targetId) return;

    setProjects((current) => {
      const from = current.findIndex((project) => project.id === draggedId);
      const to = current.findIndex((project) => project.id === targetId);
      if (from < 0 || to < 0) return current;
      const next = [...current];
      next.splice(to, 0, next.splice(from, 1)[0]);
      return next;
    });
  }

  function onDrop(event: DragEvent<HTMLElement>, targetId: string) {
    event.preventDefault();
    moveProject(targetId);
    setDraggedId(null);
  }

  return (
    <div className="screen">
      <PageHead
        title="Проекты"
        actions={
          <Link className="primary-button" to="/projects/new">
            Новый проект
          </Link>
        }
      />

      {projects.length === 0 ? (
        <>
          <p className="lead" style={{ marginBottom: "var(--space-6)" }}>
            Первый проект начинается с шаблона.
          </p>
          <div className="dash-templates">
            {TEMPLATES.map((template) => (
              <Card className="dash-template" key={template.id} onClick={() => undefined}>
                <h3>{template.title}</h3>
                <p>{template.description}</p>
              </Card>
            ))}
          </div>
        </>
      ) : (
        <div className="dash-grid">
          {projects.map((project) => (
            <article
              className={`dash-card ${draggedId === project.id ? "is-dragging" : ""}`.trim()}
              draggable
              key={project.id}
              onDragEnd={() => setDraggedId(null)}
              onDragOver={(event) => event.preventDefault()}
              onDragStart={(event) => {
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("text/plain", project.id);
                setDraggedId(project.id);
              }}
              onDrop={(event) => onDrop(event, project.id)}
            >
              <div className="dash-card-id">
                <ProjectChip icon={project.icon} color={project.color} />
                <h2 className="dash-card-name">{project.name}</h2>
              </div>
              <div className="dash-card-actions" aria-label={`Действия для проекта «${project.name}»`}>
                <Link className="dash-card-action" to={`/projects/${project.id}`}>
                  Продолжить изучение
                </Link>
                <Link className="dash-card-action" to={`/projects/${project.id}/cards?session=today`}>
                  Повторить
                </Link>
              </div>
            </article>
          ))}
        </div>
      )}

      {DEMO_ARCHIVE.length > 0 && (
        <Disclosure
          className="dash-archive"
          summary={`Архив и завершённые (${DEMO_ARCHIVE.length})`}
        >
          {DEMO_ARCHIVE.map((project) => (
            <div className="dash-archive-row" key={project.id}>
              <ProjectChip icon={project.icon} color={project.color} size="sm" />
              <span className="dash-archive-name">{project.name}</span>
              <span className="dash-archive-note">{project.note}</span>
              <Button variant="ghost" title="Появится вместе с API" disabled>
                Вернуть в работу
              </Button>
            </div>
          ))}
        </Disclosure>
      )}
    </div>
  );
}
