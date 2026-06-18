"""Unit tests for pure backend logic (no DB / network needed).

These anchor the "unit tests" gate in CLAUDE.md §3. They cover security, schema validation,
file-upload validation, and the lead status state machine — including edge cases.
"""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.schemas.lead import LeadStatusUpdate
from app.services.storage import _validate_content_type

# --- security ---------------------------------------------------------------------------------

def test_password_hash_roundtrip():
    h = hash_password("attorney123")
    assert h != "attorney123"  # actually hashed
    assert verify_password("attorney123", h) is True
    assert verify_password("wrong", h) is False


def test_jwt_roundtrip_and_tamper():
    token = create_access_token(subject="attorney@company.com")
    assert decode_access_token(token) == "attorney@company.com"
    assert decode_access_token(token + "tampered") is None
    assert decode_access_token("not.a.jwt") is None


# --- status state machine ---------------------------------------------------------------------

def test_status_update_accepts_reached_out():
    assert LeadStatusUpdate(status="REACHED_OUT", version=1).status == "REACHED_OUT"


@pytest.mark.parametrize("bad", ["PENDING", "NONSENSE", "", "reached_out"])
def test_status_update_rejects_invalid(bad):
    with pytest.raises(ValidationError):
        LeadStatusUpdate(status=bad, version=1)


# --- file upload validation (edge cases) ------------------------------------------------------

@pytest.mark.parametrize(
    "content_type",
    [
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/pdf; charset=utf-8",  # parameters are stripped
    ],
)
def test_validate_content_type_accepts_allowed(content_type):
    assert _validate_content_type(content_type, "resume.pdf") in {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }


@pytest.mark.parametrize("content_type", ["text/plain", "image/png", "application/zip"])
def test_validate_content_type_rejects_disallowed(content_type):
    with pytest.raises(HTTPException) as exc:
        _validate_content_type(content_type, "resume.txt")
    assert exc.value.status_code == 400


def test_validate_content_type_falls_back_to_extension():
    # Missing content type -> guessed from filename; .pdf is allowed.
    assert _validate_content_type(None, "resume.pdf") == "application/pdf"
