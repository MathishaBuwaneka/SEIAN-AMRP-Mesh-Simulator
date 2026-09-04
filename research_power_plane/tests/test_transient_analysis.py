from __future__ import annotations

import pytest

from seian_power_pipeline.transient_analysis import analyze_trace, sample_nearest, threshold_intervals


def test_sample_nearest_uses_closest_trace_sample():
    assert sample_nearest([0.0, 0.5, 1.0], [1.0, 2.0, 3.0], 0.6) == (0.5, 2.0)
    assert sample_nearest([0.0, 0.5, 1.0], [1.0, 2.0, 3.0], 2.0) == (1.0, 3.0)


def test_trace_summary_captures_values_before_and_after_switching():
    times = [index / 10 for index in range(31)]
    values = [0.39 if time < 1.0 or time >= 2.0 else 0.0 for time in times]

    result = analyze_trace("Vrms_N04", times, values, event_times_s=[1.0, 2.0])

    assert result["samples"] == 31
    assert result["events"][0]["before"] == pytest.approx(0.39)
    assert result["events"][0]["after"] == pytest.approx(0.0)
    assert result["events"][1]["before"] == pytest.approx(0.0)
    assert result["events"][1]["after"] == pytest.approx(0.39)
    assert result["interruptions"][0]["start_s"] == pytest.approx(1.0)
    assert result["interruptions"][0]["end_s"] == pytest.approx(2.0)


def test_threshold_intervals_merge_short_signal_chatter():
    times = [0.5, 1.0, 1.01, 1.02, 2.0]
    values = [1.0, 0.0, 1.0, 0.0, 1.0]
    intervals = threshold_intervals(
        times,
        values,
        threshold=0.5,
        ignore_before_s=0.5,
        minimum_duration_s=0.0,
        merge_gap_s=0.02,
    )
    assert intervals == [
        {
            "start_s": 1.0,
            "end_s": 2.0,
            "duration_s": 1.0,
            "ongoing_at_end": False,
            "threshold": 0.5,
        }
    ]


def test_ongoing_interval_is_marked_at_end_of_run():
    intervals = threshold_intervals(
        [0.5, 1.0, 1.5],
        [1.0, 0.0, 0.0],
        threshold=0.5,
        ignore_before_s=0.5,
    )
    assert intervals[0]["ongoing_at_end"] is True
    assert intervals[0]["duration_s"] == pytest.approx(0.5)
