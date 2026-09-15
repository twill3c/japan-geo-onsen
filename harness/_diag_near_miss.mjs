// 押し損ね(点のすぐ外)を押しても、その点が開くかを測る(SPEC F-21 / HC-290 の「押し損ねを許す範囲」)。
// 他の点から離れた P12 の点を選び、中心から (点の半径 + 3px) だけ右を押す。
// 期待: 詳細が開く(一覧は出ない・何も出ないのでもない)。
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

// 周り 25px に他の点が無い点を選ぶ(押し損ねの位置に別の点が来ないように)
const targets = await page.evaluate(() => {
  const m = window.__map;
  const layers = ['onsen', 'onsen-wd', 'onsen-fac', 'onsen-wp', 'volcano'].filter((id) => m.getLayer(id));
  const z = m.getZoom();
  const radius = z <= 5 ? 2.4 : z <= 10 ? 2.4 + ((z - 5) / 5) * 2.2 : 4.6 + ((z - 10) / 4) * 2.4;
  const out = [];
  for (const f of m.queryRenderedFeatures({ layers: ['onsen'] })) {
    const p = m.project(f.geometry.coordinates);
    const around = m.queryRenderedFeatures([[p.x - 25, p.y - 25], [p.x + 25, p.y + 25]], { layers });
    if (around.length !== 1) continue;
    out.push({ x: p.x + radius + 3, y: p.y, name: f.properties.name });
    if (out.length >= 20) break;
  }
  return out;
});

let detail = 0; let chooser = 0; let none = 0; let wrong = 0;
for (const t of targets) {
  await page.evaluate(({ x, y }) => {
    document.querySelector('.feature-panel .close')?.click();
    const c = window.__map.getCanvas();
    const r = c.getBoundingClientRect();
    c.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: x + r.left, clientY: y + r.top }));
  }, t);
  await page.waitForTimeout(150);
  const r = await page.evaluate(() => {
    if (document.querySelector('.feature-panel .point-chooser')) return { kind: 'chooser' };
    const h = document.querySelector('.feature-panel h3');
    return h ? { kind: 'detail', title: h.textContent } : { kind: 'none' };
  });
  if (r.kind === 'detail') { detail++; if (!r.title.includes(t.name)) wrong++; }
  else if (r.kind === 'chooser') chooser++;
  else none++;
}
console.log(JSON.stringify({ pressedNearMiss: targets.length, detail, wrongPoint: wrong, chooser, none }));
await browser.close();
server.close();
process.exitCode = targets.length > 0 && detail === targets.length && wrong === 0 ? 0 : 1;
