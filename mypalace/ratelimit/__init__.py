"""Per-user rate limiting (phase 4 slice 4).

Sliding-window counters in Redis, scoped to (tenant_id, key_id, user_id).
The middleware wraps every authenticated request after AuthMiddleware
has populated request.state.auth. Keys with the ``unlimited`` scope
bypass the check.
"""

from mypalace.ratelimit.limiter import RateLimiter, rate_limiter

__all__ = ["RateLimiter", "rate_limiter"]
