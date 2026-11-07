// 実験Eの復元用。index.html の「実験E 編集ここから」で囲まれた関数と交換します。
function estimateExerciseArea(readings, overrides = {}) {
  // 変更1: 一番強いAPがこの値より弱い場合は保留。
  const MIN_RSSI = -72;
  // 変更2: 上位2台の差がこの値より小さい場合は保留。
  const MIN_GAP = 4;
  const ordered = [...readings].sort((a, b) => b.rssi - a.rssi);
  if (ordered.length < 2) return null;
  const [first, second] = ordered;
  if (first.rssi < (overrides.minRssi ?? MIN_RSSI)) return null;
  const gap = first.rssi - second.rssi;
  if (gap === 0 || gap < (overrides.minGap ?? MIN_GAP)) return null;
  return first.area;
}
