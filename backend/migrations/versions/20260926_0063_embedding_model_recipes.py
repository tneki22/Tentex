"""Шаблоны запроса и документа для известных embedding-моделей.

Профили создавались с `{text}` и mean pooling для любой модели. E5 без
`query:`/`passage:` и Qwen3-Embedding без инструкции в запросе и last-token
pooling ищут заметно хуже. Правятся только профили с нетронутыми шаблонами;
рецепты повторяют `app.retrieval.recipes` на момент миграции.

Revision ID: 20260926_0063
Revises: 20260925_0062
"""

import sqlalchemy as sa
from alembic import op

revision = "20260926_0063"
down_revision = "20260925_0062"
branch_labels = None
depends_on = None

_QWEN3_QUERY = (
    "Instruct: Given a question or topic, retrieve passages from study materials "
    "that answer it\nQuery:{text}"
)


def _recipe(model_id: str) -> tuple[str, str, str] | None:
    name = model_id.lower()
    if "qwen3-embedding" in name:
        return "last_token", _QWEN3_QUERY, "{text}"
    if "e5" in name.replace("/", "-").split("-") and "instruct" not in name:
        return "mean", "query: {text}", "passage: {text}"
    return None


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, model_id FROM embedding_profiles "
            "WHERE query_template = '{text}' AND document_template = '{text}'"
        )
    ).all()
    for profile_id, model_id in rows:
        recipe = _recipe(model_id)
        if recipe is None:
            continue
        pooling, query_template, document_template = recipe
        connection.execute(
            sa.text(
                "UPDATE embedding_profiles SET pooling = :pooling, "
                "query_template = :query_template, document_template = :document_template "
                "WHERE id = :id"
            ),
            {
                "pooling": pooling,
                "query_template": query_template,
                "document_template": document_template,
                "id": profile_id,
            },
        )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE embedding_profiles SET pooling = 'mean', "
            "query_template = '{text}', document_template = '{text}' "
            "WHERE query_template IN (:qwen3, 'query: {text}')"
        ),
        {"qwen3": _QWEN3_QUERY},
    )
