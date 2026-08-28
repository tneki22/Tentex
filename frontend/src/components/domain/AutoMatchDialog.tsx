import { useEffect, useState } from "react";
import { FileText, Link2 } from "lucide-react";
import { Button, Dialog, RadioCards } from "../ui";

type AutoMatchMode = "headings" | "ai";

interface AutoMatchDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Режим «на основе заголовков»: нынешний разбор файла ответов. */
  onRunHeadings: () => void;
  /** Запасной путь: разобрать ответы из сплошного текста страниц. */
  onImportText: () => void;
}

/**
 * Одна точка входа автосопоставления вместо двух кнопок в разных вкладках.
 * Режим «на основе заголовков» — существующий детерминированный разбор файла
 * ответов; режим «с ИИ» — будущий проход 2 (этап 8), пока честная заглушка.
 */
export function AutoMatchDialog({
  open,
  onOpenChange,
  onRunHeadings,
  onImportText,
}: AutoMatchDialogProps) {
  const [mode, setMode] = useState<AutoMatchMode>("headings");

  // При каждом открытии возвращаемся к рекомендованному режиму.
  useEffect(() => {
    if (open) setMode("headings");
  }, [open]);

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Сопоставить ответы автоматически"
      description="Разложить разделы файла ответов по вопросам программы."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Отмена</Button>
          <Button
            disabled={mode !== "headings"}
            onClick={() => { onOpenChange(false); onRunHeadings(); }}
          >
            <Link2 size={14} /> Сопоставить
          </Button>
        </>
      }
    >
      <RadioCards
        label="Как сопоставлять"
        layout="rows"
        value={mode}
        onChange={setMode}
        options={[
          {
            value: "headings",
            title: "На основе заголовков",
            description: "Заголовки разделов сверяются с формулировками вопросов. Без ИИ, работает офлайн.",
          },
          {
            value: "ai",
            title: "С помощью ИИ",
            description: "Модель разнесёт разделы, когда формулировки сильно разошлись.",
            unavailableReason: "Появится на этапе 8: проход 2 разнесёт разделы моделью и спросит подтверждение перед отправкой данных.",
          },
        ]}
      />
      <p className="materials-muted">
        Чаще всего достаточно заголовков: если файл ответов подготовлен аккуратно,
        они сами лягут на вопросы. ИИ понадобится только для сложных случаев.
      </p>
      <Button variant="ghost" onClick={() => { onOpenChange(false); onImportText(); }}>
        <FileText size={14} /> Или вставить ответы текстом
      </Button>
    </Dialog>
  );
}
