import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { request } from "../api/client";
import type { ApiResponse, TenantStats } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { ErrorBox } from "../components/ErrorBox";

export function Stats() {
  const [tenantId, setTenantId] = useState("default");

  const statsQuery = useQuery<ApiResponse<TenantStats | { tenants: TenantStats[] }>>({
    queryKey: ["stats", tenantId],
    queryFn: () =>
      request<ApiResponse<TenantStats | { tenants: TenantStats[] }>>(
        "/v1/admin/stats",
        { query: { tenant_id: tenantId } },
      ),
    enabled: tenantId.length > 0,
  });

  const dataField = statsQuery.data?.data;
  const tenants: TenantStats[] = dataField
    ? "tenants" in dataField
      ? dataField.tenants
      : [dataField]
    : [];

  return (
    <div>
      <PageHeader
        title="Stats"
        description="Per-tenant snapshot. Use 'ALL' to fan out across every tenant."
      />

      <div className="mb-4 flex items-center gap-2">
        <label className="text-sm">tenant_id:</label>
        <input
          value={tenantId}
          onChange={(e) => setTenantId(e.target.value)}
          className="font-mono text-sm px-3 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800"
          placeholder="default or ALL"
        />
      </div>

      <ErrorBox error={statsQuery.error} />

      {statsQuery.isLoading ? (
        <div className="text-sm text-slate-500">Loading…</div>
      ) : tenants.length === 0 ? (
        <div className="text-sm text-slate-500">No data.</div>
      ) : (
        <div className="space-y-6">
          {tenants.map((t) => (
            <TenantStatsCard key={t.tenant_id} stats={t} />
          ))}
        </div>
      )}
    </div>
  );
}

function TenantStatsCard({ stats }: { stats: TenantStats }) {
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-md p-4">
      <div className="text-lg font-semibold mb-3 font-mono">{stats.tenant_id}</div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
        <Counter label="memories" value={stats.row_counts.memories} />
        <Counter label="sessions" value={stats.row_counts.sessions} />
        <Counter label="episodes" value={stats.row_counts.episodes} />
        <Counter label="arcs" value={stats.row_counts.narrative_arcs} />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
        <Counter label="created (7d)" value={stats.activity_7d.memories_created} />
        <Counter label="accessed (7d)" value={stats.activity_7d.memories_accessed} />
        <Counter label="reflected (7d)" value={stats.activity_7d.episodes_reflected} />
        <Counter label="intentions fired (7d)" value={stats.activity_7d.intentions_fired} />
      </div>
      <div className="text-sm text-slate-600 dark:text-slate-400 grid grid-cols-2 gap-2 mb-4">
        <div>FSRS tracked: {stats.fsrs_health.tracked_memories}</div>
        <div>FSRS key: {stats.fsrs_health.key_memories}</div>
        <div>mean stability: {stats.fsrs_health.mean_stability.toFixed(2)}</div>
        <div>
          mean retrieval: {stats.fsrs_health.mean_retrieval_strength.toFixed(2)}
        </div>
      </div>
      {stats.top_users_by_access_7d.length > 0 && (
        <div>
          <div className="text-sm font-medium mb-1">Top users (7d access)</div>
          <div className="space-y-1">
            {stats.top_users_by_access_7d.map((u) => (
              <div
                key={u.user_id}
                className="flex justify-between text-xs font-mono"
              >
                <span>{u.user_id}</span>
                <span>{u.access_count}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Counter({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="text-2xl font-semibold tabular-nums">{value}</div>
      <div className="text-xs text-slate-500 uppercase tracking-wide mt-0.5">
        {label}
      </div>
    </div>
  );
}
