"""drop stale CHECK constraints that still block parser_mode='cloud'

Revision ID: 20260904_0033
Revises: 20260904_0032
Create Date: 2026-09-04

Багфикс: разбор материала режимом «Облако» падал 500-й на любую попытку
запуска, включая обычный вызов из интерфейса (`Библиотека → Обработка →
Облако → «Запустить заново»`). Причина — `sqlite3.IntegrityError: CHECK
constraint failed`.

SQLite не поддерживает `ALTER TABLE ... DROP CONSTRAINT`, поэтому batch-режим
Alembic на каждой смене типа перестраивает таблицу целиком. На этой базе он
делает это не всегда чисто: реальная схема после миграции `20260904_0032`
несёт по два одноимённых по смыслу, но разных по значению CHECK-ограничения
на одном столбце:

- `materials.parser_mode` — старое `CONSTRAINT parser_mode CHECK (parser_mode
  IN ('fast', 'textbook'))` (без префикса `ck_`, самая ранняя форма ещё до
  введения `conv()`-нейминга) рядом с новым `ck_materials_parser_mode CHECK
  (parser_mode IN ('fast', 'cloud'))`;
- `background_jobs.parser_mode` — старое `ck_processing_tasks_task_parser_mode
  CHECK (parser_mode IN ('fast'))` рядом с новым
  `ck_background_jobs_task_parser_mode CHECK (parser_mode IN ('fast',
  'cloud'))`.

SQLite проверяет **все** CHECK-ограничения столбца разом, поэтому старое
`'fast'`-only ограничение рубит любую попытку записать `'cloud'`, даже
несмотря на то что новое, более широкое ограничение это значение разрешает.
Тот же класс дублирования уже описан в комментарии миграции `20260901_0031`
(«SQLite ненадёжно отражает имена CHECK-ограничений при пересборке таблицы в
batch-режиме Alembic») — там он был безвреден, потому что старое и новое
ограничения совпадали по множеству разрешённых значений. Здесь — впервые
разошлись, потому что `20260904_0032` не сужала множество, а расширяла его.

Ограничения `state`/`stage`/`kind` на `background_jobs` дублированы тем же
образом (`ck_processing_tasks_*` рядом с `ck_background_jobs_*`), но у них
множества значений совпадают — трогать их здесь незачем, это раздувало бы
диф без предмета.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy.schema import conv

revision: str = "20260904_0033"
down_revision: str | Sequence[str] | None = "20260904_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # `conv(...)` — обязательна: без неё `drop_constraint` прогоняет переданное
    # имя через тот же `ck_%(table_name)s_%(constraint_name)s`, что и создание
    # constraint'а, и ищет несуществующее `ck_background_jobs_ck_processing_
    # tasks_task_parser_mode` вместо реального имени на диске. `conv()` — тот
    # же приём, что уже используют явные имена в `app/models.py`.
    with op.batch_alter_table("materials") as batch:
        batch.drop_constraint(conv("parser_mode"), type_="check")
    with op.batch_alter_table("background_jobs") as batch:
        batch.drop_constraint(conv("ck_processing_tasks_task_parser_mode"), type_="check")


def downgrade() -> None:
    # Восстанавливает форму ограничений, а не историю данных: строки с
    # 'cloud', уже записанные под новым ограничением, под старое не пройдут
    # (как и при любом другом сужении CHECK) — тот же компромисс, что и в
    # downgrade() соседних миграций режима разбора.
    with op.batch_alter_table("background_jobs") as batch:
        batch.create_check_constraint(
            conv("ck_processing_tasks_task_parser_mode"), "parser_mode IN ('fast')"
        )
    with op.batch_alter_table("materials") as batch:
        batch.create_check_constraint(
            conv("parser_mode"), "parser_mode IN ('fast', 'textbook')"
        )
