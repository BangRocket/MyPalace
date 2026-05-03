"""Exception hierarchy for the Palace client."""

from typing import Any


class PalaceError(Exception):
    """Base error. Raised on any non-2xx HTTP response other than 404."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.payload = payload

    def __repr__(self) -> str:
        return f"{type(self).__name__}(status_code={self.status_code}, message={self.message!r})"


class PalaceNotFound(PalaceError):
    """Raised on HTTP 404."""


class PalaceTransport(PalaceError):
    """Raised on network/timeout errors (no HTTP status reached)."""
