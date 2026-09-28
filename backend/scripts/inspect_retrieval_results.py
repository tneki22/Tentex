"""Показать реальные места выдачи из БД без записи в материалы или индекс."""

from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from sqlalchemy import text

from app.db import SessionLocal
from app.retrieval.schemas import RetrievalScope, RetrievalSearchWrite, SearchStrategy
from app.retrieval.search import HybridRetriever


async def main() -> None:
    """Выполнить запрос по проекту и вывести пути и начало каждого найденного текста."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_id", type=UUID)
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--excerpt", type=int, default=400)
    parser.add_argument("--strategies", nargs="+", choices=list(SearchStrategy),
                        default=list(SearchStrategy))
    args = parser.parse_args()

    with SessionLocal() as session:
        session.execute(text("PRAGMA query_only = ON"))
        session.autoflush = False
        output = {}
        for strategy_name in args.strategies:
            strategy = SearchStrategy(strategy_name)
            result = await HybridRetriever().search(session, RetrievalSearchWrite(
                query=args.query,
                strategy=strategy,
                scope=RetrievalScope.PROJECT,
                project_id=args.project_id,
                limit=args.limit,
            ))
            output[strategy.value] = {
                "no_relevant_match": result.no_relevant_match,
                "degradation_reasons": result.degradation_reasons,
                "hits": [{
                    "rank": rank,
                    "material": hit.locator.material_name,
                    "section": hit.locator.block_title,
                    "page": hit.locator.page_from,
                    "block_id": str(hit.locator.block_id) if hit.locator.block_id else None,
                    "chunk_id": str(hit.locator.chunk_id),
                    "signals": hit.signals,
                    "excerpt": " ".join(hit.text.split())[:args.excerpt],
                } for rank, hit in enumerate(result.results, 1)],
            }
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
