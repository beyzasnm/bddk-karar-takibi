const assert = require('node:assert/strict');
const fs = require('node:fs');
const { pathToFileURL } = require('node:url');
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1360, height: 850 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const output = 'dist/treasury/index.html';
  try {
    await page.goto(pathToFileURL(fs.realpathSync(output)).href);
    const snapshot = JSON.parse(await page.locator('#snapshot').textContent());
    assert.equal(snapshot.series.length, 4);
    const values = page.locator('.card .value');
    const before = await values.allTextContents();
    assert.equal(before.length, 4);
    assert.ok(before.every(text => text.includes('→') && !text.includes('—')));
    const cardsBefore = await page.locator('.metrics').allTextContents();
    await page.getByRole('button', { name: '52 hafta' }).click();
    assert.deepEqual(await values.allTextContents(), before);
    assert.deepEqual(await page.locator('.metrics').allTextContents(), cardsBefore);
    const first = page.locator('.card').first();
    const slider = first.getByRole('slider');
    await slider.focus();
    const lastDate = await slider.getAttribute('aria-valuetext');
    await slider.press('ArrowLeft');
    assert.notEqual(await slider.getAttribute('aria-valuetext'), lastDate);
    assert.match(await first.locator('.tip').textContent(), /milyon TL/);
    await page.getByRole('button', { name: 'Karşılaştır', exact: true }).click();
    const compare = page.locator('#comparison-chart');
    assert.match(await compare.textContent(), /Endeks/);
    assert.match(await compare.locator('.tip').textContent(), /milyon TL.*milyon TL/s);
    await page.getByRole('button', { name: 'Tüm geçmiş' }).click();
    assert.deepEqual(await values.allTextContents(), before);
    assert.deepEqual(await page.locator('.metrics').allTextContents(), cardsBefore);
    assert.ok(snapshot.periods.includes('2025-12-26') && snapshot.periods.includes('2026-01-02'));
    for (const series of snapshot.series) {
      assert.equal(typeof snapshot.points[series.id]['2025-12-26'], 'number');
      assert.equal(typeof snapshot.points[series.id]['2026-01-02'], 'number');
    }
    const html = fs.readFileSync(output, 'utf8');
    const latest = new Date(snapshot.latest + 'T00:00:00Z');
    const weekday = (latest.getUTCDay() + 6) % 7;
    latest.setUTCDate(latest.getUTCDate() + 4 - weekday - 7);
    const previousWeek = latest.toISOString().slice(0,10);
    const previous = snapshot.periods.filter(d => d <= previousWeek && d > new Date(latest - 7 * 86400000).toISOString().slice(0,10)).at(-1);
    assert.ok(previous);
    snapshot.points[snapshot.series[0].id][previous] = null;
    snapshot.error = 'Kontrollü kaynak bağlantısı hatası';
    await page.goto('about:blank');
    await page.setContent(html.replace(/(<script type="application\/json" id="snapshot">).*?(<\/script>)/s,
      (_, start, end) => start + JSON.stringify(snapshot).replace(/</g, '\\u003c') + end));
    assert.match(await page.locator('#notice').textContent(), /Son doğrulanmış veri/);
    assert.match(await page.locator('.card .metrics').first().textContent(), /gözlemi eksik/);
    assert.deepEqual(errors, []);
    console.log('Dört kart, tarih aralıkları, klavye, bilgi kutusu ve endeks karşılaştırması doğrulandı.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
