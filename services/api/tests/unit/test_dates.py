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


# Callers name dates too; the agent must not compute them (PO review). Today is Fri 25 Sep 2026.
@pytest.mark.parametrize(("expr", "day"), [
    ("October 5", date(2026, 10, 5)),
    ("5 October", date(2026, 10, 5)),
    ("5th oct", date(2026, 10, 5)),
    ("on the 5th of October", date(2026, 10, 5)),
    ("5/10", date(2026, 10, 5)),                    # day first, as callers in India say it
    ("05/10/2026", date(2026, 10, 5)),
    ("2026-10-05", date(2026, 10, 5)),
    ("5 tareekh", date(2026, 10, 5)),               # the 5th: next time it comes round
    ("30 tarikh", date(2026, 9, 30)),
    ("ಅಕ್ಟೋಬರ್ 5", date(2026, 10, 5)),
    ("अक्टूबर 5", date(2026, 10, 5)),
    ("5 अक्टूबर", date(2026, 10, 5)),
    ("20 September", date(2027, 9, 20)),            # already past this year: next year
])
def test_named_and_numeric_dates(day_parts, expr, day):
    got = when(expr, day_parts=day_parts)
    assert (got.date_from, got.date_to, got.resolved) == (day, day, True)


def test_named_date_keeps_the_day_part(day_parts):
    got = when("5th October evening", day_parts=day_parts)
    assert (got.date_from, got.day_part) == (date(2026, 10, 5), "EVENING")


@pytest.mark.parametrize("expr", ["31/02", "30 February", "45 tareekh"])
def test_impossible_dates_are_not_understood(day_parts, expr):
    assert when(expr, day_parts=day_parts).resolved is False


@pytest.mark.parametrize("utterance", [
    "Can I book with Dr Indu",          # a name, not Kannada 'today'
    "fever since monday",               # history, not the visit
    "had a headache last night",
])
def test_history_and_names_in_the_sentence_are_not_the_visit_date(day_parts, utterance):
    got = resolve_when(today=FRI, utterance=utterance, day_parts=day_parts)
    assert (got.date_from, got.date_to, got.day_part) == (FRI, date(2026, 10, 1), None)


def test_indu_still_means_today_when_given_as_the_time(day_parts):
    assert when("indu", day_parts=day_parts).date_to == FRI


def test_the_default_range_is_marked_as_not_stated(day_parts):
    assert resolve_when(today=FRI, utterance="any doctor", day_parts=day_parts).stated is False
    assert resolve_when(today=FRI, utterance="any doctor next week", day_parts=day_parts).stated is True
