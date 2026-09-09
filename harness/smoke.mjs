/**
 * 実ブラウザ検品。
 *
 * 型検査もテストも緑のまま通る欠陥（レイヤーが出ない・パネルが溢れる・
 * 等高線が引けない）は、実際に開いてみないと分からない。
 *
 *   node harness/smoke.mjs            出荷物(out/)を配って検品する
 *   node harness/smoke.mjs --shot     併せて画面を撮る(harness/shots/)
 *   node harness/smoke.mjs --url URL  既に動いている場所を検品する(本番検品)
 *
 * 終了コード: 合格 0 / 不合格 1 / 検品器自身の異常 2。
 * `process.exit()` は使わない（開いたままの handle があると別の値で abort する — HC-198）。
 */
import { chromium } from 'playwright';
import { createServer } from 'node:http';
import { readFile, mkdir, stat } from 'node:fs/promises';
import { extname, join, resolve } from 'node:path';

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.geojson': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.txt': 'text/plain; charset=utf-8',
};

const args = process.argv.slice(2);
const wantShots = args.includes('--shot');
const urlArg = args.includes('--url') ? args[args.indexOf('--url') + 1] : null;

const failures = [];
const notes = [];
function check(ok, label, detail = '') {
  if (ok) notes.push(`  OK   ${label}`);
  else failures.push(`  FAIL ${label}${detail ? ` — ${detail}` : ''}`);
}

async function serve(root) {
  const server = createServer(async (req, res) => {
    try {
      let p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
      if (p.endsWith('/')) p += 'index.html';
      let file = join(root, p);
      try {
        if ((await stat(file)).isDirectory()) file = join(file, 'index.html');
      } catch {
        if (!extname(file)) file = `${file}.html`;
      }
      const body = await readFile(file);
      res.writeHead(200, { 'content-type': MIME[extname(file)] ?? 'application/octet-stream' });
      res.end(body);
    } catch {
      res.writeHead(404, { 'content-type': 'text/plain' });
      res.end('not found');
    }
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  return { server, base: `http://127.0.0.1:${server.address().port}` };
}

/** 見えている要素が親の外へはみ出していないかを実測する(代理指標では捕まらない — HC-194)。 */
async function overflowing(page) {
  return page.evaluate(() => {
    const bad = [];
    const docW = document.documentElement.clientWidth;
    for (const el of document.querySelectorAll('body *')) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      if (r.right > docW + 1) {
        bad.push(`${el.tagName.toLowerCase()}.${el.className || '(no class)'} right=${r.right.toFixed(1)} > ${docW}`);
      }
    }
    return bad.slice(0, 8);
  });
}

async function main() {
  let stop = () => {};
  let base = urlArg;
  if (!base) {
    const root = resolve('out');
    try {
      await stat(join(root, 'index.html'));
    } catch {
      console.error('out/index.html がない。先に npm run build を走らせること');
      process.exitCode = 2;
      return;
    }
    const s = await serve(root);
    base = s.base;
    stop = () => s.server.close();
  }

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const consoleErrors = [];
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', (e) => consoleErrors.push(String(e)));

  try {
    /* ---------- 地図画面 ---------- */
    // networkidle は地図タイルが流れ続ける本番では届かないことがある。
    // 以降の waitForSelector / waitForFunction が本当の待ちなので、ここは軽く待つ。
    await page.goto(`${base}/`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.maplibregl-canvas', { timeout: 20000 });
    check(true, '地図の canvas が出る');

    // 「canvas がある」だけでは足りない。**置き場と同じ大きさで描かれているか**を測る。
    // MapLibre は置き場の高さが確定する前に構築されると既定の 400x300 で固まり、
    // その状態でも canvas は存在し、フィーチャの照会も通り、検査は全部緑になる(HC-194)。
    const box = await page.evaluate(() => {
      const c = document.querySelector('.maplibregl-canvas').getBoundingClientRect();
      const a = document.querySelector('.map-area').getBoundingClientRect();
      return { cw: c.width, ch: c.height, aw: a.width, ah: a.height };
    });
    check(
      Math.abs(box.cw - box.aw) <= 2 && Math.abs(box.ch - box.ah) <= 2,
      '地図が置き場いっぱいに描かれている',
      `canvas ${box.cw}x${box.ch} / 置き場 ${box.aw}x${box.ah}`,
    );
    check(box.ch > 400, '地図の高さが十分ある', `${box.ch}px`);

    // 画面の高さを定数で足し引きすると、ヘッダの行数が変わった日に静かに壊れる(HC-205)。
    // 「フッタより上か」「余計な縦スクロールが出ていないか」を実測で押さえる。
    const fit = await page.evaluate(() => {
      const a = document.querySelector('.map-area').getBoundingClientRect();
      const f = document.querySelector('.fleet-footer').getBoundingClientRect();
      return {
        overlap: +(a.bottom - f.top).toFixed(1),
        scroll: document.documentElement.scrollHeight,
        view: window.innerHeight,
      };
    });
    check(fit.overlap <= 0, '地図の下端がフッタに被っていない', `${fit.overlap}px 被り`);
    check(fit.scroll <= fit.view + 1, '地図画面に余計な縦スクロールが出ない',
      `${fit.scroll} > ${fit.view}`);

    const disclaimer = await page.locator('.disclaimer').innerText();
    check(/保証するものではありません/.test(disclaimer), '免責が常に出ている', disclaimer.slice(0, 40));

    // 温泉と火山が描かれているか(MapLibre の内部状態ではなく、描画済みフィーチャを数える)
    //
    // 固定の待ち時間で数えていたら、本番で 3 層とも 0 件になった。実測すると点が出るのは
    // 約 3.0 秒で、待ちが 2.5 秒では足りていなかっただけである(手元では届いていた)。
    // 固定待ちは回線の速さを測る計器になってしまうので、**出るまで待って、出なければ落とす**
    // 形に変えた。締切を過ぎたらそのときの数(0 のまま)を返すので、本当に描かれない故障は
    // これまで通り落ちる。
    const RENDER_DEADLINE_MS = Number(process.env.SMOKE_RENDER_DEADLINE_MS ?? 20000);
    const counts = await page.evaluate(async (deadlineMs) => {
      const wait = (ms) => new Promise((r) => setTimeout(r, ms));
      const m = window.__map;
      if (!m) return null;
      const read = () => ({
        onsen: m.queryRenderedFeatures({ layers: ['onsen'] }).length,
        onsenWd: m.queryRenderedFeatures({ layers: ['onsen-wd'] }).length,
        volcano: m.queryRenderedFeatures({ layers: ['volcano'] }).length,
      });
      const until = Date.now() + deadlineMs;
      let c = read();
      while (Date.now() < until && !(c.onsen > 0 && c.onsenWd > 0 && c.volcano > 0)) {
        await wait(250);
        c = read();
      }
      return c;
    }, RENDER_DEADLINE_MS);
    if (counts === null) {
      notes.push('  --   window.__map が無いので描画数は数えていない');
    } else {
      check(counts.onsen > 0, `温泉(国土数値情報)が描かれている(${counts?.onsen} 件)`);
      check(counts.onsenWd > 0, `温泉(Wikidata)が描かれている(${counts?.onsenWd} 件)`);
      check(counts.volcano > 0, `火山が描かれている(${counts?.volcano} 件)`);
    }

    // 等高線を入れて、線が出るところまで見る
    await page.getByText('標高タイルから引く').click();
    await page.waitForFunction(
      () => /本 \/ 標高タイル|拡大してください|取得できませんでした/.test(document.body.innerText),
      null, { timeout: 40000 },
    );
    const note = await page.locator('.layer-panel .status').first().innerText();
    check(/本 \/ 標高タイル z\d+ を \d+ 枚/.test(note), '等高線が引ける', note);

    // 注記は setData を呼んだ時点で出る。**線が実際に地図に載るのはそのあと**なので、
    // 注記だけを見て合格にすると、線が一本も無い画面を緑で通してしまう
    // (実測 2026-09-07: 注記が出た直後の画面では等高線色の画素が 0.25% しか無く、
    //  描画が落ち着いた画面では 5.28% あった)。
    let contourFeatures = 0;
    try {
      await page.waitForFunction(
        () => (window.__map?.querySourceFeatures('contours') ?? []).length > 0,
        null, { timeout: 30000 },
      );
      contourFeatures = await page.evaluate(() => window.__map.querySourceFeatures('contours').length);
    } catch { /* 下の check で不合格になる */ }
    check(contourFeatures > 0, '等高線が地図に載っている', `${contourFeatures} 本`);
    await page.waitForTimeout(1200);

    // 水のレイヤー。既定は消えているので、点けてから**実際に描かれたか**を数える
    for (const [label, layer] of [['河川(1級河川の直轄区間)', 'rivers'], ['湖沼', 'lakes']]) {
      await page.getByText(label, { exact: true }).click();
      let n = 0;
      try {
        await page.waitForFunction(
          (id) => (window.__map?.querySourceFeatures(id) ?? []).length > 0,
          layer, { timeout: 30000 },
        );
        n = await page.evaluate((id) => window.__map.querySourceFeatures(id).length, layer);
      } catch { /* 下の check で不合格になる */ }
      check(n > 0, `${label} が地図に載っている`, `${n} 件`);
    }

    // 温泉をクリックして詳細が出るか
    const clicked = await page.evaluate(() => {
      const m = window.__map;
      if (!m) return false;
      const f = m.queryRenderedFeatures({ layers: ['onsen'] })[0];
      if (!f) return false;
      const p = m.project(f.geometry.coordinates);
      m.getCanvas().dispatchEvent(new MouseEvent('click', {
        bubbles: true, clientX: p.x + m.getCanvas().getBoundingClientRect().left,
        clientY: p.y + m.getCanvas().getBoundingClientRect().top,
      }));
      return true;
    });
    if (clicked) {
      const shown = await page.locator('.feature-panel').isVisible().catch(() => false);
      check(shown, '温泉をクリックすると詳細が出る');
      if (shown) {
        const t = await page.locator('.feature-panel').innerText();
        check(/公開データに無い/.test(t), '無い項目が「公開データに無い」と書かれている');
        check(/植生自然度/.test(t), '温泉詳細に植生自然度が出ている');
      }
    }

    // 地形断面(設計書 §56)。地図を 2 回クリックして図が出るところまで見る。
    // 切替が無い版に当てたときは、例外で検品ごと落とさず**不合格として**数える
    // (この検査群は、断面を積む前の本番に当てて 7 件とも落ちることを確かめてある)。
    const profileToggle = page.getByText('地図に線を引いて断面を見る');
    const hasProfile = (await profileToggle.count()) > 0;
    check(hasProfile, '地形断面の切替がある');
    if (hasProfile) await profileToggle.click();
    const drew = hasProfile && await page.evaluate(async () => {
      const m = window.__map;
      if (!m) return false;
      const c = m.getCanvas();
      const r = c.getBoundingClientRect();
      const clickAt = (dx, dy) => c.dispatchEvent(new MouseEvent('click', {
        bubbles: true, clientX: r.left + r.width * dx, clientY: r.top + r.height * dy,
      }));
      clickAt(0.35, 0.42);
      await new Promise((res) => setTimeout(res, 250));
      clickAt(0.62, 0.58);
      return true;
    });
    if (drew) {
      let shown = false;
      try {
        await page.waitForFunction(
          () => /全長 [\d.]+ km/.test(document.querySelector('.profile-panel')?.innerText ?? ''),
          null, { timeout: 40000 },
        );
        shown = true;
      } catch { /* 下の check で不合格になる */ }
      check(shown, '地図を 2 回クリックすると断面図が出る');
      if (shown) {
        const t = await page.locator('.profile-panel').innerText();
        // 縦を引き伸ばして描いていることを言わずに出すと、実際より険しく見える
        check(/縦は横の.*倍に引き伸ばして/.test(t), '断面図に誇張倍率が書かれている');
        check(/標高タイル z\d+ を \d+ 枚/.test(t), '断面が読んだ標高タイルの段と枚数が出ている');
        check(/画素の値をそのまま/.test(t), '断面が画素を混ぜていないと書かれている');
        check(/国土地理院 標高タイル/.test(t), '断面に出典が書かれている');
        const path = await page.locator('.profile-panel svg path').count();
        check(path > 0, '断面図に線が描かれている', `${path} 本`);
      }
      const line = await page.evaluate(
        () => (window.__map?.querySourceFeatures('profile-line') ?? []).length,
      );
      // 点 A・点 B・線の 3 つ
      check(line >= 3, '引いた線が地図にも残っている', `${line} 件`);
    }

    let bad = await overflowing(page);
    check(bad.length === 0, '地図画面に横のはみ出しが無い', bad.join(' / '));
    if (wantShots) {
      await mkdir('harness/shots', { recursive: true });
      await page.screenshot({ path: 'harness/shots/map.png' });
    }

    /* ---------- 統計画面 ---------- */
    await page.goto(`${base}/stats/`, { waitUntil: 'domcontentloaded' });
    const statsText = await page.locator('main').innerText();
    check(/この集計には使っていません/.test(statsText),
      '統計に Wikidata を使っていないと書かれている');
    check(/自然林・自然草原では差がほぼありません/.test(statsText),
      '植生で差が出るのが中ほどだけと書かれている');
    check(/1992〜1996 年/.test(statsText), '植生調査の年が書かれている');
    const svgs = await page.locator('.viz svg').count();
    check(svgs >= 7, `軸ごとの図がある(${svgs} 枚)`);
    const legends = await page.locator('.viz-legend').count();
    check(legends === svgs, '図の数だけ凡例がある');
    bad = await overflowing(page);
    check(bad.length === 0, '統計画面に横のはみ出しが無い', bad.join(' / '));
    if (wantShots) await page.screenshot({ path: 'harness/shots/stats.png', fullPage: true });

    /* ---------- 温泉の統計画面 ---------- */
    await page.goto(`${base}/onsen-stats/`, { waitUntil: 'domcontentloaded' });
    const os = await page.locator('main').innerText();
    check(/27,899/.test(os), '全国の源泉総数が出ている');
    check(/42 度以上/.test(os), '温度別の区分が出ている');
    check(/点が 1 つもありません/.test(os), '点の被覆の穴が書かれている');
    check(/Wikidata/.test(os) && /2,839 という数そのものを再現したものではありません/.test(os),
      'Wikidata を足しても 2,839 の再現ではないと書かれている');
    check(/富山県/.test(os), '出典の食い違いが書かれている');
    const segs = await page.locator('.seg-legend li').count();
    check(segs === 4, `温度別の凡例が 4 区分ある(${segs})`);
    bad = await overflowing(page);
    check(bad.length === 0, '温泉の統計画面に横のはみ出しが無い', bad.join(' / '));
    if (wantShots) await page.screenshot({ path: 'harness/shots/onsen-stats.png', fullPage: true });

    /* ---------- 出典画面 ---------- */
    await page.goto(`${base}/about/`, { waitUntil: 'domcontentloaded' });
    const about = await page.locator('main').innerText();
    check(/見つかりませんでした/.test(about), '見つからなかったデータの記録がある');
    check(/10 都府県/.test(about), '被覆の穴が書かれている');
    bad = await overflowing(page);
    check(bad.length === 0, '出典画面に横のはみ出しが無い', bad.join(' / '));
    if (wantShots) await page.screenshot({ path: 'harness/shots/about.png', fullPage: true });

    /* ---------- フッタ ---------- */
    const footer = await page.locator('.fleet-footer').innerText();
    check(/MIT License/.test(footer) && /App Menu/.test(footer), 'フリート共通フッタが出ている');

    // 外部タイルの失敗は console に出るので、それ以外の実エラーだけを見る
    const real = consoleErrors.filter((e) => !/tile|cyberjapandata|gbank|AJAXError|Failed to fetch/i.test(e));
    check(real.length === 0, 'ページ由来の JavaScript エラーが無い', real.slice(0, 3).join(' / '));
  } finally {
    await browser.close();
    stop();
  }

  console.log(notes.join('\n'));
  if (failures.length) {
    console.log(`\n不合格 ${failures.length} 件:`);
    console.log(failures.join('\n'));
    process.exitCode = 1;
  } else {
    console.log(`\n合格 — ${notes.length} 項目`);
  }
}

main().catch((e) => {
  console.error('検品器の異常:', e);
  process.exitCode = 2;
});
