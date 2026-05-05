"""Deprecated server-side mypalace-admin entry point.

Phase 11 moved the CLI into the ``mypalace-client`` package so operators
can run it from a separate machine without installing the full server.
This shim keeps the old ``mypalace-admin`` script (registered by the
server-side ``mypalace`` package) working for one minor release —
prints a one-time stderr deprecation notice and delegates to the
bundled client implementation when available.

Removal targeted for v0.12.0. Operators should switch to
``pip install 'mypalace-client[cli]'``.
"""

from __future__ import annotations

import sys

_DEPRECATION = (
    "DEPRECATION: the server-side `mypalace-admin` script will be removed "
    "in v0.12.0. Install the CLI from the client package instead:\n"
    "    pip install 'mypalace-client[cli]'\n"
)


def main(argv: list[str] | None = None) -> int:
    sys.stderr.write(_DEPRECATION)
    try:
        from mypalace_client.cli.admin import main as client_main
    except ImportError:
        sys.stderr.write(
            "ERROR: mypalace-client is not installed alongside mypalace. "
            "Run `pip install 'mypalace-client[cli]'` to keep using "
            "mypalace-admin.\n",
        )
        return 1
    return client_main(argv)


if __name__ == "__main__":
    sys.exit(main())
