"""Log lines identify the deployment and the call, and never carry the customer."""

from __future__ import annotations

import json
import logging

from frontdesk_api.logging import JsonFormatter, call_id_var


def test_every_line_names_the_provider_and_the_call():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "booking_created", None, None)
    record.fields = {"bookingId": "bkg_1"}
    token = call_id_var.set("call-42")
    try:
        line = json.loads(JsonFormatter("demo-hospital").format(record))
    finally:
        call_id_var.reset(token)
    assert line["provider"] == "demo-hospital" and line["callId"] == "call-42"
    assert line["msg"] == "booking_created" and line["bookingId"] == "bkg_1"
