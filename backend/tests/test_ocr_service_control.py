"""Классификация состояния GPU-сервиса «Учебник» после остановки.

PaddleX не обрабатывает SIGTERM: его C++-рантайм ловит сигнал сам, пишет
трассировку в журнал и выходит ненулевым кодом — даже когда остановку попросил
пользователь кнопкой «Остановить». `describe()` не должен путать это со
настоящим падением сервиса.
"""

import pytest

from app.ocr import docker_engine, service_control


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_control, "_expected_stop_container", None)
    service_control.reset_cache()


def _fake_self() -> dict:
    return {"Config": {"Labels": {"com.docker.compose.project": "tentex"}}}


def test_describe_reports_a_normal_stop_even_though_paddlex_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(docker_engine, "available", lambda: True)
    monkeypatch.setattr(docker_engine, "self_container", _fake_self)
    monkeypatch.setattr(
        docker_engine, "find_container", lambda labels: {"Id": "c1", "State": "exited"}
    )
    monkeypatch.setattr(docker_engine, "stop_container", lambda container_id, **_: None)

    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("код выхода не должен смотреться после нашей же остановки")

    monkeypatch.setattr(docker_engine, "inspect_container", fail_if_called)
    monkeypatch.setattr(docker_engine, "tail_logs", fail_if_called)

    stopped = service_control.stop()
    assert stopped.state == "stopped"

    status = service_control.describe()

    assert status.state == "stopped"
    assert status.summary == "Сервис остановлен"


def test_describe_still_reports_a_real_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_engine, "available", lambda: True)
    monkeypatch.setattr(docker_engine, "self_container", _fake_self)
    monkeypatch.setattr(
        docker_engine, "find_container", lambda labels: {"Id": "c2", "State": "exited"}
    )
    monkeypatch.setattr(
        docker_engine, "inspect_container", lambda container_id: {"State": {"ExitCode": 1}}
    )
    monkeypatch.setattr(docker_engine, "tail_logs", lambda container_id, lines: "boom")

    status = service_control.describe()

    assert status.state == "failed"
    assert status.detail == "boom"


def test_refresh_button_does_not_forget_that_we_stopped_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`reset_cache()` — то, что вызывает кнопка «Проверить ещё раз»."""
    monkeypatch.setattr(docker_engine, "available", lambda: True)
    monkeypatch.setattr(docker_engine, "self_container", _fake_self)
    monkeypatch.setattr(
        docker_engine, "find_container", lambda labels: {"Id": "c3", "State": "exited"}
    )
    monkeypatch.setattr(docker_engine, "stop_container", lambda container_id, **_: None)
    monkeypatch.setattr(
        docker_engine, "inspect_container", lambda container_id: {"State": {"ExitCode": 143}}
    )
    monkeypatch.setattr(docker_engine, "tail_logs", lambda container_id, lines: "SIGTERM trace")

    service_control.stop()
    service_control.reset_cache()

    status = service_control.describe()

    assert status.state == "stopped"


def test_start_forgets_the_previous_stop_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_engine, "available", lambda: True)
    monkeypatch.setattr(docker_engine, "self_container", _fake_self)
    monkeypatch.setattr(
        docker_engine, "find_container", lambda labels: {"Id": "c4", "State": "exited"}
    )
    monkeypatch.setattr(docker_engine, "stop_container", lambda container_id, **_: None)
    monkeypatch.setattr(
        docker_engine,
        "inspect_container",
        lambda container_id: {"Config": {"Env": []}, "State": {"ExitCode": 0}},
    )
    monkeypatch.setattr(docker_engine, "start_container", lambda container_id: None)

    service_control.stop()
    assert service_control._expected_stop_container == "c4"

    service_control.start({})

    assert service_control._expected_stop_container is None


def test_tail_logs_strips_ansi_color_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Иначе цветовые коды PaddleX рисуются в `<pre>` нечитаемыми прямоугольниками."""
    payload = b"\x1b[32mCreating model\x1b[0m\nFatalError: boom\n"
    header = bytes([1, 0, 0, 0]) + len(payload).to_bytes(4, "big")
    monkeypatch.setattr(docker_engine, "request", lambda *args, **kwargs: header + payload)

    text = docker_engine.tail_logs("c1", 30)

    assert "\x1b" not in text
    assert text == "Creating model\nFatalError: boom"
