// 重なった点の選択肢(SPEC F-21)を撮り、パネルに収まっているかを測る。1280px と 390px。
// P12 と他の層が重なる位置を探して押す。
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
  await page.goto(base + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.maplibregl-canvas');
  await page.waitForFunction(() => (window.__map?.queryRenderedFeatures({ layers: ['onsen'] }) ?? []).length > 0, null, { timeout: 30000 });
  await page.waitForTimeout(1500);
  const found = await page.evaluate(() => {
    const m = window.__map;
    const layers = ['onsen', 'onsen-wd', 'onsen-fac', 'onsen-wp'].filter((id) => m.getLayer(id));
    for (const f of m.queryRenderedFeatures({ layers: ['onsen'] })) {
      const p = m.project(f.geometry.coordinates);
      const hits = m.queryRenderedFeatures(p, { layers });
      if (hits.length >= 2 && hits.some((x) => x.layer.id !== 'onsen')) {
        const r = m.getCanvas().getBoundingClientRect();
        m.getCanvas().dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: p.x + r.left, clientY: p.y + r.top }));
        return { name: f.properties.name, hits: hits.length };
      }
    }
    return null;
  });
  if (!found) { console.log(`${w}px: 重なった点が見つからない`); await page.close(); continue; }
  await page.waitForSelector('.feature-panel .point-chooser li', { timeout: 10000 });
  const fit = await page.evaluate(() => {
    const panel = document.querySelector('.feature-panel');
    const items = [...document.querySelectorAll('.point-chooser li')].map((li) => {
      const b = li.querySelector('button');
      return { text: li.innerText.replace(/\s+/g, ' '), overflow: b.scrollWidth > b.clientWidth + 1 };
    });
    return { panel: panel.clientWidth, overflowX: panel.scrollWidth > panel.clientWidth + 1, items };
  });
  console.log(`${w}px: 押した点 ${found.name}(画素 1 点の問い合わせで ${found.hits} 件)`, JSON.stringify(fit));
  await page.locator('.feature-panel .point-chooser').screenshot({ path: `harness/shots/chooser_${w}.png` });
  await page.close();
}
await browser.close();
server.close();
