import { useEffect, useState } from "react";
import { FileText, Link2 } from "lucide-react";
import { Button, Dialog, RadioCards } from "../ui";

type AutoMatchMode = "headings" | "ai";

interface AutoMatchDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Режим «на основе заголовков»: нынешний разбор файла ответов. */
  onRunHeadings: () => void;
  /** Режим «с ИИ»: скелет документа размечает модель (срез F). */
  onRunAi: () => void;
  /** Запасной путь: разобрать ответы из сплошного текста страниц. */
  onImportText: () => void;
}

/** Одна точка входа автосопоставления вместо двух кнопок в разных вкладках. */
export function AutoMatchDialog({
  open,
  onOpenChange,
  onRunHeadings,
  onRunAi,
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
            onClick={() => {
              onOpenChange(false);
              if (mode === "headings") onRunHeadings(); else onRunAi();
            }}
          >
            <Link2 size={14} /> {mode === "headings" ? "Сопоставить" : "Разметить"}
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
            description: "Модель разметит границы разделов по скелету документа, когда заголовки или нумерация разошлись со структурой файла. Перед применением — предпросмотр и подтверждение.",
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
