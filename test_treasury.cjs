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
    assert.equal(await page.locator('.weekly-rank').count(), 0);
    assert.equal(await page.locator('.metric.weekly').count(), 4);
    assert.equal(await page.locator('.metric.four').count(), 4);
    const tones = await page.locator('.groups > section').evaluateAll(groups =>
      groups.map(group => getComputedStyle(group).backgroundColor));
    assert.equal(tones.length, 2);
    assert.notEqual(tones[0], tones[1]);
    assert.equal(await page.locator('.deposit-reference').count(), 2);
    assert.equal(await page.locator('.deposit-split[open]').count(), 0);
    for (const [i, column] of ['TP', 'YP'].entries()) {
      const entry = snapshot.depositContext[column];
      assert.equal(entry.dates[1], snapshot.latest);
      assert.ok(['total', 'demand', 'term'].every(key => entry[key]?.every(v => typeof v === 'number')));
      const reference = await page.locator('.deposit-reference').nth(i).textContent();
      const pct = 100 * (entry.total[1] - entry.total[0]) / entry.total[0];
      const formatted = new Intl.NumberFormat('tr-TR', {minimumFractionDigits: 2, maximumFractionDigits: 2}).format(Math.abs(pct));
      assert.match(reference, /Sektör toplam mevduatı/);
      assert.ok(reference.includes('%' + formatted));
      const details = page.locator('.deposit-split').nth(i);
      await details.locator('summary').click();
      assert.equal(await details.locator('dd').count(), 2);
      assert.match(await details.locator('dd').first().textContent(), /milyar TL/);
      await details.locator('summary').click();
    }
    const cardsBefore = await page.locator('.metrics').allTextContents();
    assert.ok(before.every(text => text.includes('milyar TL')));
    const positions = await page.locator('.card').evaluateAll(cards =>
      cards.map(card => ({ x: card.offsetLeft, y: card.getBoundingClientRect().top })));
    assert.equal(positions[0].y, positions[1].y);
    assert.equal(positions[2].y, positions[3].y);
    assert.ok(positions[2].y > positions[0].y);
    assert.equal(positions[0].x, positions[2].x);
    assert.equal(positions[1].x, positions[3].x);
    const range = page.getByLabel('Grafik dönemi');
    assert.equal(await range.inputValue(), '13');
    const first = page.locator('.card').first();
    const slider = first.getByRole('slider');
    assert.equal(await slider.getAttribute('max'), '13');
    assert.equal(await page.locator('.tip:visible').count(), 0);
    await range.selectOption('4');
    assert.equal(await slider.getAttribute('max'), '4');
    await range.selectOption('26');
    assert.equal(await slider.getAttribute('max'), '26');
    await range.selectOption('52');
    assert.equal(await slider.getAttribute('max'), '52');
    assert.deepEqual(await values.allTextContents(), before);
    assert.deepEqual(await page.locator('.metrics').allTextContents(), cardsBefore);
    await slider.focus();
    const lastDate = await slider.getAttribute('aria-valuetext');
    await slider.press('ArrowLeft');
    assert.notEqual(await slider.getAttribute('aria-valuetext'), lastDate);
    assert.ok(await first.locator('.tip').isVisible());
    assert.match(await first.locator('.tip').textContent(), /milyon TL/);
    await slider.press('Escape');
    assert.equal(await page.locator('.tip:visible').count(), 0);
    await page.locator('h1').click();
    await first.locator('svg').hover();
    assert.ok(await first.locator('.tip').isVisible());
    await page.locator('h1').hover();
    assert.equal(await page.locator('.tip:visible').count(), 0);
    await page.getByRole('button', { name: 'Karşılaştır', exact: true }).click();
    const compare = page.locator('#comparison-chart');
    assert.match(await compare.textContent(), /Endeks/);
    assert.match(await compare.locator('.trend-summary').textContent(), /%/);
    assert.ok(await compare.locator('.tip').isHidden());
    await compare.getByRole('slider').focus();
    assert.match(await compare.locator('.tip').textContent(), /milyon TL.*milyon TL/s);
    await range.selectOption('custom');
    await page.getByLabel('Başlangıç', { exact: true }).fill('2025-12-26');
    await page.getByLabel('Bitiş', { exact: true }).fill('2026-01-02');
    await page.getByRole('button', { name: 'Uygula' }).click();
    assert.equal(await slider.getAttribute('max'), '1');
    assert.match(await first.locator('.range-summary').textContent(), /26 Ara 2025.*2 Oca 2026/);
    assert.match(await compare.locator('.trend-summary').textContent(), /26 Ara 2025.*2 Oca 2026/);
    await range.selectOption('all');
    assert.ok(await page.locator('#custom-dates').isHidden());
    await page.setViewportSize({ width: 390, height: 850 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), 390);
    await page.setViewportSize({ width: 1360, height: 850 });
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
    snapshot.depositContext = {};
    snapshot.error = 'Kontrollü kaynak bağlantısı hatası';
    await page.goto('about:blank');
    await page.setContent(html.replace(/(<script type="application\/json" id="snapshot">).*?(<\/script>)/s,
      (_, start, end) => start + JSON.stringify(snapshot).replace(/</g, '\\u003c') + end));
    assert.match(await page.locator('#notice').textContent(), /Son doğrulanmış veri/);
    assert.match(await page.locator('.card .metrics').first().textContent(), /gözlemi eksik/);
    assert.match(await page.locator('.deposit-reference').first().textContent(), /Bu hafta veri alınamadı/);
    assert.equal(await page.locator('.card').count(), 4);
    assert.deepEqual(errors, []);
    console.log('Dört kart, tarih aralıkları, klavye, bilgi kutusu ve endeks karşılaştırması doğrulandı.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
