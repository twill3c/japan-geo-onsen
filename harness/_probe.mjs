/**
 * 地図面を普通のスクリーンショットで確かめる。
 *
 * Map は preserveDrawingBuffer:true で作っているので WebGL 面も写る。
 * 併せて「等高線がどれだけ描かれているか」を色で数える(目視は当てにしない)。
 *
 *   node harness/_probe.mjs [出力先.png]
 */
import { chromium } from 'playwright';
import { createServer } from 'node:http';
import { readFile, stat, mkdir } from 'node:fs/promises';
import { extname, join, resolve } from 'node:path';

const MIME = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css',
  '.json': 'application/json', '.geojson': 'application/json', '.png': 'image/png',
  '.svg': 'image/svg+xml', '.ico': 'image/x-icon',
};
const out = process.argv[2] ?? 'harness/shots/map-live.png';
const root = resolve('out');
const server = createServer(async (req, res) => {
  try {
    let p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
    if (p.endsWith('/')) p += 'index.html';
    let f = join(root, p);
    try { if ((await stat(f)).isDirectory()) f = join(f, 'index.html'); }
    catch { if (!extname(f)) f = `${f}.html`; }
    const b = await readFile(f);
    res.writeHead(200, { 'content-type': MIME[extname(f)] ?? 'application/octet-stream' });
    res.end(b);
  } catch { res.writeHead(404); res.end('x'); }
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${server.address().port}`;

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto(`${base}/`, { waitUntil: 'networkidle' });
await page.waitForSelector('.maplibregl-canvas');
await page.getByText('標高タイルから引く').click();
await page.waitForFunction(() => /本 \/ 標高タイル/.test(document.body.innerText), null, { timeout: 40000 });
await page.waitForFunction(() => window.__map?.areTilesLoaded?.() === true, null, { timeout: 90000 });
await page.waitForTimeout(2500);

const state = await page.evaluate(() => {
  const m = window.__map;
  return {
    contourLayer: m.getLayoutProperty('contours', 'visibility'),
    contourRendered: m.queryRenderedFeatures({ layers: ['contours'] }).length,
    note: document.querySelector('.layer-panel .status')?.innerText ?? '(なし)',
  };
});
console.log(JSON.stringify(state, null, 1));

await mkdir('harness/shots', { recursive: true });
await page.locator('.map-area').screenshot({ path: out });
console.log(`${out} を書いた`);

await browser.close();
server.close();
