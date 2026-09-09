// 地形断面の図を実際に撮って目で確かめる(HC-041: 目で見なければ分からない性質は
// テストで代替しない)。out/ を配って地図を開き、線を引いて断面パネルを撮る。
import { chromium } from 'playwright';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join } from 'node:path';

const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css',
  '.json': 'application/json', '.geojson': 'application/json', '.png': 'image/png',
  '.svg': 'image/svg+xml', '.ico': 'image/x-icon', '.txt': 'text/plain' };

const root = 'out';
const server = createServer(async (req, res) => {
  try {
    let p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
    if (p.endsWith('/')) p += 'index.html';
    const body = await readFile(join(root, p));
    res.writeHead(200, { 'content-type': TYPES[extname(p)] ?? 'application/octet-stream' });
    res.end(body);
  } catch { res.writeHead(404); res.end('not found'); }
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${server.address().port}`;

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto(base + '/', { waitUntil: 'domcontentloaded' });
await page.waitForSelector('.maplibregl-canvas');
await page.waitForTimeout(3000);
await page.getByText('地図に線を引いて断面を見る').click();
await page.evaluate(async () => {
  const c = window.__map.getCanvas();
  const r = c.getBoundingClientRect();
  const at = (dx, dy) => c.dispatchEvent(new MouseEvent('click', {
    bubbles: true, clientX: r.left + r.width * dx, clientY: r.top + r.height * dy,
  }));
  at(0.3, 0.35);
  await new Promise((res) => setTimeout(res, 300));
  at(0.68, 0.62);
});
await page.waitForFunction(
  () => /全長 [\d.]+ km/.test(document.querySelector('.profile-panel')?.innerText ?? ''),
  null, { timeout: 40000 },
);
await page.waitForTimeout(600);

const out = process.argv[2] ?? 'harness/shots/profile.png';
await page.locator('.profile-panel').screenshot({ path: out });
await page.screenshot({ path: out.replace('.png', '_full.png') });
console.log('撮影:', out);

// 図が器からはみ出していないか(SVG の中身の外接矩形と viewBox を比べる)
const overflow = await page.evaluate(() => {
  const svg = document.querySelector('.profile-panel svg');
  if (!svg) return null;
  const vb = svg.viewBox.baseVal;
  const bb = svg.getBBox();
  return {
    viewBox: [vb.x, vb.y, vb.width, vb.height],
    bbox: [bb.x, bb.y, bb.width, bb.height],
    over: {
      left: +(vb.x - bb.x).toFixed(2),
      top: +(vb.y - bb.y).toFixed(2),
      right: +(bb.x + bb.width - (vb.x + vb.width)).toFixed(2),
      bottom: +(bb.y + bb.height - (vb.y + vb.height)).toFixed(2),
    },
  };
});
console.log('viewBox からのはみ出し:', JSON.stringify(overflow));

await browser.close();
server.close();
