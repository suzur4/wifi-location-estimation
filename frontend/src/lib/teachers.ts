import type { Teacher } from '../api';

export const MAX_AGE_MS = 180_000;
const FUTURE_TOLERANCE_MS = 5_000;

/**
 * The browser checks freshness again, so an area is never kept on screen
 * after the measurement expires, even while the server cannot be reached.
 */
export function withFreshness(teacher: Teacher, now: number): Teacher {
  if (teacher.status !== 'located') return teacher;
  const measured = teacher.updated_at ? new Date(teacher.updated_at).getTime() : NaN;
  if (!Number.isFinite(measured) || now - measured >= MAX_AGE_MS) {
    return { ...teacher, status: 'unknown', area: null, reason: 'stale' };
  }
  if (measured - now > FUTURE_TOLERANCE_MS) {
    return { ...teacher, status: 'unknown', area: null, reason: 'future_measurement' };
  }
  return teacher;
}

const reasonLabels: Record<string, string> = {
  stale: '測定から3分以上たっています',
  stale_data: '測定から3分以上たっています',
  no_data: '測定データがありません',
  no_observation: '測定データがありません',
  insufficient_data: '測定データが足りません',
  insufficient_aps: '受信できたAPが足りません',
  insufficient_overlap: '照合できるAPが足りません',
  unknown_ap: 'APの場所が登録されていません',
  unmapped_ap: 'APの場所が登録されていません',
  ambiguous: '場所の候補が複数あります',
  low_confidence: '場所を1つに絞れません',
  unfamiliar: 'いつもの電波の状態と違います',
  unfamiliar_pattern: 'いつもの電波の状態と違います',
  unknown_area: 'いつもの電波の状態と違います',
  future: '測定時刻が正しくありません',
  future_timestamp: '測定時刻が正しくありません',
  future_measurement: '測定時刻が正しくありません',
  source_mismatch: '測定方法が学習データと違います',
  no_training_data: '学習データがありません',
};

export function reasonLabel(reason: string | null) {
  return reasonLabels[reason ?? ''] ?? '場所を判定できませんでした';
}

export const algorithmLabels: Record<string, string> = {
  connected_ap: '接続先AP', strongest_ap: '最強AP', '1nn': '1-NN', knn: 'k-NN',
  weighted_knn: '距離重み付きk-NN', rank: 'RSSI順位', gaussian: '確率的分類',
};

export const preprocessingLabels: Record<string, string> = {
  none: 'なし', mean: '平均', median: '中央値', ema: 'EMA', kalman: 'カルマンフィルタ', robust_mean: '頑健な平均',
};
