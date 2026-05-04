"""KeyService — create, lookup, list, revoke API keys."""

from __future__ import annotations

import logging
import secrets
import string
from dataclasses import dataclass

import bcrypt
from sqlalchemy import select

from palace.auth.context import VALID_SCOPES, AuthContext
from palace.auth.tenant import is_valid_tenant_id
from palace.auth.usage import usage_tracker
from palace.database import async_session
from palace.models import ApiKey, utcnow

logger = logging.getLogger(__name__)

KEY_PREFIX_LITERAL = "pk_live_"
RANDOM_PART_LEN = 32
PREFIX_INDEX_LEN = 8  # first 8 chars of random part stored as key_prefix


@dataclass(frozen=True)
class CreatedKey:
    api_key: ApiKey
    plaintext: str


def _gen_random() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(RANDOM_PART_LEN))


def _split(plaintext: str) -> tuple[str, str] | None:
    """Return (prefix_index, random_part) or None if plaintext is malformed."""
    if not plaintext.startswith(KEY_PREFIX_LITERAL):
        return None
    random_part = plaintext[len(KEY_PREFIX_LITERAL):]
    if len(random_part) != RANDOM_PART_LEN:
        return None
    return random_part[:PREFIX_INDEX_LEN], random_part


def _hash(plaintext: str) -> str:
    return bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def _verify(plaintext: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def _validate_scopes(scopes: list[str]) -> frozenset[str]:
    bad = [s for s in scopes if s not in VALID_SCOPES]
    if bad:
        raise ValueError(f"invalid scopes: {bad}")
    if not scopes:
        raise ValueError("at least one scope required")
    return frozenset(scopes)


class KeyService:
    """Business logic for API keys."""

    async def create_key(
        self,
        label: str,
        scopes: list[str],
        tenant_id: str | None = None,
    ) -> CreatedKey:
        """Create a key bound to ``tenant_id``.

        ``tenant_id=None`` means cross-tenant admin (only admins should mint
        these). Validation of the tenant_id format happens in the route layer
        (which already raises 400); here we trust the caller has validated.
        """
        valid = _validate_scopes(scopes)
        if tenant_id is not None and not is_valid_tenant_id(tenant_id):
            raise ValueError(f"invalid tenant_id: {tenant_id!r}")

        plaintext = KEY_PREFIX_LITERAL + _gen_random()
        split = _split(plaintext)
        assert split is not None  # we just generated it
        prefix_index, _ = split

        key = ApiKey(
            key_prefix=prefix_index,
            key_hash=_hash(plaintext),
            label=label,
            tenant_id=tenant_id,
            scopes=sorted(valid),
        )
        async with async_session() as db:
            db.add(key)
            await db.commit()
            await db.refresh(key)
        return CreatedKey(api_key=key, plaintext=plaintext)

    async def lookup(self, plaintext: str) -> AuthContext | None:
        """Return AuthContext for a valid key, None otherwise.

        Constant-time-ish: we always run bcrypt at least once when the prefix
        matches, so 'key not found' and 'key found, hash wrong' have similar
        latency. (The first-pass prefix lookup is unavoidable; that's a
        timing channel for prefix existence only, not for full keys.)
        """
        split = _split(plaintext)
        if split is None:
            return None
        prefix_index, _ = split

        async with async_session() as db:
            result = await db.execute(
                select(ApiKey).where(ApiKey.key_prefix == prefix_index),
            )
            candidates = result.scalars().all()

        for key in candidates:
            if key.revoked_at is not None:
                continue
            if _verify(plaintext, key.key_hash):
                await self._maybe_bump_last_used(key.id)
                return AuthContext(
                    key_id=key.id,
                    label=key.label,
                    scopes=frozenset(key.scopes or []),
                    tenant_id=key.tenant_id,
                )
        return None

    async def _maybe_bump_last_used(self, key_id: str) -> None:
        if not usage_tracker.should_update(key_id):
            return
        async with async_session() as db:
            result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
            row = result.scalar_one_or_none()
            if row is None:
                return
            row.last_used_at = utcnow()
            await db.commit()

    async def list_keys(self, include_revoked: bool = False) -> list[ApiKey]:
        async with async_session() as db:
            stmt = select(ApiKey).order_by(ApiKey.created_at.desc())
            result = await db.execute(stmt)
            rows = list(result.scalars().all())
            if not include_revoked:
                rows = [r for r in rows if r.revoked_at is None]
            return rows

    async def revoke(self, key_id: str) -> bool:
        async with async_session() as db:
            result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
            row = result.scalar_one_or_none()
            if row is None:
                return False
            if row.revoked_at is not None:
                return True
            row.revoked_at = utcnow()
            await db.commit()
            return True

    async def bootstrap_if_needed(self, plaintext: str | None) -> bool:
        """Insert an admin key from env on first boot if none exist.

        Returns True iff a new key was inserted.
        """
        async with async_session() as db:
            result = await db.execute(
                select(ApiKey).where(ApiKey.revoked_at.is_(None)),
            )
            existing = list(result.scalars().all())
        has_admin = any("admin" in (k.scopes or []) for k in existing)

        if has_admin:
            return False
        if plaintext is None:
            logger.warning(
                "no admin keys configured; /v1/admin/* will be inaccessible. "
                "Set PALACE_BOOTSTRAP_ADMIN_KEY to mint one on next boot.",
            )
            return False

        split = _split(plaintext)
        if split is None:
            logger.error(
                "PALACE_BOOTSTRAP_ADMIN_KEY is malformed; expected "
                "%s<%d random chars>. Skipping bootstrap.",
                KEY_PREFIX_LITERAL, RANDOM_PART_LEN,
            )
            return False
        prefix_index, _ = split

        key = ApiKey(
            key_prefix=prefix_index,
            key_hash=_hash(plaintext),
            label="bootstrap-admin",
            # Bootstrap key is cross-tenant admin (tenant_id=None) so support
            # operators can manage any tenant from day one.
            tenant_id=None,
            scopes=["read", "write", "admin"],
        )
        async with async_session() as db:
            db.add(key)
            await db.commit()
        logger.info(
            "bootstrap admin key registered (label=bootstrap-admin, prefix=%s)",
            prefix_index,
        )
        return True


key_service = KeyService()
