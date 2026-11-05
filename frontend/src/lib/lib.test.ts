import { describe, expect, it } from 'vitest';
import type { Teacher } from '../api';
import { clockLabel, relativeTime } from './format';
import { matchesName, searchKey } from './search';
import { MAX_AGE_MS, reasonLabel, withFreshness } from './teachers';

describe('searchKey', () => {
  it('unifies width, spaces, katakana and the 先生 suffix', () => {
    expect(searchKey('ﾀｶﾊｼ　ミドリ先生')).toBe('たかはしみどり');
    expect(searchKey('Ａｏｋｉ せんせい')).toBe('aoki');
    expect(searchKey('  ')).toBe('');
  });

  it('matches a name or a reading', () => {
    const teacher = { name: '高橋 みどり', kana: 'たかはし みどり' };
    expect(matchesName(teacher, 'タカハシ')).toBe(true);
    expect(matchesName(teacher, '高橋先生')).toBe(true);
    expect(matchesName(teacher, 'すずき')).toBe(false);
    expect(matchesName({ name: '鈴木 りく' }, '')).toBe(true);
  });
});

describe('time labels', () => {
  const now = new Date(2026, 10, 4, 19, 5).getTime();

  it('describes how long ago a measurement was taken', () => {
    expect(relativeTime(new Date(now - 30_000).toISOString(), now)).toBe('1分以内');
    expect(relativeTime(new Date(now + 3_000).toISOString(), now)).toBe('1分以内');
    expect(relativeTime(new Date(now - 12 * 60_000).toISOString(), now)).toBe('12分前');
    expect(relativeTime(new Date(now - 3 * 3_600_000).toISOString(), now)).toBe('3時間前');
    expect(relativeTime('not a date', now)).toBe('');
    expect(relativeTime(null, now)).toBe('');
  });

  it('adds the date only for other days', () => {
    expect(clockLabel(new Date(2026, 10, 4, 9, 30).getTime(), now)).toBe('09:30');
    expect(clockLabel(new Date(2026, 10, 3, 9, 30).getTime(), now)).toBe('11/3 09:30');
    expect(clockLabel(null, now)).toBe('');
  });
});

describe('withFreshness', () => {
  const now = Date.parse('2026-11-04T09:10:00Z');
  const located: Teacher = { id: '1', name: '星野 あかり', subject: '情報', status: 'located', area: '2F-east', updated_at: '2026-11-04T09:09:00Z', reason: 'ok' };

  it('keeps a fresh area and hides an expired one', () => {
    expect(withFreshness(located, now)).toBe(located);
    const expired = withFreshness({ ...located, updated_at: new Date(now - MAX_AGE_MS).toISOString() }, now);
    expect(expired).toMatchObject({ status: 'unknown', area: null, reason: 'stale' });
  });

  it('hides a measurement from the future and one without a time', () => {
    expect(withFreshness({ ...located, updated_at: new Date(now + 6_000).toISOString() }, now).reason).toBe('future_measurement');
    expect(withFreshness({ ...located, updated_at: null }, now).status).toBe('unknown');
  });

  it('labels unknown reasons in plain Japanese', () => {
    expect(reasonLabel('stale')).toBe('測定から3分以上たっています');
    expect(reasonLabel('something-new')).toBe('場所を判定できませんでした');
  });
});
