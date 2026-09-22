import { BookOpenText, Compass, Layers3 } from "lucide-react";
import { Card, PageHead } from "../components/ui";

/** Честная точка входа будущего руководства: маршрут уже стабилен, текста пока нет. */
export function Guide() {
  return (
    <div className="screen guide-screen">
      <PageHead placement="topbar" title="Инструкция по использованию" />
      <Card className="guide-placeholder">
        <BookOpenText size={28} aria-hidden="true" />
        <div>
          <p className="eyebrow">Руководство пользователя</p>
          <h2>Инструкция появится здесь</h2>
          <p>Маршрут уже готов. Позже здесь будут короткие разделы о первом проекте, работе с материалами и занятиях.</p>
        </div>
        <div className="guide-placeholder-topics" aria-label="Будущие разделы">
          <span><Compass size={15} />Первый проект</span>
          <span><Layers3 size={15} />Работа с материалами</span>
        </div>
      </Card>
    </div>
  );
}
