import { useQuery } from "@tanstack/react-query";
import { request } from "../api/client";
import type { ReadyResponse } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { ErrorBox } from "../components/ErrorBox";

export function Health() {
  const ready = useQuery<ReadyResponse>({
    queryKey: ["ready"],
    queryFn: () => request<ReadyResponse>("/ready"),
    refetchInterval: 10_000,
  });

  return (
    <div>
      <PageHeader
        title="Health"
        description="Backend-by-backend status from /ready, refreshing every 10s."
      />
      <ErrorBox error={ready.error} />

      {ready.data && (
        <div className="space-y-4">
          <div
            className={`px-4 py-3 rounded-md text-sm font-medium ${
              ready.data.status === "ok"
                ? "bg-green-50 text-green-900 border border-green-200 dark:bg-green-950/30 dark:text-green-200 dark:border-green-900"
                : "bg-amber-50 text-amber-900 border border-amber-200 dark:bg-amber-950/30 dark:text-amber-200 dark:border-amber-900"
            }`}
          >
            overall: {ready.data.status}
          </div>
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-md divide-y divide-slate-200 dark:divide-slate-800">
            {ready.data.backends.map((b) => (
              <div
                key={b.name}
                className="px-4 py-3 flex items-center justify-between"
              >
                <div className="flex items-center gap-3">
                  <span
                    className={`inline-block w-2.5 h-2.5 rounded-full ${
                      !b.configured
                        ? "bg-slate-400"
                        : b.ok
                          ? "bg-green-500"
                          : "bg-red-500"
                    }`}
                  />
                  <span className="font-mono text-sm">{b.name}</span>
                  {!b.configured && (
                    <span className="text-xs text-slate-500">
                      (not configured)
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-4 text-xs text-slate-600 dark:text-slate-400">
                  <span className="tabular-nums">{b.elapsed_ms}ms</span>
                  <span className="font-mono">{b.detail}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
