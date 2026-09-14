// 地域比較(設計書 §58)の表を撮り、横のはみ出しを測る。1280px と 390px。
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
  await page.goto(base + '/regions/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.region-table', { timeout: 20000 });
  const fit = await page.evaluate(() => {
    const scroller = document.querySelector('.region-compare .table-scroll');
    const t = document.querySelector('.region-table');
    return {
      pageOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
      scroller: scroller.clientWidth,
      table: t.scrollWidth,
      tableScrollsInside: t.scrollWidth > scroller.clientWidth,
    };
  });
  console.log(`${w}px:`, JSON.stringify(fit));
  await page.locator('.region-compare').screenshot({ path: `harness/shots/regions_${w}.png` });
  await page.close();
}
await browser.close();
server.close();
