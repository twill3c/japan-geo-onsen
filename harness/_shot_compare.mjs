// 温泉比較(設計書 §57)のパネルを撮り、はみ出しを測る。1280px と 390px。
import { chromium } from 'playwright';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join } from 'node:path';

const T = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.geojson': 'application/json', '.png': 'image/png', '.svg': 'image/svg+xml', '.ico': 'image/x-icon', '.txt': 'text/plain' };
const server = createServer(async (req, res) => {
  try {
    let p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
    if (p.endsWith('/')) p += 'index.html';
    const b = await readFile(join('out', p));
    res.writeHead(200, { 'content-type': T[extname(p)] ?? 'application/octet-stream' });
    res.end(b);
  } catch { res.writeHead(404); res.end('x'); }
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${server.address().port}`;

const clickOnsen = (page, skipName) => page.evaluate((skip) => {
  const m = window.__map;
  const fs = m.queryRenderedFeatures({ layers: ['onsen'] });
  const f = fs.find((x) => x.properties?.name && x.properties.name !== skip);
  if (!f) return null;
  const p = m.project(f.geometry.coordinates);
  const r = m.getCanvas().getBoundingClientRect();
  m.getCanvas().dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: p.x + r.left, clientY: p.y + r.top }));
  return f.properties.name;
}, skipName);

const browser = await chromium.launch();
for (const [w, h] of [[1280, 900], [390, 844]]) {
  const page = await browser.newPage({ viewport: { width: w, height: h } });
  await page.goto(base + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.maplibregl-canvas');
  await page.waitForFunction(() => (window.__map?.queryRenderedFeatures({ layers: ['onsen'] }) ?? []).length > 1, null, { timeout: 30000 });
  const a = await clickOnsen(page, null);
  await page.getByText('この温泉を別の温泉と比べる').click();
  await clickOnsen(page, a);
  await page.waitForSelector('.compare-panel .compare-table', { timeout: 20000 });
  await page.waitForTimeout(800);
  const fit = await page.evaluate(() => {
    const el = document.querySelector('.compare-panel');
    const t = el.querySelector('.compare-table');
    const overlaps = !!document.querySelector('.feature-panel:not(.compare-panel)');
    return { panel: el.clientWidth, table: t.scrollWidth, overflowX: el.scrollWidth > el.clientWidth + 1, detailPanelAlsoOpen: overlaps };
  });
  console.log(`${w}px:`, JSON.stringify(fit));
  await page.locator('.compare-panel').screenshot({ path: `harness/shots/compare_${w}.png` });
  await page.close();
}
await browser.close();
server.close();
