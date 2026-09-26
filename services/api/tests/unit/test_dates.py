"""Relative dates in the facility timezone."""

from __future__ import annotations

from datetime import date

import pytest

from frontdesk_api.domain.dates import resolve_when

FRI = date(2026, 9, 25)


def when(expr=None, *, day_parts, **kw):
    return resolve_when(today=FRI, expression=expr, day_parts=day_parts, **kw)


@pytest.mark.parametrize(("expr", "day", "part"), [
    ("today", FRI, None),
    ("right now", FRI, None),
    ("tomorrow", date(2026, 9, 26), None),
    ("tomorrow evening", date(2026, 9, 26), "EVENING"),
    ("ನಾಳೆ ಸಂಜೆ", date(2026, 9, 26), "EVENING"),
    ("naale sanje", date(2026, 9, 26), "EVENING"),
    ("कल शाम", date(2026, 9, 26), "EVENING"),
    ("kal shaam", date(2026, 9, 26), "EVENING"),
    ("आज सुबह", FRI, "MORNING"),
    ("ಇವತ್ತು ಬೆಳಿಗ್ಗೆ", FRI, "MORNING"),
    ("ಮಧ್ಯಾಹ್ನ", FRI, "AFTERNOON"),
    ("day after tomorrow", date(2026, 9, 27), None),
    ("परसों", date(2026, 9, 27), None),
    ("monday", date(2026, 9, 28), None),
    ("friday", FRI, None),
    ("next friday", date(2026, 10, 2), None),
    ("next Tuesday", date(2026, 9, 29), None),
    ("ಮುಂದಿನ ಮಂಗಳವಾರ", date(2026, 9, 29), None),
    ("अगले मंगलवार", date(2026, 9, 29), None),
    ("thursday afternoon", date(2026, 10, 1), "AFTERNOON"),
])
def test_expressions(day_parts, expr, day, part):
    result = when(expr, day_parts=day_parts)
    assert result.resolved
    assert (result.date_from, result.date_to, result.day_part) == (day, day, part)


def test_week_ranges(day_parts):
    this = when("this week", day_parts=day_parts)
    assert (this.date_from, this.date_to) == (FRI, date(2026, 9, 27))
    nxt = when("next week", day_parts=day_parts)
    assert (nxt.date_from, nxt.date_to) == (date(2026, 9, 28), date(2026, 10, 4))


def test_explicit_dates_win(day_parts):
    result = when("tomorrow", day_parts=day_parts, date_from=date(2026, 10, 5))
    assert (result.date_from, result.date_to) == (date(2026, 10, 5), date(2026, 10, 5))


def test_explicit_day_part_wins(day_parts):
    assert when("tomorrow", day_parts=day_parts, day_part="MORNING").day_part == "MORNING"


def test_nothing_given_means_the_default_window(day_parts):
    result = when(day_parts=day_parts)
    assert result.resolved and (result.date_from, result.date_to) == (FRI, date(2026, 10, 1))


def test_unintelligible_expression_is_not_resolved(day_parts):
    assert when("whenever the moon is full", day_parts=day_parts).resolved is False


def test_utterance_is_used_when_no_when_is_given(day_parts):
    result = resolve_when(today=FRI, utterance="can I come tomorrow morning", day_parts=day_parts)
    assert (result.date_from, result.day_part) == (date(2026, 9, 26), "MORNING")
