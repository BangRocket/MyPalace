import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { setAdminKey } from "../auth/storage";
import { request, HttpError } from "../api/client";
import type { ReadyResponse } from "../api/types";

export function Login() {
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const navigate = useNavigate();

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!key.trim()) return;
    setPending(true);
    setAdminKey(key.trim());
    try {
      // Round-trip a cheap admin endpoint to validate the key.
      // /v1/admin/tenants requires admin scope; /ready is public so we
      // can't use it. tenants list is the cheapest admin verb.
      await request<unknown>("/v1/admin/tenants");
      navigate("/tenants", { replace: true });
    } catch (err) {
      if (err instanceof HttpError && err.status === 401) {
        setError("Invalid admin key.");
      } else if (err instanceof HttpError && err.status === 403) {
        setError("Key authenticated but lacks admin scope.");
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Login failed.");
      }
    } finally {
      setPending(false);
    }
  }

  // Optional: probe /ready so the operator sees if the server is even up.
  void Promise.resolve<ReadyResponse | null>(null);

  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg p-6 space-y-4"
      >
        <div>
          <h1 className="text-xl font-semibold">MyPalace Admin</h1>
          <p className="text-sm text-slate-600 dark:text-slate-400 mt-1">
            Sign in with an admin API key.
          </p>
        </div>
        <label className="block">
          <span className="text-sm font-medium block mb-1">Admin key</span>
          <input
            type="password"
            autoFocus
            autoComplete="current-password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="pk_live_..."
            className="w-full font-mono text-sm px-3 py-2 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </label>
        {error && (
          <div className="text-sm text-red-600 dark:text-red-400">{error}</div>
        )}
        <button
          type="submit"
          disabled={pending || !key.trim()}
          className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-400 text-white font-medium px-4 py-2 rounded-md transition-colors"
        >
          {pending ? "Verifying…" : "Sign in"}
        </button>
        <p className="text-xs text-slate-500">
          Key is stored in <code className="font-mono">sessionStorage</code>.
          Closing the tab signs out.
        </p>
      </form>
    </div>
  );
}
