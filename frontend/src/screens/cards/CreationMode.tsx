import { useEffect, useState } from "react";
import { Link } from "react-router";
import { ArrowLeft, Check, FileText, Minus, Pencil, Plus, Search, Sparkles, WandSparkles } from "lucide-react";
import { Button, Checkbox, Field, PageHead, Progress, RadioCards, SegmentedTabs, Switch, type RadioCardOption } from "../../components/ui";
import { CostEstimate, MachineMark, OfflineNotice } from "../../components/domain";
import { AI_DRAFTS, CARD_KIND_LABEL, CREATION_QUESTIONS, DRAFT_PLAN, type AiDraft, type CardKind } from "./mockCards";

export type CreationPath = "manual" | "ai" | "fragment";

interface CreationModeProps {
  projectId: string;
  initialPath: CreationPath | null;
  onOpenBank: () => void;
  onStartStudy: () => void;
}

const PATHS: RadioCardOption<CreationPath>[] = [
  { value: "manual", title: "Вручную", description: "Выберите вопрос и создайте одну или несколько точных карточек.", icon: <Pencil size={22} /> },
  { value: "ai", title: "С помощью ИИ", description: "Tentex предложит разбиение и создаст черновики для проверки.", icon: <Sparkles size={22} /> },
  { value: "fragment", title: "Из фрагмента материала", description: "Выделите доказательный фрагмент — ссылка сохранится автоматически.", icon: <FileText size={22} /> },
];

function cardsLabel(count: number) {
  const mod100 = count % 100;
  const mod10 = count % 10;
  if (mod100 >= 11 && mod100 <= 14) return "карточек";
  if (mod10 === 1) return "карточка";
  if (mod10 >= 2 && mod10 <= 4) return "карточки";
  return "карточек";
}

function countLabel(count: number, one: string, few: string, many: string) {
  const mod100 = count % 100;
  const mod10 = count % 10;
  if (mod100 >= 11 && mod100 <= 14) return many;
  if (mod10 === 1) return one;
  if (mod10 >= 2 && mod10 <= 4) return few;
  return many;
}

export function CreationMode({ projectId, initialPath, onOpenBank, onStartStudy }: CreationModeProps) {
  const [path, setPath] = useState<CreationPath | null>(initialPath);

  if (path === "manual") return <ManualCreator onBack={() => setPath(null)} onOpenBank={onOpenBank} />;
  if (path === "ai") return <AiCreator onBack={() => setPath(null)} onOpenBank={onOpenBank} onStartStudy={onStartStudy} />;
  if (path === "fragment") return <FragmentCreator projectId={projectId} onBack={() => setPath(null)} />;

  return (
    <div className="creation-mode">
      <PageHead eyebrow="Новые карточки" title="Как создаём?" lead="Карточка проверяет одну мысль. Для длинного билета лучше сделать пакет коротких карточек и один опорный план." />
      <RadioCards label="Способ создания карточек" value={path} options={PATHS} onChange={setPath} className="creation-paths" />
      <section className="creation-principle">
        <strong>Не всё стоит превращать в карточку</strong>
        <p>Определения и условия — в короткие карточки; структуру билета — в опорный план; связный рассказ и задачи — в отдельную Сессию занятия.</p>
      </section>
    </div>
  );
}

function ManualCreator({ onBack, onOpenBank }: { onBack: () => void; onOpenBank: () => void }) {
  const [query, setQuery] = useState("");
  const [questionId, setQuestionId] = useState(CREATION_QUESTIONS[0].id);
  const [kind, setKind] = useState<CardKind>("atomic");
  const [front, setFront] = useState("Чем третья нормальная форма отличается от НФБК?");
  const [back, setBack] = useState("НФБК требует, чтобы каждый детерминант был потенциальным ключом; 3НФ допускает исключение для ключевого атрибута.");
  const [hint, setHint] = useState("Сравните требования к детерминанту");
  const [source, setSource] = useState("reference");
  const [reverse, setReverse] = useState(false);
  const [saved, setSaved] = useState(0);
  const [error, setError] = useState("");
  const question = CREATION_QUESTIONS.find((item) => item.id === questionId)!;

  function save(addAnother = false) {
    if (!front.trim() || !back.trim()) {
      setError("Заполните обе стороны карточки.");
      return;
    }
    setError("");
    setSaved((value) => value + (reverse && kind === "definition" ? 2 : 1));
    if (addAnother) {
      setFront("");
      setBack("");
      setHint("");
    }
  }

  return (
    <div className="manual-creator">
      <PageHead
        eyebrow="Создание вручную"
        title="Новая карточка"
        actions={<Button variant="ghost" onClick={onBack}><ArrowLeft size={15} /> К способам</Button>}
      />
      {saved > 0 && <div className="creation-success"><Check size={15} /> Сохранено карточек: {saved}. <button type="button" onClick={onOpenBank}>Открыть Банк</button></div>}
      <div className="manual-layout">
        <aside className="manual-question-list">
          <label><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Найти вопрос" /></label>
          <button type="button" className={questionId === "none" ? "is-active" : ""} onClick={() => setQuestionId("none")}><span>Без вопроса</span><small>личная карточка</small></button>
          {CREATION_QUESTIONS.filter((item) => `${item.title} ${item.section}`.toLocaleLowerCase("ru").includes(query.toLocaleLowerCase("ru"))).map((item) => (
            <button type="button" className={questionId === item.id ? "is-active" : ""} key={item.id} onClick={() => setQuestionId(item.id)}>
              <span>{item.title}</span><small>{item.section} · {item.existing} {cardsLabel(item.existing)}</small>
            </button>
          ))}
        </aside>
        <section className="manual-form">
          <div className="manual-form-head"><div><span>Вопрос</span><strong>{questionId === "none" ? "Без вопроса" : question.title}</strong></div><small>Можно сохранить несколько карточек подряд</small></div>
          <Field label="Тип карточки">
            <SegmentedTabs label="Тип карточки" value={kind} onChange={setKind} tabs={[
              { value: "atomic", label: "Короткая" }, { value: "plan", label: "План" }, { value: "definition", label: "Термин" }, { value: "comparison", label: "Сравнение" },
            ]} />
          </Field>
          <Field label="Лицевая сторона" required error={error && !front.trim() ? error : undefined}><textarea rows={4} value={front} onChange={(event) => setFront(event.target.value)} placeholder="Одна проверяемая мысль" /></Field>
          <Field label="Обратная сторона" required error={error && !back.trim() ? error : undefined} hint={`${back.length} символов`}><textarea rows={7} value={back} onChange={(event) => setBack(event.target.value)} placeholder="Короткий однозначный ответ" /></Field>
          <Field label="Источник">
            <select value={source} onChange={(event) => setSource(event.target.value)}><option value="reference">Эталонный ответ</option><option value="fragment">Учебник · выбрать фрагмент</option><option value="manual">Личная карточка без источника</option></select>
          </Field>
          <Field label="Подсказка" hint="Необязательно. Лучше опорный тезис, а не часть ответа."><input value={hint} onChange={(event) => setHint(event.target.value)} /></Field>
          {kind === "definition" && <Switch checked={reverse} onCheckedChange={setReverse} label="Создать обратную карточку" hint="Определение → термин. Для других типов не включается автоматически." />}
          <div className="manual-actions"><Button variant="secondary" onClick={() => save(true)}>Сохранить и добавить ещё</Button><Button onClick={() => save(false)}>Сохранить</Button></div>
        </section>
        <aside className="manual-preview">
          <span>Живой предпросмотр</span>
          <article>
            <small>{CARD_KIND_LABEL[kind]} · {questionId === "none" ? "без вопроса" : question.title}</small>
            <h2>{front || "Лицевая сторона"}</h2>
            <div><b>Ответ</b><p>{back || "Обратная сторона"}</p></div>
            {hint && <em>Подсказка: {hint}</em>}
            <footer>{source === "reference" ? "Эталонный ответ" : source === "fragment" ? "Фрагмент материала" : "Личная карточка · источника нет"}</footer>
          </article>
          {back.length > 500 && <p className="creation-warning">Ответ длиннее одного экрана. Разделите его на несколько мыслей или сделайте опорный план.</p>}
        </aside>
      </div>
    </div>
  );
}

function FragmentCreator({ projectId, onBack }: { projectId: string; onBack: () => void }) {
  return (
    <div className="fragment-creator">
      <PageHead eyebrow="Создание из источника" title="Карточка из фрагмента" actions={<Button variant="ghost" onClick={onBack}><ArrowLeft size={15} /> К способам</Button>} />
      <section>
        <div className="fragment-steps"><span>1</span><div><strong>Откройте материал</strong><p>Выберите учебник, лекцию или эталонный ответ.</p></div><span>2</span><div><strong>Выделите точный фрагмент</strong><p>Tentex сохранит материал, страницу и координаты.</p></div><span>3</span><div><strong>Нажмите «В карточку»</strong><p>Фрагмент станет ответом или подсказкой, а вопрос отредактируете перед сохранением.</p></div></div>
        <Link className="primary-button" to={`/projects/${projectId}/materials`}><FileText size={15} /> Перейти к материалам</Link>
      </section>
    </div>
  );
}

type AiStage = 1 | 2 | 3 | 4 | 5 | "generating" | "review";
type SourceMode = "reference" | "both" | "materials";
type Depth = "base" | "recommended" | "detailed";
type LongMode = "split" | "shorten" | "keep";
type QuestionFilter = "all" | "without" | "reference" | "materials";

function AiCreator({ onBack, onOpenBank, onStartStudy }: { onBack: () => void; onOpenBank: () => void; onStartStudy: () => void }) {
  const [stage, setStage] = useState<AiStage>(1);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<QuestionFilter>("all");
  const [selected, setSelected] = useState(() => new Set(CREATION_QUESTIONS.slice(0, 4).map((item) => item.id)));
  const [sourceMode, setSourceMode] = useState<SourceMode>("reference");
  const [modelKnowledge, setModelKnowledge] = useState(false);
  const [modelsEnabled, setModelsEnabled] = useState(true);
  const [depth, setDepth] = useState<Depth>("recommended");
  const [counts, setCounts] = useState<Record<string, number>>(() => Object.fromEntries(DRAFT_PLAN.map((item) => [item.id, item.proposed])));
  const [longMode, setLongMode] = useState<LongMode>("split");
  const [limit, setLimit] = useState("350");
  const [verbatim, setVerbatim] = useState(true);
  const [hints, setHints] = useState(true);
  const [reverse, setReverse] = useState(false);
  const [avoidExamples, setAvoidExamples] = useState(true);
  const [wish, setWish] = useState("Делай упор на различия нормальных форм. Определения сохраняй близко к эталону.");
  const [generated, setGenerated] = useState(0);
  const [drafts, setDrafts] = useState(AI_DRAFTS);
  const [draftStatus, setDraftStatus] = useState<Record<string, "pending" | "accepted" | "rejected">>({});
  const [activeDraftId, setActiveDraftId] = useState(AI_DRAFTS[0].id);
  const [reviewNotice, setReviewNotice] = useState("");

  const visibleQuestions = CREATION_QUESTIONS.filter((item) => {
    if (query && !`${item.title} ${item.section}`.toLocaleLowerCase("ru").includes(query.toLocaleLowerCase("ru"))) return false;
    if (filter === "without" && item.existing > 0) return false;
    if (filter === "reference" && !item.hasReference) return false;
    if (filter === "materials" && item.fragments === 0) return false;
    return true;
  });
  const selectedPlan = DRAFT_PLAN.filter((item) => selected.has(item.id));
  const totalDrafts = selectedPlan.reduce((sum, item) => sum + (counts[item.id] ?? 0), 0);
  const activeDraft = drafts.find((draft) => draft.id === activeDraftId) ?? drafts[0];
  const accepted = Object.values(draftStatus).filter((status) => status === "accepted").length;
  const rejected = Object.values(draftStatus).filter((status) => status === "rejected").length;

  useEffect(() => {
    if (stage !== "generating") return;
    const timer = window.setInterval(() => {
      setGenerated((value) => {
        if (value >= selected.size) {
          window.clearInterval(timer);
          window.setTimeout(() => setStage("review"), 450);
          return value;
        }
        return value + 1;
      });
    }, 280);
    return () => window.clearInterval(timer);
  }, [stage, selected.size]);

  function toggleQuestion(id: string, checked: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      if (checked) next.add(id); else next.delete(id);
      return next;
    });
  }

  function updateDraft(field: "front" | "back" | "kind", value: string) {
    if (!activeDraft) return;
    setDrafts((current) => current.map((draft) => draft.id === activeDraft.id ? { ...draft, [field]: value } as AiDraft : draft));
  }

  if (stage === "generating") {
    return (
      <section className="ai-generating">
        <MachineMark origin="генерация с помощью ИИ" />
        <WandSparkles size={30} />
        <h1>Разбираем вопросы на карточки</h1>
        <p>Готово {generated} из {selected.size} вопросов. Уже создано {Math.min(totalDrafts, Math.round((generated / Math.max(1, selected.size)) * totalDrafts))} черновиков.</p>
        <Progress value={generated} max={selected.size} label="Генерация карточек" />
        <small>Если провайдер остановится, готовые черновики сохранятся.</small>
      </section>
    );
  }

  if (stage === "review") {
    return (
      <div className="ai-review">
        <PageHead eyebrow="Проверка ИИ-черновиков" title="Ничего не попадёт в повторение без вас" actions={<Button variant="ghost" onClick={() => setStage(5)}><ArrowLeft size={15} /> К плану</Button>} />
        <div className="ai-review-summary"><span>Принято <b>{accepted}</b></span><span>Отклонено <b>{rejected}</b></span><span>Осталось <b>{drafts.length - accepted - rejected}</b></span></div>
        <div className="ai-review-layout">
          <aside className="ai-draft-list">
            {drafts.map((draft) => (
              <button type="button" className={`${activeDraft?.id === draft.id ? "is-active" : ""} is-${draftStatus[draft.id] ?? "pending"}`.trim()} key={draft.id} onClick={() => setActiveDraftId(draft.id)}>
                <small>{draft.question}</small><span>{draft.front}</span><em>{draftStatus[draft.id] === "accepted" ? "принято" : draftStatus[draft.id] === "rejected" ? "отклонено" : draft.warning ? "нужно проверить" : "черновик"}</em>
              </button>
            ))}
          </aside>
          {activeDraft && <section className="ai-draft-editor">
            <MachineMark origin="создано ИИ" onUndo={() => setDraftStatus((current) => ({ ...current, [activeDraft.id]: "rejected" }))} undoLabel="Отклонить черновик" />
            {activeDraft.warning && <p className="creation-warning">{activeDraft.warning}</p>}
            <Field label="Тип"><select value={activeDraft.kind} onChange={(event) => updateDraft("kind", event.target.value)}>{Object.entries(CARD_KIND_LABEL).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></Field>
            <Field label="Лицевая сторона"><textarea rows={4} value={activeDraft.front} onChange={(event) => updateDraft("front", event.target.value)} /></Field>
            <Field label="Обратная сторона" hint={`${activeDraft.back.length} символов`}><textarea rows={7} value={activeDraft.back} onChange={(event) => updateDraft("back", event.target.value)} /></Field>
            <div className="ai-draft-actions"><Button variant="ghost" onClick={() => setDraftStatus((current) => ({ ...current, [activeDraft.id]: "rejected" }))}>Отклонить</Button><Button variant="secondary" onClick={() => { updateDraft("front", `${activeDraft.front} — уточнённая формулировка`); setReviewNotice("Карточка перегенерирована, проверьте изменения."); }}>Перегенерировать</Button><Button onClick={() => setDraftStatus((current) => ({ ...current, [activeDraft.id]: "accepted" }))}><Check size={15} /> Принять</Button></div>
          </section>}
          {activeDraft && <aside className="ai-draft-source"><span>Подтверждение</span><strong>{activeDraft.source}</strong><p>{activeDraft.back}</p><div><button type="button" onClick={() => setReviewNotice("Выберите соседний черновик для объединения.")}>Объединить</button><button type="button" onClick={() => { const copy = { ...activeDraft, id: `${activeDraft.id}-part-${drafts.length}`, front: `${activeDraft.front} — продолжение` }; setDrafts((current) => [...current, copy]); setReviewNotice("Добавлена вторая карточка. Отредактируйте обе части."); }}>Разбить на две</button></div></aside>}
        </div>
        {reviewNotice && <p className="cards-inline-notice" role="status">{reviewNotice}</p>}
        <footer className="ai-review-footer"><span>Новые карточки останутся черновиками, пока вы их не примете.</span><Button variant="secondary" onClick={onOpenBank}>Сохранить в Банк</Button><Button disabled={accepted === 0} onClick={onStartStudy}>Изучить принятые сейчас</Button></footer>
      </div>
    );
  }

  const numericStage = stage as 1 | 2 | 3 | 4 | 5;
  return (
    <div className="ai-creator">
      <PageHead eyebrow="Создание с помощью ИИ" title="Мастер карточек" actions={<Button variant="ghost" onClick={onBack}><ArrowLeft size={15} /> К способам</Button>} />
      <nav className="ai-wizard-steps" aria-label="Шаги мастера">
        {["Вопросы", "Источники", "Количество", "Длинные ответы", "План"].map((label, index) => {
          const number = (index + 1) as 1 | 2 | 3 | 4 | 5;
          return <button type="button" className={numericStage === number ? "is-active" : numericStage > number ? "is-complete" : ""} disabled={number > numericStage} key={label} onClick={() => setStage(number)}><span>{numericStage > number ? <Check size={13} /> : number}</span>{label}</button>;
        })}
      </nav>

      <div className="ai-wizard-body">
        {stage === 1 && <section className="ai-question-step">
          <div className="ai-step-head"><div><h2>Выберите вопросы</h2><p>На один вопрос можно создать целый пакет карточек.</p></div><span>{selected.size} выбрано</span></div>
          <div className="ai-question-toolbar"><label><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Найти вопрос" /></label><SegmentedTabs label="Фильтр вопросов" value={filter} onChange={setFilter} tabs={[{ value: "all", label: "Все" }, { value: "without", label: "Без карточек" }, { value: "reference", label: "С эталоном" }, { value: "materials", label: "С материалом" }]} /></div>
          <div className="ai-question-list">{visibleQuestions.map((item) => <div key={item.id}><Checkbox checked={selected.has(item.id)} onCheckedChange={(checked) => toggleQuestion(item.id, checked)} label={item.title} /><span>{item.hasReference ? "Есть эталон" : "Нет эталона"} · {item.fragments ? `${item.fragments} ${countLabel(item.fragments, "фрагмент", "фрагмента", "фрагментов")}` : "нет материалов"} · {item.existing} {cardsLabel(item.existing)}</span></div>)}</div>
        </section>}

        {stage === 2 && <section>
          <div className="ai-step-head"><div><h2>Из чего создавать?</h2><p>По умолчанию используем только проверенный эталонный ответ.</p></div></div>
          <RadioCards label="Источники карточек" value={sourceMode} onChange={setSourceMode} layout="rows" options={[
            { value: "reference", title: "Только эталонные ответы", description: "Самый предсказуемый вариант для экзамена." },
            { value: "both", title: "Эталоны и связанные материалы", description: "Больше деталей, условий и исключений." },
            { value: "materials", title: "Только связанные материалы", description: "Подходит, если эталонных ответов нет." },
          ]} />
          <Switch checked={modelKnowledge} onCheckedChange={setModelKnowledge} label="Разрешить знания модели вне источников" hint="Выключено по умолчанию: иначе происхождение утверждения нельзя проверить." />
          <Switch checked={modelsEnabled} onCheckedChange={setModelsEnabled} label="Внешняя модель доступна" hint="Демонстрационное состояние мастера." />
          {!modelsEnabled && <OfflineNotice reason="disabled" alternative="Ручное создание остаётся доступно." />}
          <div className="ai-data-preview"><strong>Перед запуском отправим</strong><span>{selected.size} {countLabel(selected.size, "вопрос", "вопроса", "вопросов")}</span><span>{CREATION_QUESTIONS.filter((item) => selected.has(item.id) && item.hasReference).length} {countLabel(CREATION_QUESTIONS.filter((item) => selected.has(item.id) && item.hasReference).length, "эталон", "эталона", "эталонов")}</span><span>{CREATION_QUESTIONS.filter((item) => selected.has(item.id)).reduce((sum, item) => sum + item.fragments, 0)} фрагментов</span><span>GPT-5 mini</span></div>
        </section>}

        {stage === 3 && <section>
          <div className="ai-step-head"><div><h2>Глубина и количество</h2><p>Рекомендация зависит от числа независимо важных мыслей, а не от длины текста.</p></div><strong>≈ {totalDrafts} {cardsLabel(totalDrafts)}</strong></div>
          <RadioCards label="Глубина карточек" value={depth} onChange={setDepth} options={[
            { value: "base", title: "Основа", description: "Только обязательные определения и тезисы." },
            { value: "recommended", title: "Рекомендуем", description: "Разумное покрытие вопроса без мелочей." },
            { value: "detailed", title: "Подробно", description: "Условия, различия и исключения." },
          ]} />
          <div className="ai-count-list">{selectedPlan.map((item) => <div key={item.id}><span><strong>{item.title}</strong><small>{item.breakdown}</small></span><span className="ai-count-control"><button type="button" aria-label="Уменьшить" onClick={() => setCounts((current) => ({ ...current, [item.id]: Math.max(0, current[item.id] - 1) }))}><Minus size={14} /></button><b>{counts[item.id]}</b><button type="button" aria-label="Увеличить" onClick={() => setCounts((current) => ({ ...current, [item.id]: current[item.id] + 1 }))}><Plus size={14} /></button></span></div>)}</div>
          <p className="ai-introduction-estimate">При лимите 5 новых карточек в день ввод займёт около {Math.ceil(totalDrafts / 5)} дней.</p>
        </section>}

        {stage === 4 && <section>
          <div className="ai-step-head"><div><h2>Длинные ответы</h2><p>Полный исходный ответ всегда остаётся доступен в источнике.</p></div></div>
          <RadioCards label="Длинные ответы" value={longMode} onChange={setLongMode} layout="rows" options={[
            { value: "split", title: "Разбивать на несколько карточек", description: "Рекомендуем: план, определения, условия, различия и исключения." },
            { value: "shorten", title: "Сокращать", description: "Мягкая цель длины без молчаливого обрезания." },
            { value: "keep", title: "Оставлять целиком", description: "Подходит редко: ответ может занимать два экрана." },
          ]} />
          {longMode === "shorten" && <Field label="Примерная длина обратной стороны" hint="символов; полная версия остаётся в источнике"><input inputMode="numeric" value={limit} onChange={(event) => setLimit(event.target.value)} /></Field>}
          {longMode === "keep" && <p className="creation-warning">Длинная карточка хуже подходит для честной самопроверки. Проверьте её особенно внимательно.</p>}
          <div className="ai-options-grid"><Switch checked={verbatim} onCheckedChange={setVerbatim} label="Определения дословно" /><Switch checked={hints} onCheckedChange={setHints} label="Добавлять подсказки" /><Switch checked={reverse} onCheckedChange={setReverse} label="Обратные карточки терминов" /><Switch checked={avoidExamples} onCheckedChange={setAvoidExamples} label="Не делать карточки из примеров" /></div>
          <Field label="Пожелания" hint="Напишите, на чём сделать акцент и какие формулировки сохранить."><textarea rows={5} value={wish} onChange={(event) => setWish(event.target.value)} /></Field>
        </section>}

        {stage === 5 && <section className="ai-plan-step">
          <div className="ai-step-head"><div><h2>План генерации</h2><p>Проверьте состав до обращения к внешней модели.</p></div></div>
          <dl><div><dt>Вопросы</dt><dd>{selected.size}</dd></div><div><dt>Предполагаемые карточки</dt><dd>{totalDrafts}</dd></div><div><dt>Источники</dt><dd>{sourceMode === "reference" ? "Только эталонные ответы" : sourceMode === "both" ? "Эталоны и материалы" : "Только материалы"}</dd></div><div><dt>Длинные ответы</dt><dd>{longMode === "split" ? "Разбивать" : longMode === "shorten" ? `Сокращать примерно до ${limit} символов` : "Оставлять целиком"}</dd></div><div><dt>Знания модели</dt><dd>{modelKnowledge ? "Разрешены и будут помечены" : "Запрещены"}</dd></div><div><dt>Пожелание</dt><dd>{wish || "Нет"}</dd></div></dl>
          <CostEstimate calls={selected.size} cost={0.08} minutes={2} pricesFrom="01.08.2026" units={`${selected.size} ${countLabel(selected.size, "вопрос", "вопроса", "вопросов")}`} />
          {!modelsEnabled && <OfflineNotice reason="disabled" alternative="Вернитесь к ручному созданию или включите модель." />}
        </section>}
      </div>

      <footer className="ai-wizard-footer">
        <Button variant="ghost" disabled={numericStage === 1} onClick={() => setStage((numericStage - 1) as 1 | 2 | 3 | 4)}>Назад</Button>
        <span>Шаг {numericStage} из 5</span>
        {numericStage < 5 ? <Button disabled={numericStage === 1 && selected.size === 0} onClick={() => setStage((numericStage + 1) as 2 | 3 | 4 | 5)}>Продолжить</Button> : <Button disabled={!modelsEnabled || selected.size === 0} onClick={() => { setGenerated(0); setStage("generating"); }}><Sparkles size={15} /> Начать генерацию</Button>}
      </footer>
    </div>
  );
}
