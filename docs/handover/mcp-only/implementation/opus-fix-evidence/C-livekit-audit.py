"""Documentation acceptance audit; does not execute or validate a voice worker."""
from pathlib import Path

text = ' '.join(Path('docs/handover/LIVEKIT.md').read_text().split())
checks = {
    'C1 concrete local booking wrapper and per-intent transport': all(s in text for s in (
        'raw_schema=', 'X-Operation-Id', 'StreamableHttpTransport', 'manage_booking out of allowed_tools')),
    'C2 current-version write barrier inside wrapper': all(s in text for s in (
        'inside the local manage_booking wrapper', 'pending earlier turns', 'confirmed intent')),
    'C3 callback capture and shutdown finalization': all(s in text for s in (
        'note_callback', 'context.userdata', 'ctx.add_shutdown_callback', 'durable outbox')),
    'C4 force interrupt, transfer, duplicate policy and startup check': all(s in text for s in (
        'interrupt(force=True)', 'async def transfer', 'MCPToolOptions(on_duplicate="reject")', 'await read_tools.setup()')),
    'callback transition on booking board recheck': 'booking_dispatch must also capture CALLBACK_REQUIRED' in text,
    'current rollout-specific instructions': all(s in text for s in (
        '2026-10-03.2', 'PROVIDER_ID=<id> make agent-instructions', 'demo-hospital')),
}
for name, passed in checks.items():
    print(('PASS' if passed else 'FAIL') + ': ' + name)
raise SystemExit(0 if all(checks.values()) else 1)
