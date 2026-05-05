// Subset of MyPalace JSON shapes we care about.
// Mirrors mypalace/api/* response models. Kept narrow on purpose — this
// is the operator console, not a full API client; widen as new screens
// land.

export interface ApiResponse<T> {
  data: T;
  meta: { count: number; took_ms?: number };
}

export interface Tenant {
  id: string;
  label: string;
  created_at: string | null;
}

export interface ApiKey {
  key_id: string;
  key_prefix: string;
  label: string;
  tenant_id: string | null;
  scopes: string[];
  created_at: string | null;
  revoked_at: string | null;
}

export interface MintedKey extends ApiKey {
  plaintext_key: string;
}

export interface RowCounts {
  memories: number;
  sessions: number;
  episodes: number;
  narrative_arcs: number;
  intentions: number;
}

export interface Activity7d {
  memories_created: number;
  memories_accessed: number;
  episodes_reflected: number;
  intentions_fired: number;
}

export interface FsrsHealth {
  tracked_memories: number;
  key_memories: number;
  mean_stability: number;
  mean_retrieval_strength: number;
}

export interface TenantStats {
  tenant_id: string;
  row_counts: RowCounts;
  activity_7d: Activity7d;
  fsrs_health: FsrsHealth;
  top_users_by_access_7d: { user_id: string; access_count: number }[];
}

export interface AuditEntry {
  id: string;
  key_id: string;
  tenant_id: string | null;
  method: string;
  path: string;
  status_class: string;
  response_ms: number;
  created_at: string | null;
}

export interface Memory {
  id: string;
  user_id: string;
  agent_id: string | null;
  content: string;
  memory_type: string;
  importance: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface BackendCheck {
  name: string;
  ok: boolean;
  configured: boolean;
  elapsed_ms: number;
  detail: string;
}

export interface ReadyResponse {
  status: "ok" | "degraded";
  service: string;
  backends: BackendCheck[];
}
