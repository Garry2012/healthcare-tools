"""Red flags are the first line of safety: the words callers actually use must transfer to
emergency, and ordinary complaints must not. Cases from real-sounding caller wording (PO review)."""

from __future__ import annotations

import pytest

from frontdesk_api.domain.resolver import resolve


@pytest.mark.parametrize(("utterance", "fields"), [
    ("chest pain", {}),
    ("my chest is paining badly", {}),
    ("seene me dard ho raha hai", {}),                    # "me" for "mein"
    ("seene mein dard", {"need_text": "seene me dard"}),
    ("papa is not breathing properly", {}),
    ("saans nahi aa rahi", {}),
    ("she is pregnant and bleeding", {}),
    ("बच्चे को तेज़ बुखार और झटके", {}),                     # child, high fever and convulsions
    ("bacche ko jhatke aa rahe hain", {}),
    ("he collapsed and is unconscious", {}),
    ("ಎದೆ ನೋವು ಇದೆ", {}),
    ("no chest pain but", {}),                            # OPEN-QUESTIONS P4: the safe direction
])
def test_emergency_wording_transfers(directory, utterance, fields):
    assert resolve(utterance=utterance, directory=directory, **fields).action == "TRANSFER_EMERGENCY"


@pytest.mark.parametrize(("utterance", "fields"), [
    ("knee pain since a week", {"need_text": "knee pain"}),
    ("I want to collect my chest x-ray report", {}),
    ("my child has fever", {"need_text": "fever"}),
    ("breathing exercises class timing", {}),
    ("pregnancy checkup", {"category": "pregnancy doctor"}),
    ("Dr Garima tomorrow evening", {"resource_name": "Dr Garima"}),
])
def test_ordinary_requests_do_not_transfer(directory, utterance, fields):
    assert resolve(utterance=utterance, directory=directory, **fields).action != "TRANSFER_EMERGENCY"
