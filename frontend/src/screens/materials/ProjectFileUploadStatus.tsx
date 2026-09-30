import { FileUp } from "lucide-react";
import { Progress } from "../../components/ui";

interface ProjectFileUploadStatusProps {
  name: string;
  progress: number;
}

/** Отправка байтов и ожидание ответа сервера — два разных состояния. */
export function ProjectFileUploadStatus({ name, progress }: ProjectFileUploadStatusProps) {
  const sent = progress >= 100;
  return (
    <div className={`project-file-upload-status${sent ? " is-finishing" : ""}`} role="status" aria-live="polite">
      <span className="project-file-upload-icon"><FileUp size={18} aria-hidden="true" /></span>
      <span className="project-file-upload-copy">
        <strong title={name}>{name}</strong>
        <small>{sent ? "Файл передан. Сохраняем в проекте…" : `Загружаем файл · ${progress}%`}</small>
      </span>
      <span className="project-file-upload-percent" aria-hidden="true">{sent ? "…" : `${progress}%`}</span>
      <Progress value={progress} max={100} label={`Загрузка файла ${name}`} />
    </div>
  );
}
