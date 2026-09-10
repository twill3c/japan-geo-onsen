/**
 * 配られている本番が、意図した版かを実測する。
 *
 * デプロイが失敗しても古い版が動き続けるので、画面が出ているだけでは
 * 確かめたことにならない(実測 2026-09-08)。**この版にしか無い印**を探す。
 *
 *   node harness/_which3.mjs [URL]
 */
import { chromium } from 'playwright';

const url = process.argv[2] ?? 'https://japan-geo-onsen.vercel.app';
const browser = await chromium.launch();
const page = await browser.newPage();

const asked = [];
page.on('request', (r) => {
  const m = r.url().match(/\/data\/([a-z_]+\.(?:geojson|json))/);
  if (m) asked.push(m[1]);
});

await page.goto(url, { waitUntil: 'domcontentloaded' });
await page.waitForSelector('.maplibregl-canvas');
await page.waitForTimeout(5000);

const layers = await page.evaluate(() => {
  const m = window.__map;
  return m ? m.getStyle().layers.map((l) => l.id) : null;
});
console.log('起動時に取得したデータ:', asked.join(', ') || '(なし)');
console.log('温泉の層:', layers ? layers.filter((l) => l.startsWith('onsen')).join(', ') : '(不明)');

const checks = [
  ['温泉の統計ページ(源泉総数)', '/onsen-stats/', '27,899'],
  ['統計に Wikidata を使わない注記', '/stats/', 'この集計には使っていません'],
  ['2,839 の再現ではないという断り', '/onsen-stats/', '再現したものではありません'],
  ['入浴施設の層の説明(about)', '/about/', '入浴施設の層'],
  ['ほったらかし温泉の経緯(onsen-stats)', '/onsen-stats/', 'ほったらかし温泉'],
  ['地図に出せない温泉の一覧', '/missing/', '架空のデータを作ること'],
  ['山中湖温泉が一覧に載っている', '/missing/', '山中湖温泉'],
];
for (const [label, path, needle] of checks) {
  await page.goto(url + path, { waitUntil: 'domcontentloaded' });
  const t = await page.locator('main').innerText();
  console.log(`${label}: ${t.includes(needle) ? 'あり' : '**無い**'}`);
}

await browser.close();
