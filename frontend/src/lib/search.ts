/**
 * Turns a name, reading or search word into a comparable form:
 * full-width/half-width unified (NFKC), spaces removed, katakana as hiragana,
 * and a trailing 「先生」 dropped. The backend uses the same rules.
 */
export function searchKey(value: string) {
  return value
    .normalize('NFKC')
    .toLocaleLowerCase('ja')
    .replace(/\s+/g, '')
    .replace(/[ァ-ヶ]/g, c => String.fromCharCode(c.charCodeAt(0) - 0x60))
    .replace(/先生$/, '')
    .replace(/せんせい$/, '');
}

export function matchesName(teacher: { name: string; kana?: string }, query: string) {
  const key = searchKey(query);
  return !key || searchKey(teacher.name).includes(key) || searchKey(teacher.kana ?? '').includes(key);
}
