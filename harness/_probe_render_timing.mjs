// 点の層の描画数を数える計器の較正(loop_005 の記録)。
//
// 背景: 本番デプロイ直後の smoke で「温泉(国土数値情報)/(Wikidata)/火山が描かれている」の
// 3 件が 0 件で落ちた。手元では緑。原因は計器側で、固定 2,500ms 待ちが足りていなかった
// (配信し始めの本番では点が出るまで約 3.0 秒かかった)。
//
// このプローブは二つを測る。
//   (1) 点が初めて 0 でなくなるまでの時刻
//   (2) 陽性対照 — データを空の FeatureCollection に差し替えたとき、
//       締切まで待っても 0 のままであること(= 検査が空振りしていない)
//
// 使い方: node harness/_probe_render_timing.mjs [url]
import { chromium } from 'playwright';

const url = process.argv[2] || 'https://japan-geo-onsen.vercel.app';
const LAYERS = { onsen: 'onsen', wd: 'onsen-wd', volcano: 'volcano' };

// page.evaluate に渡す関数はブラウザ側で動く。外の変数は見えないので層の対応も引数で渡す。
const read = (layers) =>
  Object.fromEntries(
    Object.entries(layers).map(([k, id]) => {
      try {
        return [k, window.__map.queryRenderedFeatures({ layers: [id] }).length];
      } catch {
        return [k, -1];
      }
    }),
  );

async function open(browser, { blank }) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  if (blank) {
    // 出所の違う 3 つの層すべてを空にする
    await page.route('**/data/{onsen,onsen_wikidata,volcanoes}.geojson', (route) =>
      route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ type: 'FeatureCollection', metadata: {}, features: [] }),
      }),
    );
  }
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForSelector('.maplibregl-canvas', { timeout: 20000 });
  return page;
}

const browser = await chromium.launch();
let bad = 0;

// (1) いつ描かれるか
{
  const page = await open(browser, { blank: false });
  const t0 = Date.now();
  const seen = {};
  for (let i = 0; i < 80; i++) {
    const c = await page.evaluate(read, LAYERS);
    for (const k of Object.keys(LAYERS)) if (c[k] > 0 && !seen[k]) seen[k] = Date.now() - t0;
    if (Object.keys(seen).length === Object.keys(LAYERS).length) break;
    await page.waitForTimeout(250);
  }
  console.log('(1) 初めて 0 でなくなった時刻(ms):', JSON.stringify(seen));
  if (Object.keys(seen).length !== Object.keys(LAYERS).length) {
    console.log('    → 20 秒たっても出ない層がある。これは計器でなく画面の故障');
    bad++;
  }
  await page.close();
}

// (2) 陽性対照 — 空にしたら締切まで待っても 0 のまま
{
  const page = await open(browser, { blank: true });
  const t0 = Date.now();
  let c = await page.evaluate(read, LAYERS);
  while (Date.now() - t0 < 8000) {
    await page.waitForTimeout(250);
    c = await page.evaluate(read, LAYERS);
    if (c.onsen > 0 || c.wd > 0 || c.volcano > 0) break;
  }
  const ok = c.onsen === 0 && c.wd === 0 && c.volcano === 0;
  console.log('(2) 陽性対照(データを空に差し替え):', JSON.stringify(c), ok ? 'OK' : 'NG');
  if (!ok) {
    console.log('    → 空でも数えられている。この検査は空振りしている');
    bad++;
  }
  await page.close();
}

await browser.close();
process.exitCode = bad ? 1 : 0;
