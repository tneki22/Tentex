import { useState } from "react";
import { Bot, Cpu, DatabaseBackup, HardDrive } from "lucide-react";
import { Button, Card, PageHead, StatusBadge, Switch } from "../components/ui";
import { CostEstimate, OfflineNotice } from "../components/domain";

/**
 * Установка — глобальные настройки: модели, бот, копии, хранилище.
 * Настройки конкретного проекта (§21.14) живут внутри проекта.
 *
 * Глубина «эскизом»: SCREENS.md, раздел «Установка». Данные выдуманные.
 *
 * Тумблер моделей переключается по-настоящему: так видно, что выключенные модели —
 * законный режим (нейтральный тон, офлайновые альтернативы), а не поломка.
 */

/** Двенадцать ролей из §13; здесь три показательных. */
const ROLES = [
  { id: "pass1", label: "Построение программы (проход 1)", hint: "map-reduce по главам" },
  { id: "pass2", label: "Соотнесение материала (проход 2)", hint: "полный перебор блоков" },
  { id: "judge", label: "ИИ-судья", hint: "оценка свободного ответа по рубрике" },
];

export function Setup() {
  const [models, setModels] = useState(true);
  const [roles, setRoles] = useState<Record<string, boolean>>({
    pass1: true,
    pass2: true,
    judge: false,
  });

  return (
    <div className="screen">
      <PageHead
        title="Установка"
        lead="То, что общее для всех проектов: модели, бот, копии, хранилище."
      />

      <div className="setup-stack">
        <Card className="setup-section">
          <h2>
            <Cpu size={16} aria-hidden="true" /> Модели
          </h2>

          <Switch
            checked={models}
            onCheckedChange={setModels}
            label="Внешние модели"
            hint="Выключены — работает детерминированное ядро: программа по оглавлению, поиск, карточки, SM-2"
          />

          {models ? (
            <>
              <div className="setup-row">
                <span>Провайдер</span>
                <span className="setup-value">OpenRouter · ключ задан · отвечает</span>
              </div>
              <div className="setup-row">
                <span>Расход сегодня</span>
                <span className="setup-value">$0.34 из $2.00</span>
              </div>
              <div className="setup-divider" />
              {ROLES.map((role) => (
                <Switch
                  key={role.id}
                  checked={roles[role.id]}
                  onCheckedChange={(value) => setRoles((prev) => ({ ...prev, [role.id]: value }))}
                  label={role.label}
                  hint={role.hint}
                />
              ))}
              <div className="setup-divider" />
              <CostEstimate
                calls={30}
                cost={0.42}
                minutes={4}
                pricesFrom="12.05.2026"
                units="учебник на 320 страниц"
              />
            </>
          ) : (
            <OfflineNotice
              reason="disabled"
              alternative="Программа собирается по оглавлению и импортом, поиск и повторения работают как обычно."
            />
          )}
        </Card>

        <Card className="setup-section">
          <h2>
            <Bot size={16} aria-hidden="true" /> Бот
          </h2>
          <div className="setup-row">
            <span>Telegram</span>
            <StatusBadge tone="success">привязан</StatusBadge>
          </div>
          <div className="setup-row">
            <span>Сообщений сегодня</span>
            <span className="setup-value">4 из 20 · тихие часы 23:00–08:00</span>
          </div>
        </Card>

        <Card className="setup-section">
          <h2>
            <DatabaseBackup size={16} aria-hidden="true" /> Резервные копии
          </h2>
          <div className="setup-row">
            <span>Последняя</span>
            <span className="setup-value">вчера, 23:40 · раз в день · хранится 14</span>
          </div>
          <div className="setup-row">
            <span>Копия — это копия файла базы</span>
            <Button variant="secondary" disabled title="Появится вместе с API">
              Сделать копию сейчас
            </Button>
          </div>
        </Card>

        <Card className="setup-section">
          <h2>
            <HardDrive size={16} aria-hidden="true" /> Хранилище
          </h2>
          <div className="setup-row">
            <span>Папка данных</span>
            <span className="setup-value">
              <code>data/</code> · занято 2,1 ГБ
            </span>
          </div>
        </Card>
      </div>
    </div>
  );
}
