// 「近くにあるだけの点」まで候補に入って、1 つの点を押しても一覧が出ていないかを測る。
// 他の層と重ならない P12 の点(画素 1 点の問い合わせで 1 件)の中心を押し、パネルが詳細か一覧かを数える。
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
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto(base + '/', { waitUntil: 'domcontentloaded' });
await page.waitForSelector('.maplibregl-canvas');
await page.waitForFunction(() => (window.__map?.queryRenderedFeatures({ layers: ['onsen'] }) ?? []).length > 0, null, { timeout: 30000 });
await page.waitForTimeout(1500);

const targets = await page.evaluate(() => {
  const m = window.__map;
  const layers = ['onsen', 'onsen-wd', 'onsen-fac', 'onsen-wp'].filter((id) => m.getLayer(id));
  return m.queryRenderedFeatures({ layers: ['onsen'] })
    .map((f) => ({ p: m.project(f.geometry.coordinates), name: f.properties.name }))
    .filter(({ p }) => m.queryRenderedFeatures(p, { layers }).length === 1)
    .slice(0, 40)
    .map(({ p, name }) => ({ x: p.x, y: p.y, name }));
});

let chooser = 0;
let detail = 0;
const examples = [];
for (const t of targets) {
  await page.evaluate(({ x, y }) => {
    document.querySelector('.feature-panel .close')?.click();
    const c = window.__map.getCanvas();
    const r = c.getBoundingClientRect();
    c.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: x + r.left, clientY: y + r.top }));
  }, t);
  await page.waitForTimeout(150);
  const kind = await page.evaluate(() => (document.querySelector('.feature-panel .point-chooser') ? 'chooser'
    : document.querySelector('.feature-panel h3') ? 'detail' : 'none'));
  if (kind === 'chooser') {
    chooser++;
    if (examples.length < 3) {
      examples.push({ clicked: t.name, items: await page.locator('.point-chooser li').allInnerTexts() });
    }
  } else if (kind === 'detail') detail++;
}
console.log(JSON.stringify({ zoom: await page.evaluate(() => window.__map.getZoom()), pressedIsolated: targets.length, chooser, detail, examples }));
await browser.close();
server.close();
