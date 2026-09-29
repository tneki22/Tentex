"""Экспорт выбранных уроков одним файлом: PDF, LaTeX, Markdown или `.tentex-lessons`.

Файл собирается во временном каталоге хранилища и отдаётся ответом; каталог
удаляет роутер после отправки. Несколько уроков — один документ в присланном
порядке (клиент присылает порядок программы).
"""

from __future__ import annotations

import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy.orm import Session

from app.config import settings
from app.lessons.export import ir
from app.lessons.export.collect import Collector, ExportOptions, SourceMode, load_lessons
from app.lessons.export.package import SUFFIX, PackageWriter
from app.lessons.export.pdf import build_pdf
from app.lessons.export.render_latex import LatexRenderer
from app.lessons.export.render_markdown import AssetNames, MarkdownRenderer
from app.lessons.service import _require_lessons_project
from app.models import Lesson
from app.projects.schemas import ApiModel

ExportFormat = Literal["pdf", "latex", "markdown", "tentex"]
_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


class LessonExportWrite(ApiModel):
    lesson_ids: list[UUID] = Field(min_length=1, max_length=300)
    format: ExportFormat
    # Кусок материала: текстом фрагментов, листами страниц или одной строкой-ссылкой.
    sources: SourceMode = "text"
    answers: bool = True


@dataclass(slots=True)
class ExportFile:
    path: Path
    filename: str
    media_type: str
    workdir: Path


def _file_stem(project_name: str, lessons: list[Lesson]) -> str:
    base = lessons[0].title if len(lessons) == 1 else f"{project_name} — уроки"
    cleaned = _UNSAFE.sub("_", base).strip(" ._") or "Уроки"
    return cleaned[:90]


def _bundle(workdir: Path, stem: str, text_name: str, text: str, assets: AssetNames,
            suffix: str, media_type: str) -> tuple[Path, str, str]:
    """Один текстовый файл; с картинками — ZIP с ним и папкой `images/`."""
    if not assets.names:
        target = workdir / f"export{suffix}"
        target.write_text(text, encoding="utf-8")
        return target, f"{stem}{suffix}", media_type
    target = workdir / "export.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(text_name, text)
        for path, name in assets.names.items():
            archive.write(path, name)
    return target, f"{stem}.zip", "application/zip"


def export_lessons(session: Session, project_id: UUID, command: LessonExportWrite) -> ExportFile:
    project = _require_lessons_project(session, project_id, writable=False)
    lessons = load_lessons(session, project_id, command.lesson_ids)
    workdir = settings.storage_dir / "tmp" / f"lesson-export-{uuid4().hex}"
    workdir.mkdir(parents=True)
    stem = _file_stem(project.name, lessons)
    try:
        if command.format == "tentex":
            target = PackageWriter(session, project_id, workdir).write(
                lessons, workdir / f"export{SUFFIX}")
            return ExportFile(target, f"{stem}{SUFFIX}", "application/zip", workdir)
        collector = Collector(session, project_id,
                              ExportOptions(sources=command.sources, answers=command.answers),
                              workdir)
        title = lessons[0].title if len(lessons) == 1 else project.name
        doc = ir.ExportDoc(title=title, project_name=project.name,
                           lessons=[collector.lesson(lesson) for lesson in lessons])
        if command.format == "pdf":
            return ExportFile(build_pdf(doc, workdir), f"{stem}.pdf", "application/pdf",
                              workdir)
        assets = AssetNames()
        if command.format == "latex":
            text = LatexRenderer(assets).document(doc)
            target, name, media_type = _bundle(workdir, stem, "lessons.tex", text, assets,
                                               ".tex", "application/x-tex")
        else:
            text = MarkdownRenderer(assets).document(doc)
            target, name, media_type = _bundle(workdir, stem, "lessons.md", text, assets,
                                               ".md", "text/markdown")
        return ExportFile(target, name, media_type, workdir)
    except BaseException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
