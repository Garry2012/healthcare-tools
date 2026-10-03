"""Static checks for approved contract-only ownership and current planning docs."""
from pathlib import Path

checks = {
    'docs/DECISIONS.md': ('MCP publishes only the tool contract', 'LIVEKIT.md'),
    'docs/handover/mcp-only/PLAN.md': ('Tool calls and owner reads', 'LIVEKIT.md'),
    'docs/handover/mcp-only/TARGET-STATE.md': ('Tool contract boundary', 'explicit instructions'),
    'docs/handover/mcp-only/README.md': ('Current integration contract', 'say someone from the hospital'),
    'docs/handover/mcp-only/implementation/OPEN-DEPENDENCIES.md': ('Tool-contract integration', 'Implement LIVEKIT.md'),
}
passed = []
for name, (required, removed) in checks.items():
    text = Path(name).read_text()
    ok = required in text and removed not in text
    print(('PASS' if ok else 'FAIL') + ': ' + name)
    passed.append(ok)
raise SystemExit(0 if all(passed) else 1)
