import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { request } from "../api/client";
import type { ApiResponse, AuditEntry } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { Table } from "../components/Table";
import { ErrorBox } from "../components/ErrorBox";

export function Audit() {
  const [keyId, setKeyId] = useState("");
  const [pathPrefix, setPathPrefix] = useState("");
  const [limit, setLimit] = useState(100);

  const auditQuery = useQuery<ApiResponse<AuditEntry[]>>({
    queryKey: ["audit", keyId, pathPrefix, limit],
    queryFn: () =>
      request<ApiResponse<AuditEntry[]>>("/v1/admin/audit", {
        query: {
          key_id: keyId || undefined,
          path_prefix: pathPrefix || undefined,
          limit,
        },
      }),
  });

  return (
    <div>
      <PageHeader
        title="Audit log"
        description="Every admin operation, recent first. Filter by key or path prefix."
      />
      <div className="flex flex-wrap items-end gap-3 mb-4">
        <label className="block">
          <span className="text-xs uppercase tracking-wide text-slate-500 block mb-1">
            key id
          </span>
          <input
            value={keyId}
            onChange={(e) => setKeyId(e.target.value)}
            className="font-mono text-sm px-3 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800"
            placeholder=""
          />
        </label>
        <label className="block">
          <span className="text-xs uppercase tracking-wide text-slate-500 block mb-1">
            path prefix
          </span>
          <input
            value={pathPrefix}
            onChange={(e) => setPathPrefix(e.target.value)}
            className="font-mono text-sm px-3 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800"
            placeholder="/v1/admin/keys"
          />
        </label>
        <label className="block">
          <span className="text-xs uppercase tracking-wide text-slate-500 block mb-1">
            limit
          </span>
          <input
            type="number"
            min={1}
            max={1000}
            value={limit}
            onChange={(e) => setLimit(Math.max(1, Math.min(1000, +e.target.value)))}
            className="text-sm px-3 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 w-24"
          />
        </label>
      </div>

      <ErrorBox error={auditQuery.error} />
      {auditQuery.isLoading ? (
        <div className="text-sm text-slate-500">Loading…</div>
      ) : (
        <Table<AuditEntry>
          rows={auditQuery.data?.data ?? []}
          rowKey={(r) => r.id}
          columns={[
            {
              key: "when",
              header: "when",
              render: (r) =>
                r.created_at ? r.created_at.replace("T", " ").slice(0, 19) : "",
              className: "font-mono text-xs whitespace-nowrap",
            },
            {
              key: "status",
              header: "",
              render: (r) => (
                <span
                  className={`text-xs px-2 py-0.5 rounded font-mono ${
                    r.status_class === "2xx"
                      ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300"
                      : r.status_class === "4xx"
                        ? "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300"
                        : r.status_class === "5xx"
                          ? "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300"
                          : "bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-300"
                  }`}
                >
                  {r.status_class}
                </span>
              ),
            },
            {
              key: "ms",
              header: "ms",
              render: (r) => r.response_ms,
              className: "text-right tabular-nums text-xs",
            },
            {
              key: "method",
              header: "method",
              render: (r) => (
                <code className="font-mono text-xs">{r.method}</code>
              ),
            },
            {
              key: "path",
              header: "path",
              render: (r) => (
                <code className="font-mono text-xs break-all">{r.path}</code>
              ),
            },
            {
              key: "tenant",
              header: "tenant",
              render: (r) => (
                <code className="font-mono text-xs">{r.tenant_id ?? ""}</code>
              ),
            },
            {
              key: "key",
              header: "key",
              render: (r) => (
                <code className="font-mono text-xs text-slate-500">
                  {(r.key_id ?? "").slice(0, 8)}
                </code>
              ),
            },
          ]}
        />
      )}
    </div>
  );
}
