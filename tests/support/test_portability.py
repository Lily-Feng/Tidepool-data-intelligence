"""Portability rules, enforced on every PR:

1. Only support/adapters/<cloud>/ may import that cloud's SDKs.
2. support/ports and support/core never import adapters.
"""

import ast
from pathlib import Path

import pytest

SUPPORT = Path(__file__).resolve().parents[2] / "support"
CLOUD_SDKS = {
    "gcp": ("google",),
    "aws": ("boto3", "botocore", "aioboto3"),
    "azure": ("azure",),
}
PY_FILES = sorted(SUPPORT.rglob("*.py"))


def imports(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


@pytest.mark.parametrize("path", PY_FILES, ids=lambda p: str(p.relative_to(SUPPORT)))
def test_cloud_sdks_only_in_their_adapter(path):
    rel = path.relative_to(SUPPORT).parts
    for cloud, roots in CLOUD_SDKS.items():
        if rel[:2] == ("adapters", cloud):
            continue
        bad = sorted(n for n in imports(path) if n.split(".")[0] in roots)
        assert not bad, f"{'/'.join(rel)} imports {bad}; move it to support/adapters/{cloud}/"


@pytest.mark.parametrize("path", [p for p in PY_FILES
                                  if p.relative_to(SUPPORT).parts[0] in ("ports", "core")],
                         ids=lambda p: str(p.relative_to(SUPPORT)))
def test_ports_and_core_do_not_import_adapters(path):
    bad = sorted(n for n in imports(path) if n.startswith("support.adapters"))
    assert not bad, f"{path.relative_to(SUPPORT)} imports {bad}"
