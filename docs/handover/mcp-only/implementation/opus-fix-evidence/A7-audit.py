"""Executable structural acceptance check for explicitly requested dead-code deletion; not a behavior test."""
from pathlib import Path
import ast

root = Path(__file__).resolve().parents[5]
source = root / 'services/mcp/src/frontdesk_mcp'
checks = {
    'composition is synchronous': not any(isinstance(n, ast.AsyncFunctionDef) and n.name == '_compose'
                                         for n in ast.walk(ast.parse((source / 'availability.py').read_text()))),
    'unreachable profile raise removed': 'raise profile' not in (source / 'booking.py').read_text(),
    'unused per-path fixture injection removed': not any(
        s in (root / 'services/mcp/dev/frontdesk_stubs/knowledge.py').read_text()
        for s in ('fail_next_for', 'malformed_next_for')),
}
for name, ok in checks.items():
    print(('PASS' if ok else 'FAIL') + ': ' + name)
raise SystemExit(0 if all(checks.values()) else 1)
