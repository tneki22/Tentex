import type { ProgramNodeRead } from "../api/projects";

export interface ProgramTreeNode extends ProgramNodeRead {
  children: ProgramTreeNode[];
  depth: number;
  number: string;
}

export function buildProgramTree(nodes: ProgramNodeRead[]): ProgramTreeNode[] {
  const ids = new Set<string>();
  for (const node of nodes) {
    if (ids.has(node.id)) throw new Error(`Повторяющийся id узла: ${node.id}`);
    ids.add(node.id);
  }
  for (const node of nodes) {
    if (node.parent_id && !ids.has(node.parent_id)) {
      throw new Error(`У узла «${node.title}» отсутствует родитель`);
    }
  }

  const children = new Map<string | null, ProgramNodeRead[]>();
  for (const node of nodes) {
    const siblings = children.get(node.parent_id) ?? [];
    siblings.push(node);
    children.set(node.parent_id, siblings);
  }
  for (const siblings of children.values()) {
    siblings.sort((left, right) => left.sort_order - right.sort_order || left.id.localeCompare(right.id));
  }

  const visiting = new Set<string>();
  const visited = new Set<string>();
  const build = (node: ProgramNodeRead, depth: number, number: string): ProgramTreeNode => {
    if (visiting.has(node.id)) throw new Error("В дереве программы обнаружен цикл");
    visiting.add(node.id);
    const result: ProgramTreeNode = {
      ...node,
      depth,
      number,
      children: (children.get(node.id) ?? []).map((child, index, siblings) =>
        build(
          child,
          depth + 1,
          `${number}.${siblings.slice(0, index + 1).filter((item) => item.is_in_current_program && !item.is_archived).length}`,
        )),
    };
    visiting.delete(node.id);
    visited.add(node.id);
    return result;
  };
  const roots = (children.get(null) ?? []).map((node, index, siblings) =>
    build(
      node,
      1,
      String(siblings.slice(0, index + 1).filter((item) => item.is_in_current_program && !item.is_archived).length),
    ));
  if (visited.size !== nodes.length) throw new Error("Часть дерева программы недоступна от корня");
  return roots;
}

export function flattenProgramTree(tree: ProgramTreeNode[]): ProgramTreeNode[] {
  const result: ProgramTreeNode[] = [];
  const visit = (nodes: ProgramTreeNode[]) => {
    for (const node of nodes) {
      result.push(node);
      visit(node.children);
    }
  };
  visit(tree);
  return result;
}

/**
 * Фильтрует дерево без потери контекста: совпавший глубокий узел всегда
 * возвращается вместе со всей цепочкой родителей.
 */
export function filterProgramTree(
  tree: ProgramTreeNode[],
  query: string,
): ProgramTreeNode[] {
  const normalized = query.trim().toLocaleLowerCase("ru");
  if (!normalized) return tree;

  return tree.flatMap((node) => {
    const children = filterProgramTree(node.children, normalized);
    const matches = node.title.toLocaleLowerCase("ru").includes(normalized);
    return matches || children.length ? [{ ...node, children }] : [];
  });
}

export function visibleHiddenRoots(nodes: ProgramNodeRead[]): ProgramNodeRead[] {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  return [...nodes]
    .filter((node) => {
      if (node.is_in_current_program) return false;
      if (!node.parent_id) return true;
      return byId.get(node.parent_id)?.is_in_current_program !== false;
    })
    .sort((left, right) => left.sort_order - right.sort_order || left.title.localeCompare(right.title, "ru"));
}
