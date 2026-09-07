import { chromium } from 'playwright';
const url = process.argv[2] ?? 'https://japan-geo-onsen.vercel.app';
const browser = await chromium.launch();
const page = await browser.newPage();
const scripts = new Set();
page.on('response', (r) => { if (/\.js(\?|$)/.test(r.url())) scripts.add(r.url()); });
await page.goto(url, { waitUntil: 'domcontentloaded' });
await page.waitForSelector('.maplibregl-canvas');
await page.waitForTimeout(4000);
await browser.close();
let found = false;
for (const s of scripts) {
  const body = await (await fetch(s)).text();
  if (!body.includes('lakes.geojson')) continue;
  found = true;
  const lazy = body.includes('getLayer("lakes")') || body.includes("getLayer('lakes')");
  console.log(`${s.split('/').pop()}: lakes.geojson あり / 遅延読み込みの目印(getLayer) = ${lazy}`);
}
if (!found) console.log('lakes.geojson を含む JS が見つからなかった(読み込んだ JS ' + scripts.size + ' 本)');
