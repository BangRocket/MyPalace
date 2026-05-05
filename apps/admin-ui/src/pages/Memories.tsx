import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { request } from "../api/client";
import type { ApiResponse, Memory } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { Table } from "../components/Table";
import { ErrorBox } from "../components/ErrorBox";

// Read-only browser. Write paths stay on the API for safety
// (per design doc §1).

export function Memories() {
  const [userId, setUserId] = useState("");
  const [agentId, setAgentId] = useState("");
  const [limit, setLimit] = useState(50);

  const memoriesQuery = useQuery<ApiResponse<Memory[]>>({
    queryKey: ["memories", userId, agentId, limit],
    queryFn: () =>
      request<ApiResponse<Memory[]>>(
        `/v1/users/${encodeURIComponent(userId)}/memories`,
        {
          query: {
            agent_id: agentId || undefined,
            limit,
          },
        },
      ),
    enabled: userId.length > 0,
  });

  return (
    <div>
      <PageHeader
        title="Memories"
        description="Read-only browser. Filter by user (and optionally agent)."
      />
      <div className="flex flex-wrap items-end gap-3 mb-4">
        <label className="block">
          <span className="text-xs uppercase tracking-wide text-slate-500 block mb-1">
            user_id (required)
          </span>
          <input
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            className="font-mono text-sm px-3 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800"
            placeholder="discord-1234"
          />
        </label>
        <label className="block">
          <span className="text-xs uppercase tracking-wide text-slate-500 block mb-1">
            agent_id
          </span>
          <input
            value={agentId}
            onChange={(e) => setAgentId(e.target.value)}
            className="font-mono text-sm px-3 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800"
            placeholder=""
          />
        </label>
        <label className="block">
          <span className="text-xs uppercase tracking-wide text-slate-500 block mb-1">
            limit
          </span>
          <input
            type="number"
            min={1}
            max={500}
            value={limit}
            onChange={(e) => setLimit(Math.max(1, Math.min(500, +e.target.value)))}
            className="text-sm px-3 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 w-24"
          />
        </label>
      </div>

      <ErrorBox error={memoriesQuery.error} />

      {!userId ? (
        <div className="text-sm text-slate-500 italic">
          Enter a user_id to browse memories.
        </div>
      ) : memoriesQuery.isLoading ? (
        <div className="text-sm text-slate-500">Loading…</div>
      ) : (
        <Table<Memory>
          rows={memoriesQuery.data?.data ?? []}
          rowKey={(m) => m.id}
          columns={[
            {
              key: "type",
              header: "type",
              render: (m) => (
                <span className="text-xs px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 font-mono">
                  {m.memory_type}
                </span>
              ),
            },
            {
              key: "content",
              header: "content",
              render: (m) => <span className="text-sm">{m.content}</span>,
            },
            {
              key: "importance",
              header: "imp",
              render: (m) => m.importance.toFixed(2),
              className: "text-right tabular-nums text-xs",
            },
            {
              key: "agent",
              header: "agent",
              render: (m) => (
                <code className="font-mono text-xs">{m.agent_id ?? ""}</code>
              ),
            },
            {
              key: "created",
              header: "created",
              render: (m) =>
                m.created_at ? m.created_at.replace("T", " ").slice(0, 19) : "",
              className: "text-slate-500 text-xs whitespace-nowrap",
            },
          ]}
        />
      )}
    </div>
  );
}
