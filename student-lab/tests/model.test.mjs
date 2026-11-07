import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const script = html.match(/<script id="lab-model">([\s\S]*?)<\/script>/)?.[1];
assert.ok(script, 'index.html embeds the calculation model');
const loadModel = source => runInNewContext(`${source}\nLabModel`);
const lab = loadModel(script);
const all = [true, true, true, true];
const initial = Array.from(lab.APS, ap => ap.initial);
const plain = value => JSON.parse(JSON.stringify(value));

const near = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-10, `${actual} ≈ ${expected}`);

test('A picks the largest signed RSSI, and abstains on a tie or no readings', () => {
  assert.equal(lab.strongest(initial).area, '理科室');
  assert.equal(lab.strongest([-56, -44, -73, -80]).area, '図書室');
  assert.equal(lab.strongest([-56, -56, -73, -80]).area, null);
  assert.equal(lab.strongest(initial, [false, false, false, false]).area, null);
});

test('B computes an even median and the population standard deviation after an outlier', () => {
  const before = lab.statistics(lab.START_VALUES);
  near(before.mean, -62.4);
  assert.equal(before.median, -62);
  near(before.variance, 1.04);
  near(before.sd, Math.sqrt(1.04));
  const after = lab.statistics([...lab.START_VALUES, lab.OUTLIER]);
  assert.equal(after.count, 6);
  near(after.mean, -337 / 6);
  assert.equal(after.median, -62);
  assert.ok(after.sd > before.sd);
  assert.equal(lab.statistics([-60, -70]).median, -65);
});

test('B accepts blank lines and decimal dBm but rejects malformed and excessive values', () => {
  assert.deepEqual(plain(lab.parseReadings('\n−62.5\n-61\r\n')), [-62.5, -61]);
  assert.throws(() => lab.parseReadings('-62\n-1e2'), /2行目/);
  assert.throws(() => lab.parseReadings('-121'), /1行目/);
  assert.throws(() => lab.parseReadings(''), /1つ以上/);
  assert.throws(() => lab.parseReadings('-60\n'.repeat(13)), /12件まで/);
});

test('C resets to the same seeded sample and accepts zero as a non-constant seed', () => {
  const first = lab.measurements('outlier', lab.DEFAULT_SEED);
  assert.deepEqual(lab.measurements('outlier', lab.DEFAULT_SEED), first);
  assert.notDeepEqual(lab.measurements('outlier', 2027), first);
  assert.equal(lab.parseSeed('0'), 0);
  assert.notDeepEqual(lab.measurements('calm', 0)[0], lab.measurements('calm', 0)[1]);
  assert.throws(() => lab.parseSeed('-1'), /整数/);
  assert.throws(() => lab.parseSeed('4294967296'), /整数/);
});

test('C can get a better result with fewer APs without changing any samples', () => {
  const rows = lab.measurements('outlier', 2026);
  const original = plain(rows);
  assert.equal(lab.estimate('fingerprint', rows, all).area, '図書室');
  assert.equal(lab.estimate('fingerprint', rows, [true, false, true, true]).area, '理科室');
  assert.deepEqual(plain(rows), original);
  const result = lab.estimate('fingerprint', rows, [true, false, false, false]);
  assert.equal(result.area, null);
  assert.match(result.detail, /共通APが2台未満/);
});

test('fingerprint distances use only enabled received APs and abstain on ambiguity or distance', () => {
  const input = [-52, -41, -74, -80];
  const score = lab.fingerprint(input, [true, false, true, true]).scores.find(x => x.area === '理科室');
  near(score.distance, Math.sqrt((4 + 4 + 1) / 3));
  const tied = lab.fingerprint([-55.5, -60, -69, -80], all);
  assert.equal(tied.area, null);
  assert.match(tied.detail, /次点との差/);
  const distant = lab.fingerprint([-20, -20, -20, -20], all);
  assert.equal(distant.area, null);
  assert.match(distant.detail, /18 dB/);
});

test('D compares methods on identical rows and averages only received values per AP', () => {
  const rows = lab.measurements('outlier', 2026);
  assert.deepEqual(['strongest', 'mean', 'fingerprint'].map(method => lab.estimate(method, rows, all).area),
    ['図書室', '理科室', '図書室']);
  assert.deepEqual(plain(lab.meanByAp([[-50, null, -70, null], [-60, -64, -80, null]])), [-55, -64, -75, null]);
  assert.equal(lab.measurements('missing', 2026)[4][3], null);
});

test('E applies two changed numeric conditions and rejects arbitrary pasted code', () => {
  const readings = lab.readingsFor(initial);
  assert.equal(lab.estimateExerciseArea(readings, lab.exerciseSettings(lab.EXERCISE_SOURCE)), '理科室');
  const moreStrict = lab.EXERCISE_SOURCE.replace('MIN_RSSI = -72', 'MIN_RSSI = -50');
  assert.equal(lab.estimateExerciseArea(readings, lab.exerciseSettings(moreStrict)), null);
  const largerGap = lab.EXERCISE_SOURCE.replace('MIN_GAP = 4', 'MIN_GAP = 10');
  assert.equal(lab.estimateExerciseArea(readings, lab.exerciseSettings(largerGap)), null);
  assert.throws(() => lab.exerciseSettings(lab.EXERCISE_SOURCE.replace('return first.area;', 'return "変更";')), /数値だけ/);
  assert.throws(() => lab.exerciseSettings(lab.EXERCISE_SOURCE.replace('MIN_GAP = 4', 'MIN_GAP = -1')), /0〜120/);
});

test('E source edit changes the loaded model, and the restore example matches the original', () => {
  const changed = loadModel(script.replace('const MIN_RSSI = -72;', 'const MIN_RSSI = -50;'));
  assert.equal(changed.estimateExerciseArea(changed.readingsFor(initial)), null);
  assert.equal(changed.exerciseSettings(changed.EXERCISE_SOURCE).minRssi, -50);
  const example = readFileSync(new URL('../examples/choose-area.js', import.meta.url), 'utf8');
  const restore = runInNewContext(`${example}\nestimateExerciseArea`);
  assert.equal(restore(lab.readingsFor(initial)), '理科室');
  const lines = source => source.split('\n').map(line => line.trim());
  assert.deepEqual(lines(restore.toString()), lines(lab.EXERCISE_SOURCE));
});

test('E accepts a Windows CRLF source and pasted CRLF conditions', () => {
  const windowsModel = loadModel(script.replace(/\r?\n/g, '\r\n'));
  const input = windowsModel.EXERCISE_SOURCE.replace('MIN_RSSI = -72', 'MIN_RSSI = -50').replace(/\n/g, '\r\n');
  const settings = windowsModel.exerciseSettings(input);
  assert.equal(settings.minRssi, -50);
  assert.equal(windowsModel.estimateExerciseArea(windowsModel.readingsFor(initial), settings), null);
});

test('CSV records protect quoted notes and formula-like text', () => {
  const output = lab.csv([[1, '=1+1', '比較 "AP A",\nAP B']]);
  assert.match(output, /"シード"/);
  assert.ok(output.includes(`"1","'=1+1","比較 ""AP A"",\nAP B"`));
});
