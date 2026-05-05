"""Tests for the server-side mypalace-admin deprecation shim (phase 11).

The real CLI now lives in mypalace_client. The shim:
- prints a deprecation notice to stderr
- delegates to mypalace_client.cli.admin.main when installed
- prints an actionable error and exits 1 when not installed
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from mypalace.cli.admin import main as shim_main


class TestDeprecationShim:
    def test_prints_deprecation_to_stderr(self, capsys):
        with patch.dict(sys.modules, {"mypalace_client.cli.admin": MagicMock(main=lambda argv: 0)}):
            shim_main(["--help"])
        captured = capsys.readouterr()
        assert "DEPRECATION" in captured.err
        assert "mypalace-client[cli]" in captured.err

    def test_delegates_to_client_main_with_argv(self):
        delegated_args: list = []

        def fake_main(argv):
            delegated_args.append(argv)
            return 7

        with patch.dict(
            sys.modules,
            {"mypalace_client.cli.admin": MagicMock(main=fake_main)},
        ):
            rc = shim_main(["health"])
        assert rc == 7
        assert delegated_args == [["health"]]

    def test_missing_client_returns_error(self, capsys, monkeypatch):
        # Force the import inside the shim to raise ImportError.
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "mypalace_client.cli.admin":
                raise ImportError("not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        rc = shim_main(["health"])
        assert rc == 1
        captured = capsys.readouterr()
        assert "mypalace-client" in captured.err
        assert "[cli]" in captured.err
