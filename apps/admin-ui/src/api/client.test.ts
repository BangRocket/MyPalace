import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HttpError, request } from "./client";
import { clearAdminKey, getAdminKey, setAdminKey } from "../auth/storage";

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("request", () => {
  it("attaches X-Palace-Key when admin key is set", async () => {
    setAdminKey("pk_live_test");
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { data: [], meta: { count: 0 } }));

    await request("/v1/admin/tenants");

    const [, init] = fetchMock.mock.calls[0]!;
    expect((init as RequestInit).headers).toMatchObject({
      "X-Palace-Key": "pk_live_test",
      "Content-Type": "application/json",
    });
  });

  it("does NOT send X-Palace-Key when key absent", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, {}));
    await request("/ready");
    const [, init] = fetchMock.mock.calls[0]!;
    expect((init as RequestInit).headers).not.toHaveProperty("X-Palace-Key");
  });

  it("clears stored key on 401", async () => {
    setAdminKey("pk_live_bad");
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { detail: "unauthenticated" }));

    await expect(request("/v1/admin/tenants")).rejects.toThrow(HttpError);
    expect(getAdminKey()).toBeNull();
  });

  it("encodes query params, dropping undefined / empty", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, {}));
    await request("/v1/admin/audit", {
      query: { limit: 50, key_id: undefined, path_prefix: "" },
    });
    const [url] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/v1/admin/audit?limit=50");
  });

  it("passes a JSON body on POST", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { data: {}, meta: { count: 1 } }));
    await request("/v1/admin/tenants", {
      method: "POST",
      body: { id: "acme", label: "Acme" },
    });
    const [, init] = fetchMock.mock.calls[0]!;
    expect((init as RequestInit).method).toBe("POST");
    expect((init as RequestInit).body).toBe('{"id":"acme","label":"Acme"}');
  });

  it("includes detail string in HttpError message", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(409, { detail: "already exists" }));
    try {
      await request("/v1/admin/tenants", { method: "POST", body: {} });
      expect.unreachable("expected throw");
    } catch (e) {
      expect(e).toBeInstanceOf(HttpError);
      expect((e as HttpError).status).toBe(409);
      expect((e as HttpError).message).toContain("already exists");
    }
  });

  it("does not clear key on non-401 errors", async () => {
    setAdminKey("pk_live_keep");
    fetchMock.mockResolvedValueOnce(jsonResponse(403, { detail: "forbidden" }));
    await expect(request("/v1/admin/keys")).rejects.toThrow();
    expect(getAdminKey()).toBe("pk_live_keep");
  });

  it("handles 204 No Content", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    const result = await request("/v1/admin/keys/abc", { method: "DELETE" });
    expect(result).toBeUndefined();
  });
});

describe("clearAdminKey", () => {
  it("removes the stored key", () => {
    setAdminKey("k");
    clearAdminKey();
    expect(getAdminKey()).toBeNull();
  });
});
