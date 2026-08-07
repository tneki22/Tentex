import { useEffect, useMemo, useState } from "react";
import { Check, Pause, Pencil, Plus, Search, Sparkles, Trash2 } from "lucide-react";
import { Button, Checkbox, Field, PageHead, StatusBadge, type StatusTone } from "../../components/ui";
import { MachineMark } from "../../components/domain";
import { BANK, CARD_KIND_LABEL, type BankCard, type CardKind } from "./mockCards";

interface BankModeProps {
  onCreate: () => void;
  onGenerate: () => void;
}

type BankFilter = "all" | "active" | "draft" | "suspended" | "lost" | "hard";
type OriginFilter = "all" | "manual" | "machine" | "edited";

const FILTERS: Array<{ value: BankFilter; label: string }> = [
  { value: "all", label: "Все" }, { value: "active", label: "Активные" }, { value: "draft", label: "Черновики" },
  { value: "suspended", label: "Приостановлены" }, { value: "lost", label: "Без источника" }, { value: "hard", label: "Сложные" },
];

function cardStateBadge(state: BankCard["state"]): { text: string; tone: StatusTone } {
  if (state === "active") return { text: "активна", tone: "success" };
  if (state === "draft") return { text: "черновик", tone: "warning" };
  if (state === "lost-source") return { text: "источник потерян", tone: "danger" };
  return { text: "приостановлена", tone: "neutral" };
}

export function BankMode({ onCreate, onGenerate }: BankModeProps) {
  const [cards, setCards] = useState(BANK);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<BankFilter>("all");
  const [origin, setOrigin] = useState<OriginFilter>("all");
  const [section, setSection] = useState("all");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [activeId, setActiveId] = useState<string | null>(BANK[0]?.id ?? null);
  const [deleted, setDeleted] = useState<BankCard[]>([]);
  const [notice, setNotice] = useState("");

  const sections = [...new Set(cards.map((card) => card.section))];
  const filteredCards = useMemo(() => cards.filter((card) => {
    const text = `${card.front} ${card.question} ${card.section}`.toLocaleLowerCase("ru");
    if (query && !text.includes(query.toLocaleLowerCase("ru"))) return false;
    if (filter === "active" && card.state !== "active") return false;
    if (filter === "draft" && card.state !== "draft") return false;
    if (filter === "suspended" && card.state !== "suspended") return false;
    if (filter === "lost" && card.state !== "lost-source") return false;
    if (filter === "hard" && card.lastResult !== "fail") return false;
    if (origin !== "all" && card.origin !== origin) return false;
    if (section !== "all" && card.section !== section) return false;
    return true;
  }), [cards, filter, origin, query, section]);
  const active = cards.find((card) => card.id === activeId) ?? null;
  const allVisibleSelected = filteredCards.length > 0 && filteredCards.every((card) => selectedIds.has(card.id));

  function toggleSelected(id: string, checked: boolean) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (checked) next.add(id); else next.delete(id);
      return next;
    });
  }

  function updateSelected(state: BankCard["state"]) {
    setCards((current) => current.map((card) => selectedIds.has(card.id) ? { ...card, state } : card));
    setNotice(`Обновлено карточек: ${selectedIds.size}`);
    setSelectedIds(new Set());
  }

  function removeSelected(ids = selectedIds) {
    const removed = cards.filter((card) => ids.has(card.id));
    if (removed.length === 0) return;
    setDeleted(removed);
    setCards((current) => current.filter((card) => !ids.has(card.id)));
    setSelectedIds(new Set());
    if (activeId && ids.has(activeId)) setActiveId(null);
    setNotice(`Удалено карточек: ${removed.length}`);
  }

  function saveActive(next: BankCard) {
    setCards((current) => current.map((card) => card.id === next.id ? next : card));
    setNotice("Изменения карточки сохранены");
  }

  return (
    <div className="bank-mode">
      <PageHead
        eyebrow={`${cards.length} карточек в проекте`}
        title="Банк карточек"
        actions={<><Button variant="secondary" onClick={onGenerate}><Sparkles size={15} /> Сгенерировать</Button><Button onClick={onCreate}><Plus size={15} /> Создать</Button></>}
      />

      <section className="bank-toolbar">
        <label className="bank-search"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Вопрос, карточка или раздел" aria-label="Найти карточку" /></label>
        <select value={section} onChange={(event) => setSection(event.target.value)} aria-label="Фильтр по разделу"><option value="all">Все разделы</option>{sections.map((item) => <option value={item} key={item}>{item}</option>)}</select>
        <select value={origin} onChange={(event) => setOrigin(event.target.value as OriginFilter)} aria-label="Фильтр по происхождению"><option value="all">Любое происхождение</option><option value="manual">Вручную</option><option value="machine">Создано ИИ</option><option value="edited">Изменено после ИИ</option></select>
      </section>
      <nav className="bank-filter-tabs" aria-label="Состояние карточек">{FILTERS.map((item) => <button type="button" className={filter === item.value ? "is-active" : ""} key={item.value} onClick={() => setFilter(item.value)}>{item.label}</button>)}</nav>

      {selectedIds.size > 0 && <div className="bank-bulk-bar"><strong>Выбрано: {selectedIds.size}</strong><Button variant="ghost" onClick={() => updateSelected("active")}><Check size={14} /> Активировать</Button><Button variant="ghost" onClick={() => updateSelected("suspended")}><Pause size={14} /> Приостановить</Button><Button variant="ghost" onClick={() => removeSelected()}><Trash2 size={14} /> Удалить</Button></div>}

      <div className="bank-layout">
        <section className="bank-table" aria-label="Список карточек">
          <header className="bank-table-row">
            <span onClick={(event) => event.stopPropagation()}><Checkbox checked={allVisibleSelected} onCheckedChange={(checked) => setSelectedIds(checked ? new Set(filteredCards.map((card) => card.id)) : new Set())} label="Выбрать все карточки" /></span>
            <span>Карточка</span><span>Вопрос</span><span>Тип</span><span>Источник</span><span>Состояние</span><span>Повторение</span>
          </header>
          {filteredCards.length === 0 ? <div className="bank-empty">Карточек по этим условиям нет.</div> : filteredCards.map((card) => {
            const stateBadge = cardStateBadge(card.state);
            return <div role="row" tabIndex={0} className={`bank-table-row is-body ${activeId === card.id ? "is-active" : ""}`.trim()} key={card.id} onClick={() => setActiveId(card.id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setActiveId(card.id); } }}>
              <span onClick={(event) => event.stopPropagation()}><Checkbox checked={selectedIds.has(card.id)} onCheckedChange={(checked) => toggleSelected(card.id, checked)} label={`Выбрать карточку «${card.front}»`} /></span>
              <strong>{card.front}</strong><span>{card.question}<small>{card.section}</small></span><span>{CARD_KIND_LABEL[card.kind]}</span><span>{card.source}</span><span><StatusBadge tone={stateBadge.tone}>{stateBadge.text}</StatusBadge>{card.origin === "machine" && <MachineMark origin="ИИ" />}</span><span>{card.nextDue ?? "не начато"}</span>
            </div>;
          })}
        </section>

        {active && <BankInspector card={active} onSave={saveActive} onClose={() => setActiveId(null)} onDelete={() => removeSelected(new Set([active.id]))} />}
      </div>

      {(notice || deleted.length > 0) && <div className="bank-undo" role="status"><span>{notice}</span>{deleted.length > 0 && <button type="button" onClick={() => { setCards((current) => [...current, ...deleted]); setDeleted([]); setNotice("Удаление отменено"); }}>Отменить</button>}<button type="button" aria-label="Закрыть" onClick={() => { setNotice(""); setDeleted([]); }}>×</button></div>}
    </div>
  );
}

function BankInspector({ card, onSave, onClose, onDelete }: { card: BankCard; onSave: (card: BankCard) => void; onClose: () => void; onDelete: () => void }) {
  const [draft, setDraft] = useState(card);
  const state = cardStateBadge(draft.state);

  useEffect(() => setDraft(card), [card]);

  return (
    <aside className="bank-inspector" aria-label="Редактор выбранной карточки">
      <header><div><span>Редактор</span><strong>{draft.question}</strong></div><button type="button" onClick={onClose} aria-label="Закрыть">×</button></header>
      {draft.origin === "machine" && <MachineMark origin="создано ИИ" onUndo={() => setDraft((current) => ({ ...current, origin: "manual" }))} undoLabel="Сделать личной карточкой" />}
      {draft.state === "lost-source" && <p className="creation-warning">Источник удалён. Привяжите новый или оставьте карточку личной.</p>}
      <Field label="Лицевая сторона"><textarea rows={4} value={draft.front} onChange={(event) => setDraft({ ...draft, front: event.target.value })} /></Field>
      <Field label="Обратная сторона"><textarea rows={7} value={draft.back} onChange={(event) => setDraft({ ...draft, back: event.target.value })} /></Field>
      <Field label="Тип"><select value={draft.kind} onChange={(event) => setDraft({ ...draft, kind: event.target.value as CardKind })}>{Object.entries(CARD_KIND_LABEL).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></Field>
      <Field label="Источник"><input value={draft.source} onChange={(event) => setDraft({ ...draft, source: event.target.value, state: event.target.value ? "active" : "lost-source" })} /></Field>
      <div className="bank-inspector-state"><span>Состояние</span><StatusBadge tone={state.tone}>{state.text}</StatusBadge><select value={draft.state} onChange={(event) => setDraft({ ...draft, state: event.target.value as BankCard["state"] })}><option value="active">Активна</option><option value="draft">Черновик</option><option value="suspended">Приостановлена</option><option value="lost-source">Источник потерян</option></select></div>
      <footer><Button variant="ghost" onClick={onDelete}><Trash2 size={14} /> Удалить</Button><Button variant="secondary" onClick={() => setDraft(card)}>Отменить изменения</Button><Button onClick={() => onSave(draft)}><Pencil size={14} /> Сохранить</Button></footer>
    </aside>
  );
}
