"""search index: norm column instead of raw text, prefix index

Колонка `text` в индексе занимала место, но её никто не читал: текст фрагмента
берётся из `material_fragments`. На её место встаёт `norm` — те же слова без
морфологии (регистр приводит сам токенизатор, ё→е приходится делать руками,
`remove_diacritics 2` их не сводит). По ней идёт префиксный поиск: лемму для
огрызка построить нельзя, pymorphy3 достраивает «мил» до «мила».

`prefix = "2 3"` — короткие префиксы упираются в индекс, а не в скан диапазона
терминов; именно они самые частые, пока пользователь допечатывает слово.

Морфология не пересчитывается: `lemmas` переносятся как есть, `norm` строится
средствами SQLite. Поэтому миграция не тянет pymorphy3 и идёт быстро.

Revision ID: 20260905_0037
Revises: 20260904_0036
Create Date: 2026-09-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260905_0037"
down_revision: str | Sequence[str] | None = "20260904_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_DDL = (
    "CREATE VIRTUAL TABLE fragment_search USING fts5("
    "text, lemmas, fragment_id UNINDEXED, material_id UNINDEXED, "
    'tokenize = "unicode61 remove_diacritics 2")'
)

# rowid переносится явно: на него ссылается fragment_search_map.rowid, иначе
# удаление индекса материала перестало бы попадать в свои строки.
_FOLD_YO = "replace(replace({column}, 'ё', 'е'), 'Ё', 'Е')"


def _rebuild(new_ddl: str, target_column: str, expression: str) -> None:
    op.execute(new_ddl.replace("fragment_search", "fragment_search_new", 1))
    op.execute(
        f"INSERT INTO fragment_search_new(rowid, {target_column}, lemmas, "
        "fragment_id, material_id) "
        f"SELECT rowid, {expression}, lemmas, fragment_id, material_id FROM fragment_search"
    )
    op.execute("DROP TABLE fragment_search")
    op.execute("ALTER TABLE fragment_search_new RENAME TO fragment_search")


def upgrade() -> None:
    # Ленивый импорт как в 0007: версии сканируются до подъёма приложения.
    from app.bindings.search import FRAGMENT_SEARCH_DDL

    _rebuild(FRAGMENT_SEARCH_DDL, "norm", _FOLD_YO.format(column="text"))


def downgrade() -> None:
    # Обратно ё не возвращаем: при откате колонка снова становится нечитаемой.
    _rebuild(_OLD_DDL, "text", "norm")
