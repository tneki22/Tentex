from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    BlockClass,
    Material,
    MaterialBlock,
    MaterialFragment,
    MaterialPage,
    MaterialSourceKind,
    PageQuality,
    RetrievalChunkKind,
    TypstSourceChunk,
)

_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)
_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+|\n{2,}")
_VISUAL_ONLY = re.compile(r"^\s*\[Изображение(?:[^]]*)?]\s*$", re.IGNORECASE)


def count_tokens(text: str) -> int:
    """Стабильная локальная оценка; runtime модели проверяет фактический лимит."""
    return len(_TOKEN_RE.findall(text))


@dataclass(frozen=True)
class ChunkAtom:
    text: str
    fragment_id: UUID | None = None
    page: int | None = None
    quality: PageQuality | None = None
    locator: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ChunkDraft:
    material_id: UUID
    revision: int
    block_id: UUID | None
    kind: RetrievalChunkKind
    title: str | None
    text: str
    token_count: int
    page_from: int | None
    page_to: int | None
    quality: PageQuality | None
    fragment_ids: list[UUID]
    locator: dict[str, object]
    content_hash: str


def _split_large_atom(atom: ChunkAtom, maximum: int) -> list[ChunkAtom]:
    if count_tokens(atom.text) <= maximum:
        return [atom]
    parts = [part.strip() for part in _SENTENCE_RE.split(atom.text) if part.strip()]
    result: list[ChunkAtom] = []
    pending = ""
    for part in parts or [atom.text]:
        candidate = f"{pending} {part}".strip()
        if pending and count_tokens(candidate) > maximum:
            result.append(
                ChunkAtom(pending, atom.fragment_id, atom.page, atom.quality, atom.locator)
            )
            pending = part
        else:
            pending = candidate
        while count_tokens(pending) > maximum:
            words = pending.split()
            cut = max(1, int(len(words) * maximum / count_tokens(pending)))
            result.append(
                ChunkAtom(
                    " ".join(words[:cut]), atom.fragment_id, atom.page, atom.quality, atom.locator
                )
            )
            pending = " ".join(words[cut:])
    if pending:
        result.append(ChunkAtom(pending, atom.fragment_id, atom.page, atom.quality, atom.locator))
    return result


def chunk_atoms(
    atoms: list[ChunkAtom], *, target_tokens: int, max_tokens: int, overlap_tokens: int
) -> list[list[ChunkAtom]]:
    """Собрать куски в границах одного блока и вернуть атомы для точных локаторов."""
    expanded = [piece for atom in atoms for piece in _split_large_atom(atom, max_tokens)]
    chunks: list[list[ChunkAtom]] = []
    current: list[ChunkAtom] = []
    current_tokens = 0
    for atom in expanded:
        atom_tokens = count_tokens(atom.text)
        if current and current_tokens + atom_tokens > max_tokens:
            chunks.append(current)
            overlap: list[ChunkAtom] = []
            overlap_size = 0
            for previous in reversed(current):
                size = count_tokens(previous.text)
                if overlap and overlap_size + size > overlap_tokens:
                    break
                overlap.insert(0, previous)
                overlap_size += size
            current = overlap
            current_tokens = overlap_size
        current.append(atom)
        current_tokens += atom_tokens
        if current_tokens >= target_tokens:
            chunks.append(current)
            current = []
            current_tokens = 0
    if current:
        chunks.append(current)
    return chunks


def _worst_quality(atoms: list[ChunkAtom]) -> PageQuality | None:
    order = {PageQuality.NATIVE: 0, PageQuality.OCR: 1, PageQuality.OCR_LOW: 2}
    qualities = [atom.quality for atom in atoms if atom.quality is not None]
    return max(qualities, key=order.__getitem__) if qualities else None


def _draft(
    material: Material,
    block_id: UUID | None,
    kind: RetrievalChunkKind,
    title: str | None,
    atoms: list[ChunkAtom],
) -> ChunkDraft:
    text = "\n\n".join(atom.text.strip() for atom in atoms if atom.text.strip())
    pages = [atom.page for atom in atoms if atom.page is not None]
    fragment_ids = list(dict.fromkeys(atom.fragment_id for atom in atoms if atom.fragment_id))
    locator = next((atom.locator for atom in atoms if atom.locator), {})
    return ChunkDraft(
        material_id=material.id,
        revision=material.active_parse_revision,
        block_id=block_id,
        kind=kind,
        title=title,
        text=text,
        token_count=count_tokens(text),
        page_from=min(pages) if pages else None,
        page_to=max(pages) if pages else None,
        quality=_worst_quality(atoms),
        fragment_ids=fragment_ids,
        locator=locator,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def material_chunks(
    session: Session,
    material: Material,
    *,
    target_tokens: int,
    max_tokens: int,
    overlap_tokens: int,
) -> list[ChunkDraft]:
    """Построить structural chunks активной ревизии материала."""
    if material.active_parse_revision <= 0:
        return []
    if material.source_kind == MaterialSourceKind.TYPST:
        return _typst_chunks(session, material, target_tokens, max_tokens, overlap_tokens)
    rows = session.execute(
        select(MaterialBlock, MaterialFragment, MaterialPage)
        .join(MaterialFragment, MaterialFragment.block_id == MaterialBlock.id)
        .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
        .where(
            MaterialBlock.material_id == material.id,
            MaterialBlock.revision == material.active_parse_revision,
            MaterialBlock.block_class == BlockClass.CONTENT,
            MaterialPage.revision == material.active_parse_revision,
        )
        .order_by(MaterialBlock.sort_order, MaterialPage.page_number, MaterialFragment.sort_order)
    ).all()
    grouped: dict[UUID, tuple[MaterialBlock, list[ChunkAtom]]] = {}
    for block, fragment, page in rows:
        if not fragment.text.strip() or _VISUAL_ONLY.match(fragment.text):
            continue
        entry = grouped.setdefault(block.id, (block, []))
        entry[1].append(ChunkAtom(fragment.text, fragment.id, page.page_number, fragment.quality))
    drafts: list[ChunkDraft] = []
    for block, atoms in grouped.values():
        for group in chunk_atoms(
            atoms,
            target_tokens=target_tokens,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        ):
            drafts.append(_draft(material, block.id, RetrievalChunkKind.TEXT, block.title, group))
    return drafts


def _typst_chunks(
    session: Session,
    material: Material,
    target_tokens: int,
    max_tokens: int,
    overlap_tokens: int,
) -> list[ChunkDraft]:
    rows = list(
        session.scalars(
            select(TypstSourceChunk)
            .where(
                TypstSourceChunk.material_id == material.id,
                TypstSourceChunk.revision == material.active_parse_revision,
            )
            .order_by(TypstSourceChunk.sort_order)
        )
    )
    drafts: list[ChunkDraft] = []
    for source in rows:
        atom = ChunkAtom(
            source.source_text,
            page=source.page_from,
            locator={
                "typst_path": source.path,
                "line_from": source.line_from,
                "line_to": source.line_to,
            },
        )
        for group in chunk_atoms(
            [atom],
            target_tokens=target_tokens,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        ):
            drafts.append(
                _draft(
                    material,
                    None,
                    RetrievalChunkKind.TYPST_SOURCE,
                    source.path,
                    group,
                )
            )
    return drafts
