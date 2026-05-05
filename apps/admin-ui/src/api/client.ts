import { clearAdminKey, getAdminKey } from "../auth/storage";

// Same-origin client. The UI is mounted at /admin/* on the MyPalace
// server (design §5), so we hit the existing /v1/admin endpoints
// directly with no CORS to worry about. In dev, vite.config.ts
// proxies /v1 to localhost:8000.

export class HttpError extends Error {
  constructor(
    public status: number,
    message: string,
    public body?: unknown,
  ) {
    super(message);
    this.name = "HttpError";
  }
}

export interface RequestOptions {
  method?: "GET" | "POST" | "DELETE" | "PATCH" | "PUT";
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined>;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  if (!query) return path;
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null && v !== "") usp.set(k, String(v));
  }
  const qs = usp.toString();
  return qs ? `${path}?${qs}` : path;
}

export async function request<T>(
  path: string,
  opts: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const adminKey = getAdminKey();
  if (adminKey) headers["X-Palace-Key"] = adminKey;

  const res = await fetch(buildUrl(path, opts.query), {
    method: opts.method ?? "GET",
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });

  // 401 → admin key was wrong / revoked / expired. Wipe the stored key
  // so the App-level guard kicks the operator back to the login screen.
  if (res.status === 401) {
    clearAdminKey();
  }

  let body: unknown;
  const contentType = res.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    body = await res.json().catch(() => undefined);
  } else if (res.status !== 204) {
    body = await res.text().catch(() => undefined);
  }

  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") message = `${message}: ${detail}`;
    }
    throw new HttpError(res.status, message, body);
  }

  return body as T;
}
