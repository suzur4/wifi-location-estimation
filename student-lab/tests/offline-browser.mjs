// Developer-only regression check. Students open ../index.html without these tools.
// PLAYWRIGHT_MODULE may point to an installed playwright/index.mjs outside the handout.
import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const modulePath = process.env.PLAYWRIGHT_MODULE;
const { chromium } = await import(modulePath ? pathToFileURL(resolve(modulePath)).href : 'playwright');
const browser = await chromium.launch({
  headless: true,
  ...(process.env.CHROMIUM_EXECUTABLE ? { executablePath: process.env.CHROMIUM_EXECUTABLE } : {}),
});
const screenshots = process.env.LAB_SCREENSHOTS;
if (screenshots) await mkdir(screenshots, { recursive: true });
try {
  const context = await browser.newContext({ offline: true, locale: 'ja-JP', acceptDownloads: true });
  const page = await context.newPage();
  const remoteRequests = [];
  const errors = [];
  page.on('request', request => { if (/^https?:/.test(request.url())) remoteRequests.push(request.url()); });
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(new URL('../index.html', import.meta.url).href);
  assert.match(await page.title(), /Wi-Fi位置推定/);
  assert.equal(await page.locator('html').getAttribute('lang'), 'ja');
  const tab = async id => {
    await page.locator(`nav a[href="#experiment-${id}"]`).click();
    await page.locator(`#experiment-${id}`).waitFor({ state: 'visible' });
  };

  const initialA = await page.locator('#a-result').innerText();
  await page.locator('#a-rssi-B').focus();
  await page.locator('#a-rssi-B').press('End');
  assert.notEqual(await page.locator('#a-result').innerText(), initialA);
  assert.match(await page.locator('#a-result').innerText(), /AP B/);
  await page.locator('#a-reset').click();
  assert.equal(await page.locator('#a-result').innerText(), initialA);
  if (screenshots) await page.screenshot({ path: resolve(screenshots, 'lab-desktop.png'), fullPage: true });

  await tab('b');
  await page.locator('#b-values').fill('-62\n-61\n-60\n-59\n-58');
  let values = await page.locator('#b-stats dd').allTextContents();
  assert(values.filter(value => /−60|-60/.test(value)).length >= 2, values.join(','));
  await page.locator('#b-values').fill('-62\n-61\n-60\n-59\n-58\n-90');
  values = await page.locator('#b-stats dd').allTextContents();
  assert(values.some(value => /−65|-65/.test(value)));
  assert(values.some(value => /−60\.5|-60\.5/.test(value)));
  await page.locator('#b-values').fill('abc');
  assert(await page.locator('#b-error').isVisible());
  assert.equal(await page.locator('#b-stats dd').count(), 0);
  await page.locator('#b-reset').click();
  assert.equal(await page.locator('#b-error').isVisible(), false);

  await tab('c');
  const initialTable = await page.locator('#c-table tbody').innerText();
  const initialC = await page.locator('#c-result').innerText();
  const checks = page.locator('#c-aps input');
  await checks.nth(1).uncheck();
  assert.notEqual(await page.locator('#c-result').innerText(), initialC);
  for (const checkbox of await checks.all()) await checkbox.uncheck();
  assert.match(await page.locator('#c-result').innerText(), /保留/);
  await page.locator('#c-reset').click();
  assert.equal(await page.locator('#c-table tbody').innerText(), initialTable);
  assert.equal(await page.locator('#c-result').innerText(), initialC);
  await page.locator('#c-hypothesis').fill('APを減らすと結果は変わる？');
  await page.locator('#c-note').fill('模擬条件2026の結果。');
  await page.locator('#c-record').click();
  const csv = await page.locator('#c-csv').inputValue();
  assert.match(csv, /APを減らすと結果は変わる/);
  const downloadPromise = page.waitForEvent('download');
  await page.locator('#c-save').click();
  const download = await downloadPromise;
  const saved = await readFile(await download.path(), 'utf8');
  assert.equal(saved.replace(/^\uFEFF/, '').replace(/\r\n/g, '\n'), csv);
  await page.locator('#c-seed').fill('12.5');
  await page.locator('#c-reset').click();
  assert(await page.locator('#c-error').isVisible());
  assert.equal(await page.locator('#c-table tbody').innerText(), initialTable);
  await page.locator('#c-seed').fill('2026');
  await page.locator('#c-reset').click();

  await tab('d');
  const strongest = await page.locator('#d-result').innerText();
  await page.locator('input[name="method"][value="mean"]').check();
  assert.notEqual(await page.locator('#d-result').innerText(), strongest);
  await page.locator('input[name="method"][value="fingerprint"]').check();
  assert.equal(await page.locator('#d-result').innerText(), initialC);

  await tab('e');
  const originalCode = await page.locator('#e-code').inputValue();
  await page.locator('#e-run').click();
  const originalResult = await page.locator('#e-result').innerText();
  const editedCode = originalCode.replace(/const MIN_RSSI = -?\d+(?:\.\d+)?;/, 'const MIN_RSSI = -30;');
  assert.notEqual(editedCode, originalCode);
  await page.locator('#e-code').fill(editedCode);
  await page.locator('#e-run').click();
  assert.notEqual(await page.locator('#e-result').innerText(), originalResult);
  assert.match(await page.locator('#e-result').innerText(), /保留/);
  await page.locator('#e-reset').click();
  assert.equal(await page.locator('#e-code').inputValue(), originalCode);

  await page.setViewportSize({ width: 375, height: 812 });
  for (const id of ['a', 'b', 'c', 'd', 'e']) {
    await tab(id);
    assert(await page.locator(`#experiment-${id}`).isVisible());
    const width = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth }));
    assert(width.document <= width.viewport + 1, `${id}: horizontal page overflow ${JSON.stringify(width)}`);
  }
  await tab('a');
  if (screenshots) await page.screenshot({ path: resolve(screenshots, 'lab-mobile.png'), fullPage: true });
  await page.goto(new URL('../materials.html', import.meta.url).href);
  assert.match(await page.locator('body').innerText(), /ワークシート/);
  assert.match(await page.locator('body').innerText(), /有限オートマトン/);
  assert.equal(await page.locator('html').getAttribute('lang'), 'ja');
  if (screenshots) await page.screenshot({ path: resolve(screenshots, 'materials-mobile.png'), fullPage: true });
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'materials fit a narrow screen');
  await page.locator('#print-material').selectOption('worksheets');
  await page.emulateMedia({ media: 'print' });
  assert.equal(await page.locator('article.material:visible').count(), 3);
  await page.emulateMedia({ media: 'screen' });
  await page.locator('#print-material').selectOption('reflection');
  await page.emulateMedia({ media: 'print' });
  assert.equal(await page.locator('article.material:visible').count(), 1);
  assert(await page.locator('#reflection').isVisible());
  if (screenshots) {
    await page.setViewportSize({ width: 794, height: 1123 });
    await page.screenshot({ path: resolve(screenshots, 'reflection-print.png'), fullPage: true });
  }
  await page.emulateMedia({ media: 'screen' });
  await page.locator('#print-material').selectOption('exercise');
  await page.emulateMedia({ media: 'print' });
  assert.equal(await page.locator('article.material:visible').count(), 1);
  assert.match(await page.locator('article.material:visible').innerText(), /estimateExerciseArea/);
  if (screenshots) await page.screenshot({ path: resolve(screenshots, 'exercise-print.png'), fullPage: true });
  assert.deepEqual(remoteRequests, [], 'the offline handout must never request HTTP resources');
  assert.deepEqual(errors, [], 'browser execution and CSP errors');
  console.log(JSON.stringify({ browser: browser.version(), offline: true, fileProtocol: true,
    tested: ['A–E', 'CSV download', 'reset and seed', 'invalid input', '375px layout', 'Japanese materials'],
    remoteRequests: remoteRequests.length, windowsTested: process.platform === 'win32' }));
} finally {
  await browser.close();
}
