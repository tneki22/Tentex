from datetime import UTC, date, datetime, time

from app.preparation.calendar import (
    budget_minutes,
    capacity_minutes,
    day_bounds,
    study_date,
    union_seconds,
)
from app.preparation.schemas import BusyWindow, PreparationConfig


def test_capacity_unions_sleep_and_overlapping_busy_windows() -> None:
    config = PreparationConfig(
        timezone="UTC",
        daily_minutes=1440,
        sleep_start=time(23),
        sleep_end=time(7),
        busy_windows=[
            BusyWindow(start=time(6), end=time(9)),
            BusyWindow(start=time(8), end=time(10)),
        ],
    )

    # Сон и занятость вместе закрывают 23:00–10:00: остаётся 13 часов.
    assert capacity_minutes(date(2026, 5, 12), config, None, None) == 13 * 60
    assert (
        union_seconds(
            [
                (datetime(2026, 5, 12, 6, tzinfo=UTC), datetime(2026, 5, 12, 9, tzinfo=UTC)),
                (datetime(2026, 5, 12, 8, tzinfo=UTC), datetime(2026, 5, 12, 10, tzinfo=UTC)),
            ]
        )
        == 4 * 3600
    )


def test_study_day_boundary_and_dst_use_local_civil_time() -> None:
    moscow = PreparationConfig(timezone="Europe/Moscow", day_boundary=time(4))
    assert study_date(datetime(2026, 5, 12, 0, 59, tzinfo=UTC), moscow) == date(2026, 5, 11)
    assert study_date(datetime(2026, 5, 12, 1, tzinfo=UTC), moscow) == date(2026, 5, 12)

    new_york = PreparationConfig(timezone="America/New_York", day_boundary=time(0))
    start, end = day_bounds(date(2026, 3, 8), new_york)
    assert (end - start).total_seconds() == 23 * 3600


def test_rest_and_exam_day_without_time_have_no_capacity() -> None:
    day = date(2026, 6, 1)
    config = PreparationConfig(
        timezone="UTC", daily_minutes=120, rest_dates=[day], exam_day_enabled=True
    )
    assert budget_minutes(day, config, None) == 0
    assert capacity_minutes(day, config, day, None) == 0
