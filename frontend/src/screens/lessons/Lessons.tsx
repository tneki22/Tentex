import { useEffect, useState } from "react";
import { ArrowLeft, GraduationCap } from "lucide-react";
import { Link, useParams } from "react-router";
import { getProject, ProjectApiError, type ProjectDetail } from "../../api/projects";
import { ProjectNav } from "../../components/domain";
import { EmptyState, ErrorState, LoadingState, PageHead } from "../../components/ui";

export function Lessons() {
  const { projectId = "" } = useParams();
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    const controller = new AbortController();
    getProject(projectId, controller.signal).then(setDetail).catch((caught) => {
      if (!controller.signal.aborted) setError(caught);
    });
    return () => controller.abort();
  }, [projectId]);

  if (error) {
    const notFound = error instanceof ProjectApiError && error.status === 404;
    return <div className="screen"><ErrorState title={notFound ? "Проект не найден" : "Уроки не загрузились"} message={error instanceof Error ? error.message : "Не удалось загрузить проект"} /><Link className="secondary-button" to="/projects">К проектам</Link></div>;
  }
  if (!detail) return <div className="screen"><LoadingState label="Загружаем проект" placement="page" /></div>;

  const textbook = detail.project.workspace_variant === "textbook";
  return (
    <div className="program-screen">
      <aside className="project-side-panel">
        <header className="project-side-title"><Link className="workspace-back-button" to={`/projects/${projectId}`} aria-label="Вернуться в рабочую область"><ArrowLeft size={15} /></Link><strong>{detail.project.name}</strong></header>
        <ProjectNav projectId={projectId} active="lessons" textbook={textbook} modules={detail.project.enabled_modules} className="project-side-nav" />
      </aside>
      <main className="program-main">
        <PageHead eyebrow="Следующая итерация" title="Уроки" />
        <EmptyState title="Мастер создания уроков ещё не готов" icon={<GraduationCap size={28} />}>
          <p>Здесь появятся создание, редактирование и подготовка уроков. Пока раздел не создаёт черновики и не хранит демонстрационные данные.</p>
          <Link className="primary-button" to={`/projects/${projectId}`}>В рабочую область</Link>
        </EmptyState>
      </main>
    </div>
  );
}
