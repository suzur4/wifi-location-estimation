export type Teacher = {
  id: string; name: string; subject: string;
  status: 'located' | 'unknown' | 'private';
  area: string | null; updated_at: string | null; reason: string | null;
};
export type AdminTeacher = Teacher & { device_id: string; private: boolean };
export type AreaConfig = { areas: { id: string; label: string }[]; ap_areas: Record<string, string> };
export type Config = { algorithm: string; algorithms: { id: string; label: string }[]; demo: boolean };
export type Metric = {
  id: string; algorithm: string; preprocessing: string; accuracy: number;
  false_display_rate: number; unknown_rate: number; precision: number | null; latency_ms: number;
};
export type Research = {
  source: string; experiment_id: string; metrics: Metric[];
  series: ({ time: string } & Record<string, string | number | null>)[];
  candidates: { area: string; score: number }[]; note: string;
};
export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : `通信に失敗しました（${response.status}）`);
  }
  return response.json() as Promise<T>;
}
export function adminApi<T>(path: string, token: string, method = 'GET', body?: unknown) {
  return api<T>(`/admin${path}`, { method, headers: { Authorization: `Bearer ${token}` }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
}
