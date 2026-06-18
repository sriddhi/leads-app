"""Unit tests for the admin / assignment / audit / time-tracking feature.

All tests are pure-logic and require no database or network. DB-touching behavior
is exercised through extracted pure helpers (choose_least_loaded,
compute_duration_seconds, aggregate_attorney_time) and through Pydantic schema
validation, so no async event loop or aiosqlite is needed.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.schemas.lead import AssignRequest, ReverseRequest
from app.services.assignment import choose_least_loaded
from app.services.identity import normalize_email
from app.services.ratelimit import is_allowed, reset
from app.services.timeline import aggregate_attorney_time, compute_duration_seconds
from app.services.workflow import (
    can_transition,
    format_lead_number,
    version_conflict,
)


# --- email normalization ------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("  Foo@Bar.com  ", "foo@bar.com"),
        ("USER@EXAMPLE.COM", "user@example.com"),
        ("already@lower.com", "already@lower.com"),
        ("", ""),
    ],
)
def test_normalize_email(raw, expected):
    assert normalize_email(raw) == expected


# --- duplicate detection logic (link & flag, never merge) ---------------------
def test_duplicates_match_on_normalized_email_only():
    # Two different names sharing the SAME normalized email are duplicates of each
    # other (flagged), regardless of name. Detection keys on normalized email.
    a = normalize_email("Family@Home.com")
    b = normalize_email("family@home.com ")
    assert a == b  # same normalized email -> would be flagged


def test_duplicates_different_email_not_matched():
    # A family member with a DIFFERENT email is a separate lead (not flagged via
    # email match) — they are never merged regardless.
    assert normalize_email("dad@home.com") != normalize_email("mom@home.com")


# --- pick_attorney capacity logic --------------------------------------------
def test_choose_least_loaded_picks_minimum():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    candidates = [(a, 5, 20), (b, 2, 20), (c, 8, 20)]
    assert choose_least_loaded(candidates) == b


def test_choose_least_loaded_skips_full():
    a, b = uuid.uuid4(), uuid.uuid4()
    # a is at cap, b is under cap -> b chosen even though raw count is higher.
    candidates = [(a, 20, 20), (b, 19, 20)]
    assert choose_least_loaded(candidates) == b


def test_choose_least_loaded_all_full_returns_none():
    a, b = uuid.uuid4(), uuid.uuid4()
    candidates = [(a, 20, 20), (b, 5, 5)]
    assert choose_least_loaded(candidates) is None


def test_choose_least_loaded_tiebreak_is_input_order():
    a, b = uuid.uuid4(), uuid.uuid4()
    # Equal load -> first in input order wins (round-robin friendly).
    assert choose_least_loaded([(a, 3, 20), (b, 3, 20)]) == a


def test_choose_least_loaded_empty():
    assert choose_least_loaded([]) is None


# --- state-period duration ----------------------------------------------------
def test_compute_duration_seconds_basic():
    start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(minutes=5, seconds=30)
    assert compute_duration_seconds(start, end) == 330


def test_compute_duration_seconds_never_negative():
    start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    end = start - timedelta(seconds=10)
    assert compute_duration_seconds(start, end) == 0


# --- attorney_time_report aggregation ----------------------------------------
def test_aggregate_attorney_time():
    now = datetime(2026, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
    att = uuid.uuid4()
    lead1, lead2 = uuid.uuid4(), uuid.uuid4()
    entered = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    periods = [
        # Closed ASSIGNED period that led to reached out (1 hour = 3600s).
        {
            "lead_id": lead1,
            "assignee_id": att,
            "state": "ASSIGNED",
            "entered_at": entered,
            "exited_at": entered + timedelta(hours=1),
            "duration_seconds": 3600,
            "led_to_reached_out": True,
        },
        # Open ASSIGNED period (entered 30 min ago -> 1800s live, +load).
        {
            "lead_id": lead2,
            "assignee_id": att,
            "state": "ASSIGNED",
            "entered_at": now - timedelta(minutes=30),
            "exited_at": None,
            "duration_seconds": None,
            "led_to_reached_out": False,
        },
    ]

    report = aggregate_attorney_time(periods, now)
    row = report[att]
    assert row["total_holding_seconds"] == 3600 + 1800
    assert row["cases_handled"] == 1
    assert row["avg_time_to_reached_out_seconds"] == 3600
    assert row["current_open_load"] == 1
    assert row["oldest_open_age_seconds"] == 1800


def test_aggregate_attorney_time_ignores_unassigned_periods():
    now = datetime(2026, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
    periods = [
        {
            "lead_id": uuid.uuid4(),
            "assignee_id": None,
            "state": "QUEUED",
            "entered_at": now - timedelta(hours=1),
            "exited_at": None,
            "duration_seconds": None,
        }
    ]
    assert aggregate_attorney_time(periods, now) == {}


# --- status state machine -----------------------------------------------------
def test_can_transition_valid():
    assert can_transition("PENDING", "REACHED_OUT") is True
    assert can_transition("REACHED_OUT", "PENDING") is True  # reversal


@pytest.mark.parametrize(
    "current,target",
    [
        ("PENDING", "PENDING"),
        ("REACHED_OUT", "REACHED_OUT"),
        ("PENDING", "NONSENSE"),
        ("UNKNOWN", "REACHED_OUT"),
    ],
)
def test_can_transition_invalid(current, target):
    assert can_transition(current, target) is False


# --- optimistic version conflict ---------------------------------------------
def test_version_conflict():
    assert version_conflict(1, 1) is False
    assert version_conflict(2, 1) is True
    assert version_conflict(1, 2) is True


# --- lead number formatting ---------------------------------------------------
def test_format_lead_number():
    assert format_lead_number(1) == "LEAD-000001"
    assert format_lead_number(123) == "LEAD-000123"
    assert format_lead_number(1234567) == "LEAD-1234567"


# --- request schema validation ------------------------------------------------
def test_assign_request_requires_version():
    assert AssignRequest(version=3).version == 3
    with pytest.raises(ValidationError):
        AssignRequest()


def test_reverse_request_requires_reason():
    ok = ReverseRequest(version=1, reason="Client called back")
    assert ok.reason == "Client called back"
    with pytest.raises(ValidationError):
        ReverseRequest(version=1, reason="   ")
    with pytest.raises(ValidationError):
        ReverseRequest(version=1)


# --- rate limiting ------------------------------------------------------------
def test_rate_limit_sliding_window():
    reset()
    ip = "203.0.113.7"
    base = 1000.0
    # First 10 within the window are allowed.
    for i in range(10):
        assert is_allowed(ip, limit=10, window_seconds=60, now=base + i) is True
    # 11th within the window is blocked.
    assert is_allowed(ip, limit=10, window_seconds=60, now=base + 10) is False
    # After the window slides past, allowed again.
    assert is_allowed(ip, limit=10, window_seconds=60, now=base + 61) is True


def test_rate_limit_isolates_ips():
    reset()
    base = 2000.0
    for i in range(10):
        is_allowed("a", limit=10, window_seconds=60, now=base + i)
    assert is_allowed("a", limit=10, window_seconds=60, now=base + 10) is False
    # A different IP has its own bucket.
    assert is_allowed("b", limit=10, window_seconds=60, now=base + 10) is True
