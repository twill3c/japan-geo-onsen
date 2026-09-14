// 390px でヘッダのナビのリンクが語の途中で折れていないかを矩形で測る。
// 1 行の高さを超えるリンク(= 中で折れたリンク)を数える。全ページで見る。
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
let bad = 0;
for (const path of ['/', '/stats/', '/onsen-stats/', '/regions/', '/missing/', '/ai/', '/about/']) {
  await page.goto(base + path, { waitUntil: 'domcontentloaded' });
  const r = await page.evaluate(() => {
    const links = [...document.querySelectorAll('.site-header nav a')];
    const lineH = Math.min(...links.map((a) => a.getBoundingClientRect().height));
    const broken = links.filter((a) => a.getClientRects().length > 1 || a.getBoundingClientRect().height > lineH * 1.5)
      .map((a) => a.textContent);
    return {
      links: links.length,
      broken,
      pageOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
    };
  });
  console.log(path, JSON.stringify(r));
  if (r.broken.length || r.pageOverflow) bad++;
}
await browser.close();
server.close();
process.exitCode = bad ? 1 : 0;
