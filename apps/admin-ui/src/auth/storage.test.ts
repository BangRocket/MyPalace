import { afterEach, describe, expect, it } from "vitest";
import {
  clearAdminKey,
  getAdminKey,
  hasAdminKey,
  setAdminKey,
} from "./storage";

afterEach(() => {
  sessionStorage.clear();
});

describe("admin key storage", () => {
  it("returns null when nothing stored", () => {
    expect(getAdminKey()).toBeNull();
    expect(hasAdminKey()).toBe(false);
  });

  it("round-trips a set value", () => {
    setAdminKey("pk_live_abc");
    expect(getAdminKey()).toBe("pk_live_abc");
    expect(hasAdminKey()).toBe(true);
  });

  it("clears", () => {
    setAdminKey("pk_live_abc");
    clearAdminKey();
    expect(getAdminKey()).toBeNull();
    expect(hasAdminKey()).toBe(false);
  });

  it("uses sessionStorage, not localStorage", () => {
    setAdminKey("pk_live_xyz");
    expect(sessionStorage.getItem("mypalace.adminKey")).toBe("pk_live_xyz");
    expect(localStorage.getItem("mypalace.adminKey")).toBeNull();
  });
});
