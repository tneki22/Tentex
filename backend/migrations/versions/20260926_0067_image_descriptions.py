"""Явное состояние изображений и задача описания готового материала.

`material_fragments.visual` хранит роль, обработку, проверку и описание
изображения — копию `MaterialPage.elements[i]["image"]`. Поиск «без описания»
раньше угадывал это по префиксу `[Изображение]` и пропускал короткие облачные
подписи; теперь старые изображения один раз получают явные оси: заглушка —
`unprocessed`, облачная подпись прошлых версий — `legacy` с проверкой,
распознанный текст — `text_only`, ручная правка — `manual`.

Новый вид задачи `image_descriptions` и происхождение ревизии с тем же именем
расширяют CHECK-ограничения перечислений.

Revision ID: 20260926_0067
Revises: 20260926_0066
"""

import sqlalchemy as sa
from alembic import op

revision = "20260926_0067"
down_revision = "20260926_0066"
branch_labels = None
depends_on = None

OLD_JOB_KINDS = (
    "parse",
    "typst_compile",
    "ai_grouping",
    "ai_import_repair",
    "ai_preparation",
    "ai_cleanup",
    "link_answers",
    "ai_answer_sections",
    "ai_program_build",
    "coverage_research",
    "retrieval_index",
    "retrieval_model_install",
    "retrieval_exhaustive",
    "backup_create",
    "project_export",
    "project_import",
    "storage_verify",
    "storage_cleanup",
)
NEW_JOB_KINDS = (*OLD_JOB_KINDS, "image_descriptions")

OLD_ORIGINS = ("imported", "parse", "manual_edit", "ai_cleanup", "source_refresh", "restore")
NEW_ORIGINS = (*OLD_ORIGINS, "image_descriptions")

# Состояние старых изображений одним UPDATE: без импорта кода приложения,
# который со временем меняется, а миграция должна остаться воспроизводимой.
LEGACY_VISUAL = """
UPDATE material_fragments
SET visual = json_object(
    'role', 'unknown',
    'processing', CASE
        WHEN recognition_source = 'manual' THEN 'text_only'
        WHEN trim(text) = '' OR (trim(text) LIKE '[Изображение]%' AND length(trim(text)) <= 40)
            THEN 'unprocessed'
        WHEN recognition_source = 'vl' THEN 'legacy'
        ELSE 'text_only'
    END,
    'review', CASE
        WHEN recognition_source = 'manual' THEN 'manual'
        WHEN recognition_source = 'vl'
            AND NOT (trim(text) LIKE '[Изображение]%' AND length(trim(text)) <= 40)
            THEN 'needs_review'
        ELSE 'unreviewed'
    END,
    'reasons', json(CASE WHEN asset_path IS NULL THEN '["asset_missing"]' ELSE '[]' END),
    'signals', json('[]'),
    'detection', 'embedded',
    'crop_hash', NULL,
    'pixel_size', NULL,
    'caption', NULL,
    'description', NULL,
    'provenance', NULL
)
WHERE element_kind = 'image' AND visual IS NULL
"""


def _replace_check(table: str, column: str, enum_name: str, values: tuple[str, ...]) -> None:
    """Пересоздать CHECK перечисления: старое ограничение ищется по тексту, как в 0061."""
    existing = [
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_check_constraints(table)
        if constraint["name"] and f"{column} IN" in (constraint["sqltext"] or "")
    ]
    with op.batch_alter_table(table) as batch:
        for stale in existing:
            batch.drop_constraint(op.f(stale), type_="check")
        batch.alter_column(
            column,
            type_=sa.Enum(*values, name=enum_name, native_enum=False, create_constraint=False),
            existing_nullable=False,
        )
        batch.create_check_constraint(
            op.f(f"ck_{table}_{enum_name}"), sa.column(column).in_(values)
        )


def upgrade() -> None:
    op.add_column("material_fragments", sa.Column("visual", sa.JSON(), nullable=True))
    op.execute(sa.text(LEGACY_VISUAL))
    _replace_check("background_jobs", "kind", "background_job_kind", NEW_JOB_KINDS)
    _replace_check("material_revisions", "origin", "material_revision_origin", NEW_ORIGINS)


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM background_jobs WHERE kind = 'image_descriptions'"))
    _replace_check("background_jobs", "kind", "background_job_kind", OLD_JOB_KINDS)
    # Ревизия с описаниями остаётся в истории как ручная правка: её страницы и
    # фрагменты — полноценная версия материала, терять их при откате нельзя.
    op.execute(
        sa.text(
            "UPDATE material_revisions SET origin = 'manual_edit' "
            "WHERE origin = 'image_descriptions'"
        )
    )
    _replace_check("material_revisions", "origin", "material_revision_origin", OLD_ORIGINS)
    with op.batch_alter_table("material_fragments") as batch:
        batch.drop_column("visual")
