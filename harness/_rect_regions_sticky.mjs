// 390px で地域比較の表を右端まで横スクロールしたとき、行見出しの列が見えたままかを測る。
// 撮影ではなく矩形と elementFromPoint で確かめる(HC-194)。
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
await page.goto(base + '/regions/', { waitUntil: 'domcontentloaded' });
await page.waitForSelector('.region-table', { timeout: 20000 });
const result = await page.evaluate(async () => {
  const scroller = document.querySelector('.region-compare .table-scroll');
  const row = [...document.querySelectorAll('.region-table tbody tr')].find((tr) => !tr.classList.contains('group'));
  const th = row.querySelector('th');
  row.scrollIntoView({ block: 'center' });
  const before = th.getBoundingClientRect();
  scroller.scrollLeft = scroller.scrollWidth;          // 右端まで
  await new Promise((r) => setTimeout(r, 100));
  const after = th.getBoundingClientRect();
  const s = scroller.getBoundingClientRect();
  const hit = document.elementFromPoint(after.left + 4, after.top + after.height / 2);
  return {
    scrolledBy: Math.round(scroller.scrollLeft),
    labelLeftBefore: Math.round(before.left),
    labelLeftAfter: Math.round(after.left),
    scrollerLeft: Math.round(s.left),
    labelStillInView: after.left >= s.left - 0.5 && after.right <= s.right + 0.5,
    topmostIsLabel: hit === th || th.contains(hit),
    text: th.textContent,
  };
});
console.log(JSON.stringify(result));
await browser.close();
server.close();
process.exitCode = result.labelStillInView && result.topmostIsLabel && result.scrolledBy > 0 ? 0 : 1;
