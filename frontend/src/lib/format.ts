function toDate(value: string | number | null | undefined) {
  if (value === null || value === undefined) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** 「1分以内」「12分前」「3時間前」 */
export function relativeTime(value: string | null, now: number) {
  const date = toDate(value);
  if (!date) return '';
  const minutes = Math.floor((now - date.getTime()) / 60_000);
  if (minutes < 1) return '1分以内';
  if (minutes < 60) return `${minutes}分前`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)}時間前`;
  return `${Math.floor(minutes / 1440)}日前`;
}

/** Today: 「19:05」. Other days: 「11/3 19:05」. */
export function clockLabel(value: string | number | null, now: number) {
  const date = toDate(value);
  if (!date) return '';
  const time = date.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
  return date.toDateString() === new Date(now).toDateString() ? time : `${date.getMonth() + 1}/${date.getDate()} ${time}`;
}

export function fullDateTime(value: string | null | undefined) {
  const date = toDate(value);
  return date ? date.toLocaleString('ja-JP') : '';
}

export function percent(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}
