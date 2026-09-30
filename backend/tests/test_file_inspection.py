"""Настоящий spawn осмотра сохраняет оглавление и ошибки без удержания PDF API."""

import asyncio

import pymupdf as fitz
import pytest

from app.materials import file_inspection
from app.process_pool import IdleProcessPool
from app.projects.errors import ProjectDomainError


@pytest.fixture
def inspection_pool(monkeypatch):
    pool = IdleProcessPool(idle_seconds=0.05)
    monkeypatch.setattr(file_inspection, "inspection_pool", pool)
    yield pool
    pool.close()


def test_pdf_counts_outline_and_pool_restart(tmp_path, inspection_pool):
    path = tmp_path / "book.pdf"
    with fitz.open() as document:
        document.new_page().insert_text((72, 72), "Native text")
        document.new_page()
        document.set_toc([[1, "Chapter", 1]])
        document.save(path)
    first = asyncio.run(file_inspection.inspect_upload(path))
    assert first["counts"][:3] == (2, 1, 4)
    assert first["outline"] == [{"level": 1, "title": "Chapter", "page": 1}]
    inspection_pool.close()
    inspection_pool.start()
    assert asyncio.run(file_inspection.inspect_upload(path)) == first


@pytest.mark.parametrize("encrypted", [False, True])
def test_domain_errors_cross_the_process_boundary(tmp_path, inspection_pool, encrypted):
    path = tmp_path / "source.pdf"
    if encrypted:
        with fitz.open() as document:
            document.new_page()
            document.save(path, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="secret")
    else:
        path.write_bytes(b"broken pdf")
    with pytest.raises(ProjectDomainError) as caught:
        asyncio.run(file_inspection.inspect_upload(path))
    assert caught.value.code == ("material_encrypted" if encrypted else "material_corrupt")
