"""mypalace-admin — operator CLI for common MyPalace operations.

Exposed as the `mypalace-admin` console_script. Subcommands wrap the
HTTP admin surface so operators don't have to memorize curl
incantations. Auth via env var ``MYPALACE_ADMIN_KEY`` or ``--admin-key``;
target URL via ``MYPALACE_URL`` or ``--url`` (default
http://localhost:8000).

Output is human-readable by default. ``--json`` swaps to raw JSON for
scripts and ``jq`` pipelines.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

DEFAULT_URL = "http://localhost:8000"
ENV_URL = "MYPALACE_URL"
ENV_KEY = "MYPALACE_ADMIN_KEY"


def _client(args: argparse.Namespace) -> httpx.Client:
    base_url = (args.url or os.environ.get(ENV_URL) or DEFAULT_URL).rstrip("/")
    api_key = args.admin_key or os.environ.get(ENV_KEY)
    headers = {"X-Palace-Key": api_key} if api_key else {}
    return httpx.Client(base_url=base_url, headers=headers, timeout=30.0)


def _emit(args: argparse.Namespace, data: Any, *, table: list[list[str]] | None = None) -> None:
    """JSON in --json mode, otherwise the pretty table when provided."""
    if args.json or table is None:
        print(json.dumps(data, indent=2, default=str))
        return
    if not table:
        print("(no rows)")
        return
    widths = [max(len(row[i]) for row in table) for i in range(len(table[0]))]
    for i, row in enumerate(table):
        print("  ".join(cell.ljust(widths[j]) for j, cell in enumerate(row)))
        if i == 0:
            print("  ".join("-" * w for w in widths))


def _check(resp: httpx.Response) -> dict:
    """Raise + print on non-2xx; return parsed JSON otherwise."""
    if resp.status_code >= 400:
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text}
        sys.stderr.write(
            f"HTTP {resp.status_code}: {json.dumps(body, default=str)}\n",
        )
        sys.exit(1)
    return resp.json()


# ---------------------------------------------------------------------------
# subcommands
# ---------------------------------------------------------------------------

def cmd_health(args: argparse.Namespace) -> int:
    with _client(args) as c:
        r = c.get("/health/deep")
    is_json = r.headers.get("content-type", "").startswith("application/json")
    body = r.json() if is_json else {"raw": r.text}
    if args.json:
        print(json.dumps(body, indent=2, default=str))
    else:
        status = body.get("status", "?")
        print(f"status: {status}")
        for b in body.get("backends", []):
            mark = "✓" if b["ok"] else "✗"
            cfg = "" if b.get("configured", True) else " (not configured)"
            print(f"  {mark} {b['name']:10s}  {b['elapsed_ms']:>5d}ms  {b['detail']}{cfg}")
    return 0 if r.status_code < 400 else 2


def cmd_keys_list(args: argparse.Namespace) -> int:
    with _client(args) as c:
        params = {}
        if args.include_revoked:
            params["include_revoked"] = "true"
        body = _check(c.get("/v1/admin/keys", params=params))
    rows = body.get("data", []) or []
    table = [["KEY_ID", "PREFIX", "LABEL", "TENANT", "SCOPES", "CREATED", "REVOKED"]]
    for k in rows:
        table.append([
            (k.get("key_id") or "")[:36],
            k.get("key_prefix") or "",
            k.get("label") or "",
            k.get("tenant_id") or "(cross)",
            ",".join(k.get("scopes") or []),
            (k.get("created_at") or "")[:19],
            "yes" if k.get("revoked_at") else "",
        ])
    _emit(args, body, table=table)
    return 0


def cmd_keys_mint(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {
        "label": args.label,
        "scopes": [s.strip() for s in args.scopes.split(",") if s.strip()],
    }
    if args.cross_tenant:
        payload["cross_tenant"] = True
    elif args.tenant_id:
        payload["tenant_id"] = args.tenant_id
    with _client(args) as c:
        body = _check(c.post("/v1/admin/keys", json=payload))
    data = body.get("data", {})
    if args.json:
        print(json.dumps(body, indent=2, default=str))
    else:
        print(f"key_id:        {data.get('key_id')}")
        print(f"plaintext_key: {data.get('plaintext_key')}")
        print(f"label:         {data.get('label')}")
        print(f"scopes:        {','.join(data.get('scopes') or [])}")
        print(f"tenant_id:     {data.get('tenant_id') or '(cross)'}")
        print()
        print("⚠  The plaintext_key is shown ONCE — save it now.")
    return 0


def cmd_keys_revoke(args: argparse.Namespace) -> int:
    with _client(args) as c:
        body = _check(c.delete(f"/v1/admin/keys/{args.key_id}"))
    if args.json:
        print(json.dumps(body, indent=2, default=str))
    else:
        print(f"revoked: {args.key_id}")
    return 0


def cmd_tenants_list(args: argparse.Namespace) -> int:
    with _client(args) as c:
        body = _check(c.get("/v1/admin/tenants"))
    rows = body.get("data", []) or []
    table = [["ID", "LABEL", "CREATED"]]
    for t in rows:
        table.append([
            t.get("id") or "",
            t.get("label") or "",
            (t.get("created_at") or "")[:19],
        ])
    _emit(args, body, table=table)
    return 0


def cmd_tenants_create(args: argparse.Namespace) -> int:
    with _client(args) as c:
        body = _check(c.post("/v1/admin/tenants", json={
            "id": args.id, "label": args.label,
        }))
    if args.json:
        print(json.dumps(body, indent=2, default=str))
    else:
        d = body.get("data", {})
        print(f"created tenant: {d.get('id')}  ({d.get('label')})")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    with _client(args) as c:
        body = _check(c.get("/v1/admin/stats", params={"tenant_id": args.tenant_id}))
    if args.json:
        print(json.dumps(body, indent=2, default=str))
        return 0
    data = body.get("data", {})
    if "tenants" in data:  # ALL mode
        for t in data["tenants"]:
            _print_tenant_stats(t)
            print()
    else:
        _print_tenant_stats(data)
    return 0


def _print_tenant_stats(t: dict) -> None:
    print(f"=== {t.get('tenant_id')} ===")
    rc = t.get("row_counts", {})
    print(
        f"  rows: memories={rc.get('memories', 0)} sessions={rc.get('sessions', 0)} "
        f"episodes={rc.get('episodes', 0)} arcs={rc.get('narrative_arcs', 0)} "
        f"intentions={rc.get('intentions', 0)}",
    )
    a = t.get("activity_7d", {})
    print(
        f"  7d activity: created={a.get('memories_created', 0)} "
        f"accessed={a.get('memories_accessed', 0)} "
        f"reflected={a.get('episodes_reflected', 0)} "
        f"intentions_fired={a.get('intentions_fired', 0)}",
    )
    fsrs = t.get("fsrs_health", {})
    print(
        f"  FSRS: tracked={fsrs.get('tracked_memories', 0)} "
        f"key={fsrs.get('key_memories', 0)} "
        f"mean_stability={fsrs.get('mean_stability', 0.0)} "
        f"mean_retrieval={fsrs.get('mean_retrieval_strength', 0.0)}",
    )
    top = t.get("top_users_by_access_7d", []) or []
    if top:
        print("  top users (7d):")
        for u in top:
            print(f"    {u.get('user_id', '?'):20s}  {u.get('access_count', 0)}")


def cmd_audit(args: argparse.Namespace) -> int:
    params: dict[str, str] = {"limit": str(args.limit)}
    if args.since:
        params["since"] = args.since
    if args.key_id:
        params["key_id"] = args.key_id
    if args.path_prefix:
        params["path_prefix"] = args.path_prefix
    with _client(args) as c:
        body = _check(c.get("/v1/admin/audit", params=params))
    rows = body.get("data", []) or []
    table = [["WHEN", "STATUS", "MS", "METHOD", "PATH", "TENANT", "KEY_ID"]]
    for r in rows:
        table.append([
            (r.get("created_at") or "")[:19],
            r.get("status_class") or "",
            str(r.get("response_ms") or 0),
            r.get("method") or "",
            r.get("path") or "",
            r.get("tenant_id") or "",
            (r.get("key_id") or "")[:8],
        ])
    _emit(args, body, table=table)
    return 0


def cmd_reembed(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {
        "tenant_id": args.tenant_id,
        "provider": args.provider,
        "model": args.model,
        "batch_size": args.batch_size,
    }
    if args.token:
        payload["token"] = args.token
    with _client(args) as c:
        body = _check(c.post("/v1/admin/reembed", json=payload))
    data = body.get("data", {})
    if args.json:
        print(json.dumps(body, indent=2, default=str))
    else:
        print(f"reembed job enqueued: job_id={data.get('job_id')}")
        print(f"  poll: mypalace-admin job {data.get('job_id')}")
    return 0


def cmd_job(args: argparse.Namespace) -> int:
    with _client(args) as c:
        r = c.get(f"/v1/jobs/{args.job_id}")
    if r.status_code == 404:
        sys.stderr.write(f"job not found: {args.job_id}\n")
        return 1
    body = _check(r)
    data = body.get("data", {})
    if args.json:
        print(json.dumps(body, indent=2, default=str))
    else:
        print(f"id:           {data.get('id')}")
        print(f"kind:         {data.get('kind')}")
        print(f"status:       {data.get('status')}")
        print(f"created_at:   {data.get('created_at')}")
        print(f"completed_at: {data.get('completed_at')}")
        if data.get("error"):
            print(f"error:        {data.get('error')}")
        if data.get("result"):
            print("result:")
            print(json.dumps(data["result"], indent=2, default=str))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    import contextlib

    with _client(args) as c, c.stream(
        "GET", "/v1/admin/export", params={"tenant_id": args.tenant_id},
    ) as r:
        if r.status_code >= 400:
            r.read()
            sys.stderr.write(f"HTTP {r.status_code}: {r.text}\n")
            return 1
        if args.output == "-":
            out = sys.stdout
            close_after = contextlib.nullcontext()
        else:
            out = open(args.output, "wb")  # noqa: SIM115
            close_after = out
        with close_after:
            for chunk in r.iter_bytes():
                if hasattr(out, "buffer"):
                    out.buffer.write(chunk)
                else:
                    out.write(chunk)
    if args.output != "-":
        sys.stderr.write(f"exported to {args.output}\n")
    return 0


def cmd_version(args: argparse.Namespace) -> int:  # noqa: ARG001
    """Print the bundled mypalace-client version."""
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _v
    try:
        v = _v("mypalace-client")
    except PackageNotFoundError:
        v = "unknown"
    print(f"mypalace-admin (mypalace-client {v})")
    return 0


# ---------------------------------------------------------------------------
# argparse wiring
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mypalace-admin",
        description="MyPalace operator CLI. Wraps the HTTP admin surface.",
    )
    parser.add_argument(
        "--url",
        help=f"MyPalace base URL (default: {DEFAULT_URL} or ${ENV_URL})",
    )
    parser.add_argument(
        "--admin-key",
        help=f"Admin API key (default: ${ENV_KEY})",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit raw JSON instead of human-readable tables",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("health", help="Run /health/deep").set_defaults(
        func=cmd_health,
    )
    sub.add_parser("version", help="Print client + server version").set_defaults(
        func=cmd_version,
    )

    # keys
    p_keys = sub.add_parser("keys", help="Manage API keys")
    sub_keys = p_keys.add_subparsers(dest="keys_cmd", required=True)
    p = sub_keys.add_parser("list", help="List API keys")
    p.add_argument("--include-revoked", action="store_true")
    p.set_defaults(func=cmd_keys_list)
    p = sub_keys.add_parser("mint", help="Mint a new API key")
    p.add_argument("--label", required=True)
    p.add_argument("--scopes", required=True, help="comma-separated: read,write,admin,unlimited")
    p.add_argument("--tenant-id", help="Bind the key to this tenant")
    p.add_argument("--cross-tenant", action="store_true",
                   help="Mint a cross-tenant admin key")
    p.set_defaults(func=cmd_keys_mint)
    p = sub_keys.add_parser("revoke", help="Revoke a key by ID")
    p.add_argument("key_id")
    p.set_defaults(func=cmd_keys_revoke)

    # tenants
    p_t = sub.add_parser("tenants", help="Manage tenants")
    sub_t = p_t.add_subparsers(dest="tenants_cmd", required=True)
    sub_t.add_parser("list", help="List tenants").set_defaults(func=cmd_tenants_list)
    p = sub_t.add_parser("create", help="Create a tenant")
    p.add_argument("--id", required=True)
    p.add_argument("--label", required=True)
    p.set_defaults(func=cmd_tenants_create)

    # stats
    p = sub.add_parser("stats", help="Per-tenant or ALL stats snapshot")
    p.add_argument("tenant_id", help="Tenant id, or 'ALL' for all tenants")
    p.set_defaults(func=cmd_stats)

    # audit
    p = sub.add_parser("audit", help="Query the admin audit trail")
    p.add_argument("--since", help="ISO timestamp (e.g. 2026-05-05T00:00:00Z)")
    p.add_argument("--key-id")
    p.add_argument("--path-prefix")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_audit)

    # reembed
    p = sub.add_parser("reembed", help="Enqueue a tenant reembed job")
    p.add_argument("tenant_id")
    p.add_argument("--provider", default="huggingface")
    p.add_argument("--model", required=True)
    p.add_argument("--token", help="HF token / OpenAI API key")
    p.add_argument("--batch-size", type=int, default=100)
    p.set_defaults(func=cmd_reembed)

    # job
    p = sub.add_parser("job", help="Look up a worker job by id")
    p.add_argument("job_id")
    p.set_defaults(func=cmd_job)

    # export
    p = sub.add_parser("export", help="Stream a tenant NDJSON export")
    p.add_argument("tenant_id")
    p.add_argument("-o", "--output", default="-",
                   help="Output file (- for stdout)")
    p.set_defaults(func=cmd_export)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
