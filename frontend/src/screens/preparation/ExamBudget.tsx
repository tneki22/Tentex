/** Дата экзамена и вычисленный сервером остаток доступного времени: простая надпись, без карточки. */
import { Info } from "lucide-react";
import { Link } from "react-router";
import { IconButton, Tooltip } from "../../components/ui";
import type { Overview } from "../../api/preparation";
import { dayNumber, duration } from "./dates";
import { longDateLabel, plural } from "./model";

/** Цвет использует те же пороги, что карточка проекта: три дня и неделя. */
export function ExamBudget({ overview }: { overview: Overview }) {
  const { budget, deadline, settings } = overview;
  if (!deadline) return <p className="prep-note">Дата экзамена не задана. <Link to={`/projects/${overview.project_id}/settings`}>Указать дату</Link></p>;
  const days = dayNumber(deadline) - dayNumber(overview.today);
  const tone = days <= 3 ? "danger" : days <= 7 ? "warning" : "success";
  const explanation = <div className="prep-budget-explanation">
    <strong>Как считается время</strong>
    <span>Сумма дневных бюджетов: {duration(budget.base_minutes * 60)}</span>
    <span>Дни отдыха и пропуски: −{duration(budget.rest_minutes * 60)}</span>
    <span>Поправка на недельное расписание и исключения: {budget.exception_minutes < 0 ? "+" : "−"}{duration(Math.abs(budget.exception_minutes) * 60)}</span>
    <span>Уже потрачено сегодня: −{duration(budget.used_minutes * 60)}</span>
    <span>Ограничение свободными часами, сон, занятость и резерв: −{duration(budget.unavailable_minutes * 60)}</span>
    <strong>Осталось: {duration(budget.remaining_minutes * 60)}</strong>
    <small>Для каждого дня берём меньшую величину: остаток дневного бюджета или свободное время. Пересечения сна и занятости считаются один раз. День экзамена исключён. Часовой пояс: {settings.config.timezone}.</small>
  </div>;
  const examTime = overview.exam_time ? <> в <strong>{overview.exam_time.slice(0, 5)}</strong></> : null;
  const daysLabel =
    days < 0 ? "экзамен уже прошёл" : days === 0 ? "экзамен сегодня" : `до экзамена ${days} ${plural(days, "день", "дня", "дней")}`;
  return <section className={`prep-exam-budget is-${tone}`} aria-label="До экзамена">
    <p className="prep-exam-line">
      Твой экзамен <strong>{longDateLabel(deadline)}</strong>{examTime}, {daysLabel}.
    </p>
    <p className="prep-exam-line">
      {days > 0 && <>Из них {budget.study_days} {plural(budget.study_days, "день", "дня", "дней")} под этот экзамен. </>}
      На подготовку осталось{" "}
      <strong>{settings.config.daily_minutes == null ? "бюджет не задан" : duration(budget.remaining_minutes * 60)}</strong>
      <Tooltip label={explanation} side="bottom">
        <IconButton label="Как считается оставшееся время" hideNativeTitle>
          <Info size={14} />
        </IconButton>
      </Tooltip>
    </p>
  </section>;
}
