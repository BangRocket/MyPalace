"""Route → required-scope mapping. First match wins."""

from __future__ import annotations

import fnmatch

# (method, path-glob, required-scope)
# Order matters: most specific first. `*` matches any single method.
SCOPE_RULES: list[tuple[str, str, str]] = [
    ("*",      "/v1/admin/*",              "admin"),
    ("*",      "/v1/admin",                "admin"),
    ("*",      "/v1/maintenance/*",        "admin"),
    ("*",      "/v1/maintenance",          "admin"),
    ("POST",   "/v1/memories/search",      "read"),
    ("POST",   "/v1/memories/list",        "read"),
    ("POST",   "/v1/episodes/search",      "read"),
    ("POST",   "/v1/intentions/check",     "read"),
    ("POST",   "/v1/intentions/format",    "read"),
    ("POST",   "/v1/context",              "read"),
    ("POST",   "/v1/context/*",            "read"),
    ("GET",    "/v1/*",                    "read"),
    ("GET",    "/v1/*/*",                  "read"),
    ("GET",    "/v1/*/*/*",                "read"),
    ("*",      "/v1/*",                    "write"),
    ("*",      "/v1/*/*",                  "write"),
    ("*",      "/v1/*/*/*",                "write"),
]

PUBLIC_PATHS: frozenset[str] = frozenset({
    "/health",
    "/health/deep",  # phase 8 slice 1 — k8s readiness probes need unauthenticated access
    "/live",         # phase 9 slice 2 — k8s livenessProbe
    "/ready",        # phase 9 slice 2 — k8s readinessProbe
    "/metrics",      # phase 4 slice 2 — k8s scrapers need unauthenticated access
    "/docs",
    "/redoc",
    "/openapi.json",
    "/docs/oauth2-redirect",
})


def is_public(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    # FastAPI serves /docs assets like /docs/swagger-ui-bundle.js
    return path.startswith("/docs/") or path.startswith("/redoc/")


def required_scope(method: str, path: str) -> str:
    """Return the scope required for a (method, path). Defaults to 'write'
    if no rule matches — defensive: new routes require explicit allowlisting
    to be readable by 'read' keys."""
    method = method.upper()
    for rule_method, rule_path, scope in SCOPE_RULES:
        if rule_method != "*" and rule_method != method:
            continue
        if fnmatch.fnmatchcase(path, rule_path):
            return scope
    return "write"
