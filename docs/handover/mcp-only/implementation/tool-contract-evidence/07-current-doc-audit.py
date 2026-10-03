"""Static reference audit for current documentation; dated evidence is intentionally excluded."""
from pathlib import Path

files = ('CLAUDE.md', 'README.md', 'services/mcp/README.md', 'docs/handover/AZURE.md',
         'docs/handover/TESTING.md', 'docs/handover/ONBOARDING.md',
         'docs/handover/OWNER-INTEGRATION-MESSAGES.md', 'docs/handover/CONTEXTFORGE.md')
failed = []
for name in files:
    text = Path(name).read_text()
    bad = [word for word in ('LIVEKIT.md', 'AGENT-INSTRUCTIONS', 'agent-instructions') if word in text]
    print(('FAIL' if bad else 'PASS') + ': ' + name + (': ' + ', '.join(bad) if bad else ''))
    failed.extend(bad)
raise SystemExit(bool(failed))
