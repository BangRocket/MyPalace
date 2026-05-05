import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "../api/client";
import type { ApiKey, ApiResponse, MintedKey } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { Table } from "../components/Table";
import { ErrorBox } from "../components/ErrorBox";

const VALID_SCOPES = ["read", "write", "admin", "unlimited"] as const;

export function Keys() {
  const qc = useQueryClient();
  const [showRevoked, setShowRevoked] = useState(false);
  const [creating, setCreating] = useState(false);
  const [label, setLabel] = useState("");
  const [scopes, setScopes] = useState<Set<string>>(new Set(["read", "write"]));
  const [tenantId, setTenantId] = useState("");
  const [crossTenant, setCrossTenant] = useState(false);
  const [minted, setMinted] = useState<MintedKey | null>(null);

  const keysQuery = useQuery<ApiResponse<ApiKey[]>>({
    queryKey: ["keys", showRevoked],
    queryFn: () =>
      request<ApiResponse<ApiKey[]>>("/v1/admin/keys", {
        query: showRevoked ? { include_revoked: "true" } : undefined,
      }),
  });

  const mintMutation = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      request<ApiResponse<MintedKey>>("/v1/admin/keys", {
        method: "POST",
        body,
      }),
    onSuccess: (resp) => {
      setMinted(resp.data);
      setCreating(false);
      setLabel("");
      setScopes(new Set(["read", "write"]));
      setTenantId("");
      setCrossTenant(false);
      void qc.invalidateQueries({ queryKey: ["keys"] });
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (key_id: string) =>
      request<unknown>(`/v1/admin/keys/${encodeURIComponent(key_id)}`, {
        method: "DELETE",
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["keys"] }),
  });

  return (
    <div>
      <PageHeader
        title="API keys"
        description="Tenant-bound or cross-tenant admin keys. Scopes: read, write, admin, unlimited."
        actions={
          !creating && !minted ? (
            <button
              onClick={() => setCreating(true)}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-md text-sm font-medium"
            >
              Mint key
            </button>
          ) : null
        }
      />

      {minted && (
        <div className="mb-4 bg-amber-50 dark:bg-amber-950/30 border border-amber-300 dark:border-amber-800 rounded-md p-4">
          <div className="text-sm font-semibold text-amber-900 dark:text-amber-200 mb-2">
            ⚠ Save this plaintext key now. It will not be shown again.
          </div>
          <code className="font-mono text-sm bg-white dark:bg-slate-900 px-3 py-2 rounded block break-all">
            {minted.plaintext_key}
          </code>
          <button
            onClick={() => setMinted(null)}
            className="mt-3 text-sm text-amber-900 dark:text-amber-200 underline"
          >
            I've saved it
          </button>
        </div>
      )}

      {creating && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!label.trim() || scopes.size === 0) return;
            const body: Record<string, unknown> = {
              label: label.trim(),
              scopes: [...scopes],
            };
            if (crossTenant) body["cross_tenant"] = true;
            else if (tenantId.trim()) body["tenant_id"] = tenantId.trim();
            mintMutation.mutate(body);
          }}
          className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-md p-4 mb-4 space-y-3"
        >
          <label className="block">
            <span className="text-sm font-medium block mb-1">label</span>
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              className="w-full text-sm px-3 py-2 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800"
              placeholder="acme-prod"
            />
          </label>
          <div>
            <span className="text-sm font-medium block mb-1">scopes</span>
            <div className="flex gap-3 flex-wrap">
              {VALID_SCOPES.map((scope) => (
                <label key={scope} className="flex items-center gap-1 text-sm">
                  <input
                    type="checkbox"
                    checked={scopes.has(scope)}
                    onChange={(e) => {
                      const next = new Set(scopes);
                      if (e.target.checked) next.add(scope);
                      else next.delete(scope);
                      setScopes(next);
                    }}
                  />
                  {scope}
                </label>
              ))}
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={crossTenant}
              onChange={(e) => setCrossTenant(e.target.checked)}
            />
            cross-tenant admin key (no tenant binding)
          </label>
          {!crossTenant && (
            <label className="block">
              <span className="text-sm font-medium block mb-1">
                tenant_id (leave blank to use the default tenant)
              </span>
              <input
                value={tenantId}
                onChange={(e) => setTenantId(e.target.value)}
                className="w-full font-mono text-sm px-3 py-2 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800"
                placeholder="acme"
              />
            </label>
          )}
          <ErrorBox error={mintMutation.error} />
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={mintMutation.isPending}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-400 text-white rounded-md text-sm font-medium"
            >
              {mintMutation.isPending ? "Minting…" : "Mint"}
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

      <div className="flex items-center gap-3 mb-3">
        <label className="flex items-center gap-1 text-sm">
          <input
            type="checkbox"
            checked={showRevoked}
            onChange={(e) => setShowRevoked(e.target.checked)}
          />
          show revoked
        </label>
      </div>

      <ErrorBox error={keysQuery.error} />
      <ErrorBox error={revokeMutation.error} />

      {keysQuery.isLoading ? (
        <div className="text-sm text-slate-500">Loading…</div>
      ) : (
        <Table<ApiKey>
          rows={keysQuery.data?.data ?? []}
          rowKey={(k) => k.key_id}
          columns={[
            {
              key: "prefix",
              header: "prefix",
              render: (k) => <code className="font-mono text-xs">{k.key_prefix}</code>,
            },
            { key: "label", header: "label", render: (k) => k.label },
            {
              key: "tenant",
              header: "tenant",
              render: (k) => (
                <code className="font-mono text-xs">
                  {k.tenant_id ?? "(cross-tenant)"}
                </code>
              ),
            },
            {
              key: "scopes",
              header: "scopes",
              render: (k) => (
                <div className="flex gap-1 flex-wrap">
                  {(k.scopes ?? []).map((s) => (
                    <span
                      key={s}
                      className="text-xs px-2 py-0.5 rounded bg-slate-200 dark:bg-slate-800"
                    >
                      {s}
                    </span>
                  ))}
                </div>
              ),
            },
            {
              key: "created",
              header: "created",
              render: (k) =>
                k.created_at ? k.created_at.replace("T", " ").slice(0, 19) : "",
              className: "text-slate-500 text-xs",
            },
            {
              key: "actions",
              header: "",
              render: (k) =>
                k.revoked_at ? (
                  <span className="text-xs text-slate-500">revoked</span>
                ) : (
                  <button
                    onClick={() => {
                      if (window.confirm(`Revoke key "${k.label}"?`)) {
                        revokeMutation.mutate(k.key_id);
                      }
                    }}
                    className="text-xs text-red-600 hover:text-red-700"
                  >
                    Revoke
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
