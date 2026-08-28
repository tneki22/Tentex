import { useCallback, useEffect, useRef, useState } from "react";
import {
  activateWizardDraft,
  createWizardDraft,
  discardWizardDraft,
  getWizardDraft,
  importExamProgram,
  ProjectApiError,
  saveWizardDraft,
  undoProjectAction,
  type ActionUndoResult,
  type ExamFormat,
  type ExamImportResult,
  type ProgramChangeResult,
  type ProjectDetail,
  type TemplateKey,
  type WizardDraftCommand,
  type WizardDraftDetail,
} from "../api/projects";

type DraftStatus = "idle" | "loading" | "ready" | "saving" | "error";

export interface WizardDraftController {
  detail: WizardDraftDetail | null;
  /** Меняется только после гидратации с сервера, не после локального сохранения. */
  hydrationVersion: number;
  status: DraftStatus;
  error: Error | null;
  conflict: ProjectApiError | null;
  ensureDraft: () => Promise<WizardDraftDetail>;
  queueSave: (command: Omit<WizardDraftCommand, "expected_revision">) => Promise<WizardDraftDetail>;
  enqueueProgramCommand: (command: (detail: WizardDraftDetail) => Promise<ProgramChangeResult>) => Promise<ProgramChangeResult>;
  undo: () => Promise<ActionUndoResult>;
  importExam: (rawText: string, examFormat: Exclude<ExamFormat, "unknown">, dedupeDuplicates?: boolean) => Promise<ExamImportResult>;
  activate: () => Promise<ProjectDetail>;
  discard: () => Promise<void>;
  flush: () => Promise<void>;
  reload: () => Promise<void>;
}

export function useWizardDraft({
  templateKey,
  projectId,
}: {
  templateKey: TemplateKey;
  projectId?: string | null;
}): WizardDraftController {
  const [detail, setDetail] = useState<WizardDraftDetail | null>(null);
  const [hydrationVersion, setHydrationVersion] = useState(0);
  const [status, setStatus] = useState<DraftStatus>(projectId ? "loading" : "idle");
  const [error, setError] = useState<Error | null>(null);
  const [conflict, setConflict] = useState<ProjectApiError | null>(null);
  const detailRef = useRef<WizardDraftDetail | null>(null);
  const queueRef = useRef<Promise<unknown>>(Promise.resolve());
  const createRequestRef = useRef<Promise<WizardDraftDetail> | null>(null);
  const blockedRef = useRef(false);
  const loadRequestRef = useRef(0);

  const accept = useCallback((next: WizardDraftDetail, { hydrated = false }: { hydrated?: boolean } = {}) => {
    detailRef.current = next;
    setDetail(next);
    if (hydrated) setHydrationVersion((current) => current + 1);
    setStatus("ready");
    setError(null);
  }, []);

  const fail = useCallback((caught: unknown) => {
    const nextError = caught instanceof Error ? caught : new Error("Не удалось сохранить черновик");
    if (caught instanceof ProjectApiError && ["stale_draft_revision", "stale_program_revision", "stale_action_sequence"].includes(caught.code ?? "")) {
      blockedRef.current = true;
      setConflict(caught);
    } else {
      setError(nextError);
    }
    setStatus("error");
    throw nextError;
  }, []);

  const reload = useCallback(async () => {
    const id = detailRef.current?.project.id ?? projectId;
    if (!id) return;
    setStatus("loading");
    try {
      const next = await getWizardDraft(id);
      blockedRef.current = false;
      setConflict(null);
      accept(next, { hydrated: true });
    } catch (caught) {
      return fail(caught) as never;
    }
  }, [accept, fail, projectId]);

  useEffect(() => {
    // После первого сохранения родитель добавляет id только что созданного черновика в URL.
    // Его уже актуальная версия лежит в detailRef; повторный GET может вернуть revision 0
    // после первого PUT и затереть revision 1, создавая ложный конфликт autosave.
    const requestId = ++loadRequestRef.current;
    if (!projectId) {
      detailRef.current = null;
      setDetail(null);
      setStatus("idle");
      setError(null);
      setConflict(null);
      return;
    }
    if (detailRef.current?.project.id === projectId) {
      setError(null);
      setStatus("ready");
      return;
    }
    const controller = new AbortController();
    setStatus("loading");
    void getWizardDraft(projectId, controller.signal)
      .then((next) => { if (!controller.signal.aborted && loadRequestRef.current === requestId) accept(next, { hydrated: true }); })
      .catch((caught) => {
        if (!controller.signal.aborted && loadRequestRef.current === requestId) {
          try { fail(caught); } catch { /* state already contains the error */ }
        }
      });
    return () => controller.abort();
  }, [accept, fail, projectId]);

  const ensureDraft = useCallback(async () => {
    const current = detailRef.current;
    if (current && (!projectId || current.project.id === projectId)) return current;

    // `projectId` means that the user chose an existing draft. The child wizard may
    // mount before the effect above starts its GET request, so it must never create
    // a new draft during that short interval.
    if (projectId) {
      setStatus("loading");
      try {
        const next = await getWizardDraft(projectId);
        accept(next, { hydrated: true });
        return next;
      } catch (caught) {
        return fail(caught) as never;
      }
    }

    if (createRequestRef.current) return createRequestRef.current;
    setStatus("saving");
    const request = createWizardDraft(templateKey)
      .then((next) => {
        accept(next);
        return next;
      })
      .catch((caught) => fail(caught) as never)
      .finally(() => {
        if (createRequestRef.current === request) createRequestRef.current = null;
      });
    createRequestRef.current = request;
    return request;
  }, [accept, fail, projectId, templateKey]);

  const enqueue = useCallback(<T,>(task: () => Promise<T>): Promise<T> => {
    const run = queueRef.current.then(async () => {
      if (blockedRef.current) throw conflict ?? new Error("Очередь сохранения остановлена из-за конфликта");
      return task();
    });
    queueRef.current = run.catch(() => undefined);
    return run;
  }, [conflict]);

  const queueSave = useCallback((command: Omit<WizardDraftCommand, "expected_revision">) => enqueue(async () => {
    const current = await ensureDraft();
    setStatus("saving");
    try {
      const next = await saveWizardDraft(current.project.id, {
        ...command,
        expected_revision: detailRef.current?.draft.revision ?? current.draft.revision,
      });
      accept(next);
      return next;
    } catch (caught) {
      return fail(caught) as never;
    }
  }), [accept, enqueue, ensureDraft, fail]);

  const enqueueProgramCommand = useCallback((command: (current: WizardDraftDetail) => Promise<ProgramChangeResult>) => enqueue(async () => {
    const current = await ensureDraft();
    setStatus("saving");
    try {
      const result = await command(detailRef.current ?? current);
      const latest = detailRef.current ?? current;
      accept({
        ...latest,
        draft: result.draft_revision === null ? latest.draft : { ...latest.draft, revision: result.draft_revision },
        program: result.program,
        latest_undoable_action: result.latest_undoable_action,
      });
      return result;
    } catch (caught) {
      return fail(caught) as never;
    }
  }), [accept, enqueue, ensureDraft, fail]);

  const importExam = useCallback((rawText: string, examFormat: Exclude<ExamFormat, "unknown">, dedupeDuplicates = false) => enqueue(async () => {
    const current = await ensureDraft();
    setStatus("saving");
    try {
      const latest = detailRef.current ?? current;
      const result = await importExamProgram(latest.project.id, {
        expected_revision: latest.draft.revision,
        expected_program_revision: latest.program.revision,
        exam_format: examFormat,
        raw_text: rawText,
        dedupe_duplicates: dedupeDuplicates,
      });
      accept({
        ...latest,
        draft: { ...latest.draft, revision: result.revision },
        program: result.program,
        latest_undoable_action: result.latest_undoable_action,
      });
      return result;
    } catch (caught) {
      return fail(caught) as never;
    }
  }), [accept, enqueue, ensureDraft, fail]);

  const undo = useCallback(() => enqueue(async () => {
    const current = await ensureDraft();
    const latest = detailRef.current ?? current;
    if (!latest.latest_undoable_action) throw new Error("Нет действия для отмены");
    setStatus("saving");
    try {
      const result = await undoProjectAction(latest.project.id, latest.latest_undoable_action.sequence);
      if (result.program) {
        accept({
          ...latest,
          draft: result.draft_revision === null ? latest.draft : { ...latest.draft, revision: result.draft_revision },
          program: result.program,
          latest_undoable_action: result.latest_undoable_action,
        });
      }
      return result;
    } catch (caught) {
      return fail(caught) as never;
    }
  }), [accept, enqueue, ensureDraft, fail]);

  const flush = useCallback(async () => { await queueRef.current; }, []);

  const activate = useCallback(() => enqueue(async () => {
    const current = await ensureDraft();
    const latest = detailRef.current ?? current;
    setStatus("saving");
    try {
      return await activateWizardDraft(latest.project.id, latest.draft.revision);
    } catch (caught) {
      return fail(caught) as never;
    }
  }), [enqueue, ensureDraft, fail]);

  const discard = useCallback(() => enqueue(async () => {
    const current = detailRef.current;
    if (!current) return;
    try {
      await discardWizardDraft(current.project.id, current.draft.revision);
      detailRef.current = null;
      setDetail(null);
      setStatus("idle");
    } catch (caught) {
      fail(caught);
    }
  }), [enqueue, fail]);

  const awaitingRequestedDraft = Boolean(
    projectId && detail?.project.id !== projectId && status !== "error",
  );

  return {
    detail,
    hydrationVersion,
    status: awaitingRequestedDraft ? "loading" : status,
    error,
    conflict,
    ensureDraft,
    queueSave,
    enqueueProgramCommand,
    undo,
    importExam,
    activate,
    discard,
    flush,
    reload,
  };
}
