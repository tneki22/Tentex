import type { WorkspaceLayout } from "../../api/projects";

const PREFIX = "tentex:detached-pane:";

interface DetachedPaneState {
  projectId: string;
  layout: WorkspaceLayout;
}

export function readDetachedPane(id: string, projectId: string): WorkspaceLayout | null {
  try {
    const raw = window.localStorage.getItem(`${PREFIX}${id}`);
    if (!raw) return null;
    const state = JSON.parse(raw) as DetachedPaneState;
    return state.projectId === projectId
      && Array.isArray(state.layout?.groups)
      && state.layout.groups.length === 1
      && Array.isArray(state.layout.groups[0]?.tabs)
      && Array.isArray(state.layout.expanded_node_ids)
      && Array.isArray(state.layout.group_weights)
      ? state.layout
      : null;
  } catch {
    return null;
  }
}

export function writeDetachedPane(id: string, projectId: string, layout: WorkspaceLayout): void {
  window.localStorage.setItem(`${PREFIX}${id}`, JSON.stringify({ projectId, layout } satisfies DetachedPaneState));
}

export function removeDetachedPane(id: string): void {
  window.localStorage.removeItem(`${PREFIX}${id}`);
}
