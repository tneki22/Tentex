import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, RotateCcw } from "lucide-react";
import {
  checkStudyTaskAttempt,
  submitStudyTaskAttempt,
  type AttemptOutcome,
  type StudyTaskRead,
} from "../../api/lessons";
import { TaskCard } from "../../components/domain/lesson/tasks/TaskCard";
import { Button, Dialog, Progress } from "../../components/ui";

interface LessonPracticeRunProps {
  open: boolean;
  onOpenChange(open: boolean): void;
  projectId: string;
  lessonId: string;
  title: string;
  tasks: StudyTaskRead[];
}

function tasksWord(count: number): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod100 >= 11 && mod100 <= 14) return "заданий";
  if (mod10 === 1) return "задание";
  if (mod10 >= 2 && mod10 <= 4) return "задания";
  return "заданий";
}

/**
 * «Пройти задания»: задания урока по одному, в конце — сводка «N верно, M с
 * ошибками» и «Повторить ошибки». Каждая проверка — обычная попытка задания,
 * поэтому история и последняя попытка в уроке те же, что при ответе в тексте.
 */
export function LessonPracticeRun({ open, onOpenChange, projectId, lessonId, title, tasks }: LessonPracticeRunProps) {
  const [queue, setQueue] = useState<StudyTaskRead[]>(tasks);
  const [position, setPosition] = useState(0);
  const [outcomes, setOutcomes] = useState<Record<string, AttemptOutcome>>({});
  const [round, setRound] = useState(0);

  useEffect(() => {
    if (!open) return;
    setQueue(tasks);
    setPosition(0);
    setOutcomes({});
    setRound((value) => value + 1);
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const finished = position >= queue.length;
  const summary = useMemo(() => {
    const values = queue.map((task) => outcomes[task.activity_id]);
    return {
      passed: values.filter((item) => item === "passed").length,
      mistakes: values.filter((item) => item === "partial" || item === "failed").length,
      skipped: values.filter((item) => item === undefined).length,
    };
  }, [queue, outcomes]);

  function repeatMistakes() {
    const again = queue.filter((task) => outcomes[task.activity_id] !== "passed");
    setQueue(again);
    setPosition(0);
    setOutcomes({});
    setRound((value) => value + 1);
  }

  const task = queue[position];
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      className="lesson-practice-run"
      title="Пройти задания"
      description={`«${title}» · ${queue.length} ${tasksWord(queue.length)}`}
      footer={finished ? (
        <>
          {summary.mistakes + summary.skipped > 0 && (
            <Button variant="secondary" onClick={repeatMistakes}><RotateCcw size={14} />Повторить ошибки</Button>
          )}
          <Button onClick={() => onOpenChange(false)}>Готово</Button>
        </>
      ) : (
        <>
          <Button variant="ghost" disabled={position === 0} onClick={() => setPosition((value) => value - 1)}><ChevronLeft size={14} />Назад</Button>
          <Button variant="secondary" onClick={() => setPosition((value) => value + 1)}>
            {position === queue.length - 1 ? "К итогу" : "Дальше"}<ChevronRight size={14} />
          </Button>
        </>
      )}
    >
      <Progress value={Math.min(position, queue.length)} max={Math.max(queue.length, 1)} label="Пройдено заданий" />
      {finished ? (
        <div className="lesson-practice-summary" role="status">
          <strong>{summary.passed} верно{summary.mistakes ? `, ${summary.mistakes} с ошибками` : ""}{summary.skipped ? `, ${summary.skipped} без ответа` : ""}</strong>
          <p>{summary.mistakes + summary.skipped === 0
            ? "Все задания решены. Можно отметить урок пройденным."
            : "Ошибки — повод перечитать куски урока, на которые ссылается разбор, и попробовать ещё раз."}</p>
        </div>
      ) : task && (
        <TaskCard
          key={`${round}-${task.activity_id}`}
          task={task}
          label={`Задание ${position + 1} из ${queue.length}`}
          onSubmit={(answer) => submitStudyTaskAttempt(projectId, lessonId, task.activity_id,
            task.form === "open_answer" ? { text: answer.text } : { answer })}
          onCheckPending={(attemptId) => checkStudyTaskAttempt(projectId, lessonId, task.activity_id, attemptId)}
          onResult={(attempt) => { if (attempt.outcome) setOutcomes((current) => ({ ...current, [task.activity_id]: attempt.outcome! })); }}
        />
      )}
    </Dialog>
  );
}
