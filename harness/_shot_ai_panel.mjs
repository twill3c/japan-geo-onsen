// 温泉の詳細パネルの「AI の見立て」を撮り、パネル幅に収まっているかを測る。1280px と 390px。
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

const browser = await chromium.launch();
for (const [w, h] of [[1280, 900], [390, 844]]) {
  const page = await browser.newPage({ viewport: { width: w, height: h } });
  const asked = [];
  page.on('request', (r) => { if (r.url().includes('/data/ai/')) asked.push(r.url().split('/data/')[1]); });
  await page.goto(base + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.maplibregl-canvas');
  await page.waitForFunction(() => (window.__map?.queryRenderedFeatures({ layers: ['onsen'] }) ?? []).length > 0, null, { timeout: 30000 });
  const beforeClick = [...asked];
  await page.evaluate(() => {
    const m = window.__map;
    // 他の層と重なっていない P12 の点を選ぶ(重なっていると上の層の点が選ばれる)
    const layers = ['onsen', 'onsen-wd', 'onsen-fac', 'onsen-wp'].filter((id) => m.getLayer(id));
    const f = m.queryRenderedFeatures({ layers: ['onsen'] })
      .find((c) => m.queryRenderedFeatures(m.project(c.geometry.coordinates), { layers }).length === 1);
    const p = m.project(f.geometry.coordinates);
    const r = m.getCanvas().getBoundingClientRect();
    m.getCanvas().dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: p.x + r.left, clientY: p.y + r.top }));
  });
  await page.waitForSelector('.feature-panel .ai-explain .ai-contrib', { timeout: 20000 });
  await page.locator('.feature-panel .ai-explain').scrollIntoViewIfNeeded();
  const fit = await page.evaluate(() => {
    const panel = document.querySelector('.feature-panel');
    const box = document.querySelector('.feature-panel .ai-explain');
    return { panel: panel.clientWidth, box: box.scrollWidth, overflowX: panel.scrollWidth > panel.clientWidth + 1 };
  });
  console.log(`${w}px:`, JSON.stringify(fit), '/ 起動時に AI のデータを読んだか:', beforeClick.length > 0, '/ クリック後:', asked.join(','));
  await page.locator('.feature-panel .ai-explain').screenshot({ path: `harness/shots/ai_panel_${w}.png` });
  await page.close();
}
await browser.close();
server.close();
