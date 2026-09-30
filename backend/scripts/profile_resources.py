"""Read-only замер HTTP-задержек и стабильности выдачи для ресурсного аудита.

Пример: python backend/scripts/profile_resources.py --query "нормальная форма"
Метрики Docker снимайте отдельно: docker stats --no-stream.
"""

import argparse
import hashlib
import json
import statistics
import time
import urllib.request
from pathlib import Path

POLL_PATH = "/api/background-jobs?active_only=true&pending_review=true&failed_only=true"
READ_PATHS = ("/api/materials", "/api/projects", POLL_PATH, "/api/system/status")


def measure(url: str, *, payload: dict | None, repeats: int) -> dict:
    """Первая задержка отдельно от медианы прогретых повторов; личные тексты не выводятся."""
    samples, fingerprints = [], []
    for _ in range(repeats + 1):
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"},
        )
        started = time.perf_counter()
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.load(response)
        samples.append(round((time.perf_counter() - started) * 1000, 1))
        if isinstance(result, dict) and "results" in result:
            locators = [hit["locator"] for hit in result["results"]]
            digest = hashlib.sha256(json.dumps(locators, sort_keys=True).encode()).hexdigest()
            fingerprints.append(digest)
    return {
        "first_ms": samples[0], "warm_median_ms": statistics.median(samples[1:]),
        "samples_ms": samples, "ranking_fingerprints": fingerprints,
    }


def main() -> None:
    """Поиск выполняется только по явным --query, используя настроенный backend embeddings."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--query", action="append", default=[])
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats должен быть положительным")
    base = args.api.rstrip("/")
    report = {path: measure(base + path, payload=None, repeats=args.repeats) for path in READ_PATHS}
    for query in args.query:
        report[query] = measure(
            base + "/api/retrieval/search",
            payload={"query": query, "scope": "library", "strategy": "hybrid", "limit": 5},
            repeats=args.repeats,
        )
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)


if __name__ == "__main__":
    main()
