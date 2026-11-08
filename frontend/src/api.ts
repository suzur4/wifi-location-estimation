export type TeacherStatus = 'located' | 'unknown' | 'private';

export type Teacher = {
  id: string;
  name: string;
  kana?: string;
  subject: string;
  status: TeacherStatus;
  area: string | null;
  updated_at: string | null;
  reason: string | null;
};

export type AdminTeacher = Teacher & {
  device_id: string;
  private: boolean;
  fsm?: { phase: string; confirmations: number; required_confirmations: number };
};

export type Area = { id: string; label: string };

export type Config = {
  algorithm: string;
  algorithms: { id: string; label: string }[];
  demo: boolean;
  fsm?: { enabled: boolean; confirmations: number; max_age_seconds: number; min_aps: number; min_margin: number };
};

export type Metric = {
  id: string | null;
  algorithm: string;
  preprocessing: string;
  accuracy: number;
  false_display_rate: number;
  unknown_rate: number;
  precision: number | null;
  latency_ms: number;
  k?: number;
  selection?: string;
  selected_aps?: string[] | null;
};

export type SeriesRow = { time: string } & Record<string, string | number | null>;

export type Research = {
  dataset: string;
  datasets: { id: string; label: string }[];
  source: string;
  experiment_id: string;
  counts: number[];
  created_at?: string | null;
  metrics: Metric[];
  series: SeriesRow[];
  candidates: { area: string; score: number }[];
  note: string;
  citation?: string | null;
  license?: string | null;
};

/** An API failure. status is 0 when the server could not be reached. */
export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = 'ApiError';
  }
}

export const TIMEOUT_MS = 10_000;
const NO_RESPONSE = 'サーバーから応答がありません。しばらくしてからもう一度お試しください。';

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  // Without a timeout, a stalled connection would leave the screen loading forever.
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    let response: Response;
    try {
      response = await fetch(`/api${path}`, {
        ...options,
        signal: controller.signal,
        headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers },
      });
    } catch {
      throw new ApiError(controller.signal.aborted ? NO_RESPONSE
        : 'サーバーに接続できません。サーバーが起動しているか確認してください。', 0);
    }
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      const detail = typeof body?.detail === 'string' ? body.detail : '';
      throw new ApiError(detail || `通信に失敗しました（エラー ${response.status}）`, response.status);
    }
    if (response.status === 204) return undefined as T;
    try {
      return await response.json() as T;
    } catch {
      // The timeout can also fire while the body is still arriving.
      throw new ApiError(controller.signal.aborted ? NO_RESPONSE : 'サーバーの応答を読み取れませんでした。', response.status);
    }
  } finally {
    window.clearTimeout(timer);
  }
}

export function canUseOperatorTools() {
  // The laptop serves its LAN directory over HTTP. The operator's SSH tunnel opens on loopback.
  return window.location.protocol === 'https:' || ['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname);
}

export function adminApi<T>(path: string, token: string, method = 'GET', body?: unknown) {
  if (!canUseOperatorTools()) {
    return Promise.reject(new ApiError('管理画面はSSHトンネル経由で開いてください。', 0));
  }
  return api<T>(`/admin${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}` },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}
