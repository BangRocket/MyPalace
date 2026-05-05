// Admin key persistence (sessionStorage — clears on tab close, per design §4).
//
// We use sessionStorage rather than localStorage so that closing the tab
// effectively logs the operator out. There is no separate logout flow.

const ADMIN_KEY_STORAGE = "mypalace.adminKey";

export function getAdminKey(): string | null {
  try {
    return sessionStorage.getItem(ADMIN_KEY_STORAGE);
  } catch {
    return null;
  }
}

export function setAdminKey(key: string): void {
  sessionStorage.setItem(ADMIN_KEY_STORAGE, key);
}

export function clearAdminKey(): void {
  sessionStorage.removeItem(ADMIN_KEY_STORAGE);
}

export function hasAdminKey(): boolean {
  return getAdminKey() !== null;
}
