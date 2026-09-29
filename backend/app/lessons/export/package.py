"""Файл уроков `.tentex-lessons`: уроки отдельно от проекта, для другой установки.

ZIP с `manifest.json`, `lessons.json` и изображениями уроков в `media/`. Материал
в файл не входит: кусок описан отпечатком файла (SHA-256), страницами, якорями
границ по тексту абзацев и снимком своего текста. В установке, где есть тот же
файл, кусок снова становится живой ссылкой; где нет — показывается снимком.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.lessons.export.collect import Collector, ExportOptions, note_body
from app.lessons.export.render_markdown import MarkdownRenderer
from app.lessons.export.resolve import text_hash
from app.lessons.service import _source_name, media_kind
from app.materials.storage import material_path
from app.models import (
    Lesson,
    LessonBlock,
    LessonBlockKind,
    LessonSourceRef,
    LessonTopic,
    Material,
    MaterialFragment,
    MaterialPage,
    ProgramNode,
    Project,
    ProjectMaterial,
    StudyTask,
    utc_now,
)
from app.storage.archive import APP_VERSION

FORMAT = "tentex-lessons"
FORMAT_VERSION = 1
SUFFIX = ".tentex-lessons"
# Что из `build_meta` переживает перенос: понятия нужны «уже известно» следующих
# уроков, подпись сборки — метке урока. Задача и прогоны остаются в старой установке.
BUILD_KEYS = ("template", "level", "basis", "model_id", "cost_usd", "concepts")
ANCHOR_TEXT = 160


def fragment_anchor(session: Session, fragment_id: UUID | None) -> dict[str, Any] | None:
    """Граница куска вне базы: страница, место на странице и отпечаток текста абзаца."""
    if fragment_id is None:
        return None
    row = session.execute(
        select(MaterialFragment.page_id, MaterialFragment.sort_order, MaterialFragment.text,
               MaterialPage.page_number)
        .join(MaterialPage, MaterialPage.id == MaterialFragment.page_id)
        .where(MaterialFragment.id == fragment_id)
    ).first()
    if row is None:
        return None
    page_id, sort_order, text, page_number = row
    index = session.scalar(
        select(func.count()).select_from(MaterialFragment)
        .where(MaterialFragment.page_id == page_id, MaterialFragment.sort_order < sort_order)
    )
    return {"page": page_number, "index": int(index or 0), "hash": text_hash(text),
            "text": " ".join((text or "").split())[:ANCHOR_TEXT]}


class PackageWriter:
    """Собирает содержимое файла уроков; картинки урока складывает в `media/`."""

    def __init__(self, session: Session, project_id: UUID, workdir: Path) -> None:
        self.session = session
        self.project_id = project_id
        self.collector = Collector(session, project_id, ExportOptions(sources="text"), workdir)
        self.snapshot = MarkdownRenderer(images=False)
        self.materials: dict[str, dict[str, Any]] = {}
        self.media: dict[str, Path] = {}

    def _material_key(self, material: Material | None, sha256: str | None, name: str,
                      page_count: int | None) -> str | None:
        digest = material.sha256 if material is not None else sha256
        if not digest:
            return None
        for key, item in self.materials.items():
            if item["sha256"] == digest:
                return key
        key = f"m{len(self.materials) + 1}"
        self.materials[key] = {"key": key, "sha256": digest, "name": name,
                               "page_count": page_count}
        return key

    def _ref(self, ref: LessonSourceRef) -> dict[str, Any]:
        material = self.session.get(Material, ref.material_id) if ref.material_id else None
        link = (self.session.get(ProjectMaterial, (self.project_id, material.id))
                if material is not None else None)
        name = _source_name(material, link, ref.source_name_snapshot)
        snapshot = ref.snapshot_md
        anchors = ref.snapshot_anchors or {}
        if material is not None:
            anchors = {"from": fragment_anchor(self.session, ref.from_fragment_id),
                       "to": fragment_anchor(self.session, ref.to_fragment_id)}
            if ref.region_bbox is None and material.active_parse_revision > 0:
                blocks = self.collector._fragment_blocks(material, ref)
                snapshot = self.snapshot.blocks(blocks) or None
        return {
            "role": ref.role.value,
            "material": self._material_key(material, ref.material_sha256, name,
                                           material.page_count if material else None),
            "name": name,
            "page_from": ref.page_from,
            "page_to": ref.page_to,
            "from": anchors.get("from"),
            "to": anchors.get("to"),
            "region_bbox": ref.region_bbox,
            "always_pages": ref.always_pages,
            "citation_label": ref.citation_label,
            "snapshot_md": snapshot,
        }

    def _media(self, block: LessonBlock) -> dict[str, Any] | None:
        kind = media_kind(block)
        if kind == "link":
            return {"url": block.media_path}
        if kind == "image" and block.media_path:
            path = material_path(block.media_path)
            if path.exists():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                name = f"media/{digest}{path.suffix.lower()}"
                self.media[name] = path
                return {"file": name}
        return None

    def _task(self, activity_id: UUID | None) -> dict[str, Any] | None:
        task = self.session.get(StudyTask, activity_id) if activity_id else None
        if task is None or task.deleted_at is not None:
            return None
        return {
            "form": task.form.value, "prompt_md": task.prompt_md, "payload": task.payload,
            "answer_key": task.answer_key, "reference_md": task.reference_md,
            "explanation_md": task.explanation_md, "hint_md": task.hint_md,
            "difficulty": task.difficulty.value, "basis": task.basis.value,
            "source_snapshot": task.source_snapshot,
        }

    def _topics(self, lesson: Lesson) -> tuple[list[dict[str, Any]], dict[UUID, int]]:
        topics: list[dict[str, Any]] = []
        index: dict[UUID, int] = {}
        for topic in self.session.scalars(select(LessonTopic).where(
            LessonTopic.lesson_id == lesson.id).order_by(LessonTopic.sort_order)
        ):
            node = self.session.get(ProgramNode, topic.program_node_id)
            path: list[str] = []
            parent = self.session.get(ProgramNode, node.parent_id) \
                if node is not None and node.parent_id else None
            while parent is not None:
                path.insert(0, parent.title)
                parent = self.session.get(ProgramNode, parent.parent_id) \
                    if parent.parent_id else None
            index[topic.program_node_id] = len(topics)
            topics.append({"title": node.title if node is not None
                           else topic.topic_title_snapshot, "path": path})
        return topics, index

    def lesson(self, lesson: Lesson, key: str) -> dict[str, Any]:
        topics, topic_index = self._topics(lesson)
        blocks: list[dict[str, Any]] = []
        for block in self.session.scalars(select(LessonBlock).where(
            LessonBlock.lesson_id == lesson.id).order_by(LessonBlock.sort_order)
        ):
            item: dict[str, Any] = {
                "kind": block.kind.value,
                "variant": block.variant.value if block.variant else None,
                "body_md": note_body(block.body_md) if block.kind == LessonBlockKind.NOTE
                else block.body_md,
                "origin": block.origin.value,
                "basis": block.basis.value if block.basis else None,
                "collapsed": block.collapsed,
                "topic": topic_index.get(block.bound_program_node_id)
                if block.bound_program_node_id else None,
                "refs": [self._ref(ref) for ref in self.session.scalars(
                    select(LessonSourceRef).where(LessonSourceRef.block_id == block.id))],
            }
            if block.kind == LessonBlockKind.MEDIA:
                item["media"] = self._media(block)
            if block.kind == LessonBlockKind.ACTIVITY:
                item["task"] = self._task(block.activity_id)
                if item["task"] is None:
                    continue
            blocks.append(item)
        meta = lesson.build_meta or {}
        return {
            "key": key,
            "title": lesson.title,
            "goal": lesson.goal,
            "status": lesson.status.value,
            "duration_minutes": lesson.duration_minutes,
            "build": {name: meta[name] for name in BUILD_KEYS if name in meta} or None,
            "topics": topics,
            "blocks": blocks,
        }

    def write(self, lessons: list[Lesson], target: Path) -> Path:
        records = [self.lesson(lesson, f"l{number}")
                   for number, lesson in enumerate(lessons, start=1)]
        project = self.session.get(Project, self.project_id)
        manifest = {
            "format": FORMAT,
            "version": FORMAT_VERSION,
            "app_version": APP_VERSION,
            "exported_at": utc_now().isoformat(),
            "project": {"name": project.name if project else ""},
            "lessons": len(records),
            "materials": list(self.materials.values()),
        }
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
            archive.writestr("lessons.json", json.dumps(records, ensure_ascii=False))
            for name, path in self.media.items():
                archive.write(path, name)
        return target

