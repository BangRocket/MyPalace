import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request, HttpError } from "../api/client";
import type { ApiResponse, Tenant } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { Table } from "../components/Table";
import { ErrorBox } from "../components/ErrorBox";

export function Tenants() {
  const qc = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [newId, setNewId] = useState("");
  const [newLabel, setNewLabel] = useState("");

  const tenantsQuery = useQuery<ApiResponse<Tenant[]>>({
    queryKey: ["tenants"],
    queryFn: () => request<ApiResponse<Tenant[]>>("/v1/admin/tenants"),
  });

  const createMutation = useMutation({
    mutationFn: (body: { id: string; label: string }) =>
      request<ApiResponse<Tenant>>("/v1/admin/tenants", {
        method: "POST",
        body,
      }),
    onSuccess: () => {
      setCreating(false);
      setNewId("");
      setNewLabel("");
      void qc.invalidateQueries({ queryKey: ["tenants"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) =>
      request<unknown>(`/v1/admin/tenants/${encodeURIComponent(id)}`, {
        method: "DELETE",
        query: { confirm: id },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tenants"] }),
  });

  return (
    <div>
      <PageHeader
        title="Tenants"
        description="Hard data-isolation boundary. One tenant per logical customer / project."
        actions={
          !creating ? (
            <button
              onClick={() => setCreating(true)}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-md text-sm font-medium"
            >
              New tenant
            </button>
          ) : null
        }
      />

      {creating && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!newId.trim() || !newLabel.trim()) return;
            createMutation.mutate({ id: newId.trim(), label: newLabel.trim() });
          }}
          className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-md p-4 mb-4 space-y-3"
        >
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="text-sm font-medium block mb-1">id</span>
              <input
                value={newId}
                onChange={(e) => setNewId(e.target.value)}
                pattern="[a-z0-9_-]{1,32}"
                title="lowercase letters, digits, _, - (max 32 chars)"
                className="w-full font-mono text-sm px-3 py-2 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800"
                placeholder="acme"
              />
            </label>
            <label className="block">
              <span className="text-sm font-medium block mb-1">label</span>
              <input
                value={newLabel}
                onChange={(e) => setNewLabel(e.target.value)}
                className="w-full text-sm px-3 py-2 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800"
                placeholder="Acme Corp"
              />
            </label>
          </div>
          <ErrorBox error={createMutation.error} />
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={createMutation.isPending}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-400 text-white rounded-md text-sm font-medium"
            >
              {createMutation.isPending ? "Creating…" : "Create"}
            </button>
            <button
              type="button"
              onClick={() => setCreating(false)}
              className="px-4 py-2 bg-slate-200 hover:bg-slate-300 dark:bg-slate-800 dark:hover:bg-slate-700 rounded-md text-sm"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      <ErrorBox error={tenantsQuery.error} />
      <ErrorBox error={deleteMutation.error} />

      {tenantsQuery.isLoading ? (
        <div className="text-sm text-slate-500">Loading…</div>
      ) : (
        <Table<Tenant>
          rows={tenantsQuery.data?.data ?? []}
          rowKey={(t) => t.id}
          columns={[
            {
              key: "id",
              header: "id",
              render: (t) => <code className="font-mono">{t.id}</code>,
            },
            { key: "label", header: "label", render: (t) => t.label },
            {
              key: "created_at",
              header: "created",
              render: (t) =>
                t.created_at ? t.created_at.replace("T", " ").slice(0, 19) : "",
              className: "text-slate-500 text-xs",
            },
            {
              key: "actions",
              header: "",
              render: (t) => (
                <button
                  onClick={() => {
                    const ok = window.confirm(
                      `Delete tenant "${t.id}"? Tenant must have no data.\n\n` +
                        "(Use the CLI with --force --confirm if you want to drop data too.)",
                    );
                    if (ok) deleteMutation.mutate(t.id);
                  }}
                  className="text-xs text-red-600 hover:text-red-700"
                  disabled={deleteMutation.isPending}
                >
                  Delete
                </button>
              ),
              className: "text-right",
            },
          ]}
        />
      )}
    </div>
  );
}
