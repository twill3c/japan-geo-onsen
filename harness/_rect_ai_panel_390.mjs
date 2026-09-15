// 390px で温泉詳細の「AI の見立て」の寄与の表が、パネルの枠の中で実際に見えるかを矩形で測る。
// 要素の撮影は、スクロールする枠の中だと切れて写る(HC-194)ので、撮影ではなく elementFromPoint で見る。
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
const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
await page.goto(base + '/', { waitUntil: 'domcontentloaded' });
await page.waitForSelector('.maplibregl-canvas');
await page.waitForFunction(() => (window.__map?.queryRenderedFeatures({ layers: ['onsen'] }) ?? []).length > 0, null, { timeout: 30000 });
await page.evaluate(() => {
  const m = window.__map;
  const layers = ['onsen', 'onsen-wd', 'onsen-fac', 'onsen-wp'].filter((id) => m.getLayer(id));
  const f = m.queryRenderedFeatures({ layers: ['onsen'] })
    .find((c) => m.queryRenderedFeatures(m.project(c.geometry.coordinates), { layers }).length === 1);
  const p = m.project(f.geometry.coordinates);
  const r = m.getCanvas().getBoundingClientRect();
  m.getCanvas().dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: p.x + r.left, clientY: p.y + r.top }));
});
await page.waitForSelector('.feature-panel .ai-explain .ai-contrib', { timeout: 20000 });
const m = await page.evaluate(() => {
  const panel = document.querySelector('.feature-panel');
  const table = document.querySelector('.feature-panel .ai-contrib');
  table.scrollIntoView({ block: 'center' });
  const pr = panel.getBoundingClientRect();
  const rows = [...table.querySelectorAll('tr')].map((tr) => {
    const r = tr.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return {
      inside: r.top >= pr.top - 0.5 && r.bottom <= pr.bottom + 0.5 && r.left >= pr.left - 0.5 && r.right <= pr.right + 0.5,
      topmostIsRow: !!hit && tr.contains(hit),
    };
  });
  return { panel: [Math.round(pr.top), Math.round(pr.bottom)], rows };
});
console.log(JSON.stringify(m));
await browser.close();
server.close();
process.exitCode = m.rows.length === 4 && m.rows.every((r) => r.inside && r.topmostIsRow) ? 0 : 1;
