"""Root pytest conftest.

Fixes a namespace-package shadow caused by the palace_client subpackage
layout. The repo has two editable-installed packages:

    palace          -> /Volumes/Storage/Code/Palace/palace
    palace_client   -> /Volumes/Storage/Code/Palace/palace_client/palace_client

Pytest prepends the project root to sys.path. Python's PathFinder then
discovers the OUTER directory `palace_client/` (which has no __init__.py)
as a PEP 420 namespace package and resolves `import palace_client` to
that empty shadow rather than to the inner installed package. The
editable-install meta-path finders are appended (not prepended) to
sys.meta_path, so PathFinder always wins.

Symptom: `from palace_client import PalaceClient` raises ImportError
because the namespace shadow has no PalaceClient attribute.

Fix: move the editable-install finders ahead of PathFinder so the
installed packages resolve before any namespace shadow on sys.path.
This only runs in pytest contexts (conftest is pytest-only); it does
not affect production imports.
"""

from __future__ import annotations

import sys
from importlib.machinery import PathFinder


def _prioritize_editable_finders() -> None:
    editable = [
        f
        for f in sys.meta_path
        if isinstance(f, type) and f.__name__ == "_EditableFinder"
    ]
    if not editable:
        return
    for f in editable:
        sys.meta_path.remove(f)
    try:
        idx = sys.meta_path.index(PathFinder)
    except ValueError:
        idx = len(sys.meta_path)
    for f in reversed(editable):
        sys.meta_path.insert(idx, f)


_prioritize_editable_finders()
