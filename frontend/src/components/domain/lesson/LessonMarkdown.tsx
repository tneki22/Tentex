import type { ReactNode } from "react";
import { MarkdownView, type MarkdownOptions } from "../markdown/MarkdownView";

/**
 * Картинка из Markdown.
 *
 * `blob:` живёт только до перезагрузки вкладки: изображение, брошенное прямо в
 * редактор пояснения, после неё не открывается и раньше оставалось в тексте
 * строкой `![1.00](blob:…)`. Вместо мёртвой картинки — честная пометка;
 * изображения урока добавляются блоком «Медиа», у него файл на диске.
 */
function picture(alt: string, url: string, key: string): ReactNode {
  if (/^(https?:|\/api\/)/.test(url)) {
    return <img key={key} className="lesson-markdown-image" src={url} alt={alt} loading="lazy" />;
  }
  return <span key={key} className="lesson-markdown-missing">Изображение не сохранилось{alt ? `: ${alt}` : ""}</span>;
}

const LESSON_OPTIONS: MarkdownOptions = { renderImage: picture };

/**
 * Пояснение урока в режиме чтения — тот же рендер, что у ответов чата.
 * Crepe пишет пустой абзац как `<br />` и экранирует знаки разметки `\*`:
 * общий разбор понимает и то и другое. Один Crepe на выбранном блоке, остальные — здесь (§3.7).
 */
export function LessonMarkdown({ text, className = "" }: { text: string; className?: string }) {
  return <MarkdownView text={text} className={`lesson-markdown ${className}`.trim()} options={LESSON_OPTIONS} />;
}
