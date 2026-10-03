"""Check that current handovers no longer prescribe the superseded gate or wrong write key."""
from pathlib import Path
root = Path(__file__).resolve().parents[5]
forbidden = {
    'docs/handover/TESTING.md': ['routing decisions from the trusted turn', 'overlapping routing'],
    'docs/handover/mcp-only/README.md': ['identity, routing gate,'],
    'docs/handover/OWNER-INTEGRATION-MESSAGES.md': ['original turn context', 'encoded turn headers'],
    'docs/handover/CONTEXTFORGE.md': ['availability/CREATE/knowledge journeys require', 'base64 expansion'],
    'deploy/environments/README.md': ['has the placeholder an empty'],
    'docs/architecture/TARGET.md': [r'action\|target\|operation'],
}
failures = []
for name, phrases in forbidden.items():
    text = ' '.join((root / name).read_text().split())
    stale = [phrase for phrase in phrases if phrase in text]
    print(('FAIL' if stale else 'PASS') + ': ' + name)
    failures.extend(stale)
raise SystemExit(1 if failures else 0)
