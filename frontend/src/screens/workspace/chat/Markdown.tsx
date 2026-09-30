import { useMemo, useState } from "react";
import type { ChatRetrievalSource } from "../../../api/chat";
import { MarkdownView, type MarkdownOptions } from "../../../components/domain/markdown/MarkdownView";
import { Popover } from "../../../components/ui/Popover";
import { CitationPreview } from "./ChatSources";

/**
 * Ответ модели: общий Markdown плюс цитаты `[S3]`, открывающие окно источника.
 *
 * Открыто одно окно — ключ конкретного вхождения ссылки, а не S-ID: одна и та
 * же цитата может стоять в ответе несколько раз. Клик снаружи и Escape
 * закрывают окно силами Radix; клик по другой цитате переключает ключ.
 */
export function Markdown({ text, sources = [] }: { text: string; sources?: ChatRetrievalSource[] }) {
  const [openKey, setOpenKey] = useState<string | null>(null);
  const options = useMemo<MarkdownOptions>(() => {
    const byId = new Map(sources.map((source) => [source.id, source]));
    return {
      renderCitation: (id, key) => {
        const source = byId.get(id);
        if (!source) return null;
        return (
          <Popover
            key={key}
            side="right"
            align="start"
            className="popover-citation"
            open={openKey === key}
            onOpenChange={(open) => setOpenKey((current) => (open ? key : current === key ? null : current))}
            // Следующая цитата открывается сразу: возврат фокуса старой кнопке закрыл бы её.
            onCloseAutoFocus={(event) => event.preventDefault()}
            trigger={
              <button type="button" className="chat-citation" aria-label={`Источник ${id}: ${source.material}`}>
                {id}
              </button>
            }
          >
            <CitationPreview source={source} />
          </Popover>
        );
      },
    };
  }, [sources, openKey]);
  return <MarkdownView className="chat-markdown" text={text} options={options} />;
}
