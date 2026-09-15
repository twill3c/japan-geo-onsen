// 温泉の詳細に AI の見立てが出ない原因を切り分ける。
// クリックで選ばれた点の層と属性、パネルの「AI の見立て」節の文、/data/ai/ への要求を記録する。
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
const reqs = [];
page.on('response', (r) => { if (r.url().includes('/data/ai/')) reqs.push(`${r.status()} ${r.url().split('/data/')[1]}`); });
page.on('console', (m) => { if (m.type() === 'error') reqs.push(`console: ${m.text()}`); });
await page.goto(base + '/', { waitUntil: 'domcontentloaded' });
await page.waitForSelector('.maplibregl-canvas');
await page.waitForFunction(() => (window.__map?.queryRenderedFeatures({ layers: ['onsen'] }) ?? []).length > 0, null, { timeout: 30000 });
const clicked = await page.evaluate(() => {
  const m = window.__map;
  const f = m.queryRenderedFeatures({ layers: ['onsen'] })[0];
  const p = m.project(f.geometry.coordinates);
  const layers = ['onsen', 'onsen-wd', 'onsen-fac'].filter((id) => m.getLayer(id));
  const hits = m.queryRenderedFeatures(p, { layers: [...layers, 'volcano'] });
  const r = m.getCanvas().getBoundingClientRect();
  m.getCanvas().dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: p.x + r.left, clientY: p.y + r.top }));
  return {
    target: { name: f.properties.name, onsen_id: f.properties.onsen_id, provenance: f.properties.provenance ?? null },
    topHit: hits[0] ? { layer: hits[0].layer.id, name: hits[0].properties.name, provenance: hits[0].properties.provenance ?? null } : null,
    hitCount: hits.length,
  };
});
await page.waitForTimeout(4000);
const section = await page.evaluate(() => {
  const panel = document.querySelector('.feature-panel');
  if (!panel) return '(パネル無し)';
  const t = panel.innerText;
  const i = t.indexOf('AI の見立て');
  return i < 0 ? '(節が無い)' : t.slice(i, i + 300);
});
console.log('クリックした点:', JSON.stringify(clicked));
console.log('AI の節:', JSON.stringify(section));
console.log('要求:', reqs.join(' | ') || '(なし)');
await browser.close();
server.close();
