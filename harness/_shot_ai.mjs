// AI の結果ページを撮り、横のはみ出しを測る。1280px と 390px。
import { chromium } from 'playwright';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join } from 'node:path';

const T = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.geojson': 'application/json', '.csv': 'text/csv', '.png': 'image/png', '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon', '.txt': 'text/plain' };
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
  await page.goto(base + '/ai/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.ai-table');
  const fit = await page.evaluate(() => ({
    pageOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
    tables: [...document.querySelectorAll('main .table-scroll')].map((s) => {
      const t = s.querySelector('table');
      return { box: s.clientWidth, table: t.scrollWidth, scrollsInside: t.scrollWidth > s.clientWidth };
    }),
    csvLinked: !!document.querySelector('a[href="/data/ai/dataset.csv"]'),
  }));
  console.log(`${w}px:`, JSON.stringify(fit));
  // ページの上部(免責・問い・合否・比較表)を撮る。全ページ撮影は固定フッタを焼き込むので避ける
  await page.screenshot({ path: `harness/shots/ai_${w}.png`, clip: { x: 0, y: 0, width: w, height: Math.min(2200, await page.evaluate(() => document.documentElement.scrollHeight)) }, fullPage: true });
  await page.close();
}
// CSV が配られていること
const r = await fetch(base + '/data/ai/dataset.csv');
const text = await r.text();
console.log('dataset.csv:', r.status, text.split('\n').length - 1, '行(ヘッダ込み・末尾改行で +1)');
await browser.close();
server.close();
