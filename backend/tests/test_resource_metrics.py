"""Ресурсы: cgroup working set, честные пропуски, старые и повреждённые снимки."""

from datetime import UTC, datetime, timedelta

from app.system import resources
from app.system.schemas import ResourceServiceRead


def test_working_set_matches_docker_inactive_cache(tmp_path):
    (tmp_path / "memory.current").write_text("10000")
    (tmp_path / "memory.stat").write_text("inactive_file 4000\nactive_file 1000\n")
    (tmp_path / "cpu.stat").write_text("usage_usec 123456\nuser_usec 100\n")
    assert resources._counters(tmp_path) == (6000, 123456)


def test_v1_counters_and_cache_cannot_produce_negative_memory(tmp_path):
    for name in ("memory", "cpuacct"):
        (tmp_path / name).mkdir()
    (tmp_path / "memory/memory.usage_in_bytes").write_text("1000")
    (tmp_path / "memory/memory.stat").write_text("total_inactive_file 2000\n")
    (tmp_path / "cpuacct/cpuacct.usage").write_text("5000000")
    assert resources._counters(tmp_path) == (0, 5000)


def test_summary_excludes_stale_corrupt_and_mismatched_snapshots(tmp_path, monkeypatch):
    monkeypatch.setattr(resources.settings, "data_dir", tmp_path)
    directory = resources.settings.diagnostics_dir / "resources"
    directory.mkdir(parents=True)
    now = datetime.now(UTC)
    for service, stamp in (("api", now), ("worker", now - timedelta(minutes=1))):
        payload = ResourceServiceRead(
            service=service, sampled_at=stamp, memory_bytes=100, cpu_percent=200,
        )
        (directory / f"{service}.json").write_text(payload.model_dump_json())
    (directory / "retrieval-model.json").write_text("{broken")
    summary = resources.resource_summary()
    assert summary.memory_bytes == 100
    assert summary.cpu_percent == 200  # Одно ядро = 100%, верхнего потолка нет.
    assert summary.missing_services == ["worker", "retrieval-model"]
    (directory / "api.json").write_text(payload.model_dump_json())
    assert resources.resource_summary().memory_bytes is None


def test_atomic_samples_include_freshness_and_unknown_initial_cpu(tmp_path, monkeypatch):
    monkeypatch.setattr(resources.settings, "data_dir", tmp_path)
    resources.ResourceSampler("api")._publish(1234, None)
    summary = resources.resource_summary()
    assert summary.memory_bytes == 1234
    assert summary.cpu_percent is None
    assert len(summary.services) == 1
    resources.ResourceSampler("worker")._publish(4321, 12.34)
    resources.ResourceSampler("api")._publish(1234, 1.25)
    assert resources.resource_summary().cpu_percent == 13.59
