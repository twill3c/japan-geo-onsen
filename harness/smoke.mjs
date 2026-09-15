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
      // 他の層の点が同じ位置に重なっていない P12 の点を選ぶ。重なっていると、クリックは
      // 上に描かれた層(Wikidata など)の点を選び、P12 にしか無い表示(AI の見立て)が出ない。
      // 最初は「P12 の先頭の点」を選んでいて、実装は正しいのに検品だけが落ちた
      const onsenLayers = ['onsen', 'onsen-wd', 'onsen-fac', 'onsen-wp'].filter((id) => m.getLayer(id));
      const f = m.queryRenderedFeatures({ layers: ['onsen'] }).find((c) => {
        const px = m.project(c.geometry.coordinates);
        return m.queryRenderedFeatures(px, { layers: onsenLayers }).length === 1;
      });
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
        // 周辺環境分析(設計書 §56)。数は点を開いてから別ファイルで読むので、出るまで待つ
        let surr = false;
        try {
          await page.waitForFunction(
            () => !!document.querySelector('.feature-panel .surroundings table'),
            null, { timeout: 20000 },
          );
          surr = true;
        } catch { /* 下の check で不合格になる */ }
        check(surr, '温泉詳細にまわり 5〜50km の表が出る');
        // AI の見立て(設計書 §35)。確率と呼ばず、何を当てたモデルかと免責を必ず添える
        let aiShown = false;
        try {
          await page.waitForFunction(
            () => !!document.querySelector('.feature-panel .ai-explain .ai-contrib'),
            null, { timeout: 20000 },
          );
          aiShown = true;
        } catch { /* 下の check で不合格になる */ }
        const aiSection = aiShown ? '' : await page.evaluate(() => {
          const t = document.querySelector('.feature-panel')?.innerText ?? '(パネル無し)';
          const i = t.indexOf('AI の見立て');
          return i < 0 ? '(節が無い)' : t.slice(i, i + 80).replace(/\s+/g, ' ');
        });
        check(aiShown, '温泉詳細に AI の見立て(寄与の表)が出る', aiSection);
        if (aiShown) {
          const ai = await page.locator('.feature-panel .ai-explain').innerText();
          check(/確率ではありません/.test(ai), 'AI の出力を確率と呼ばないと書かれている');
          check(/学習に使っていないモデル/.test(ai), 'その都道府県を学習に使っていないモデルの出力だと書かれている');
          check(ai.includes('この結果は公開データから学習した統計モデルによる推定です。'), '温泉詳細の AI にも免責が出る');
          check(!/%/.test(ai.split('\n').filter((l) => /出力/.test(l)).join('')), 'AI の出力を % で出していない');
          const rows = await page.locator('.feature-panel .ai-contrib tr').count();
          check(rows === 4, `寄与の大きい特徴量が 4 つ並ぶ(${rows})`);
        }
        if (surr) {
          const st = await page.locator('.feature-panel .surroundings').innerText();
          check(/50 km/.test(st) && /活火山/.test(st) && /湖沼/.test(st), '周辺の表に半径と対象が並ぶ');
          check(/河川と標高の起伏は数えていません/.test(st), '数えていないものが書かれている');
          // 内訳の表(details の中)も thead を持つので、最初の表だけを数える。
          // 両方を数えていて「列 9」と出ていた(合格はするが報告の数が嘘になる)
          const cols = await page.locator('.feature-panel .surroundings > table thead th').count();
          check(cols === 5, `周辺の表に 4 つの半径の列がある(${cols - 1})`);
        }
      }
    }

    // 温泉比較(設計書 §57)。詳細から「比べる」を押し、別の温泉をクリックして表が出るまで見る
    const cmpBtn = page.getByText('この温泉を別の温泉と比べる');
    const hasCmp = (await cmpBtn.count()) > 0;
    check(hasCmp, '温泉の詳細に「比べる」がある');
    if (hasCmp) {
      await cmpBtn.first().click();
      const picked = await page.evaluate(() => {
        const m = window.__map;
        const a = document.querySelector('.compare-panel')?.textContent ?? '';
        const fs = m.queryRenderedFeatures({ layers: ['onsen'] });
        // A と違う名前で、他の層と重ならない点を B に選ぶ(重なっていると選択肢の一覧が出る。
        // 一覧から選ぶ経路は下で別に確かめる)
        const layers = ['onsen', 'onsen-wd', 'onsen-fac', 'onsen-wp'].filter((id) => m.getLayer(id));
        const f = fs.find((x) => x.properties?.name && !a.includes(String(x.properties.name))
          && m.queryRenderedFeatures(m.project(x.geometry.coordinates), { layers }).length === 1);
        if (!f) return false;
        const p = m.project(f.geometry.coordinates);
        const r = m.getCanvas().getBoundingClientRect();
        m.getCanvas().dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: p.x + r.left, clientY: p.y + r.top }));
        return true;
      });
      let shown = false;
      if (picked) {
        try {
          await page.waitForSelector('.compare-panel .compare-table', { timeout: 15000 });
          shown = true;
        } catch { /* 下の check で不合格になる */ }
      }
      check(shown, '別の温泉をクリックすると比較表が出る');
      if (shown) {
        const ct = await page.locator('.compare-panel').innerText();
        // 設計書の表の行が並び、泉温などは両列とも「公開データに無い」
        check(/標高/.test(ct) && /火山距離/.test(ct) && /河川距離/.test(ct), '比較表に設計書の行が並ぶ');
        // 無い行は A・B をまたぐ 1 欄にまとめてある。行の名前ごとに確かめる
        const naRows = await page.evaluate(() => [...document.querySelectorAll('.compare-table tr.unavailable')]
          .map((tr) => `${tr.querySelector('th')?.textContent}:${tr.querySelector('td')?.textContent}`));
        const wantNa = ['泉温', '湧出量', 'pH', '泉質'];
        check(wantNa.every((k) => naRows.some((r) => r.startsWith(`${k}:`) && r.includes('公開データに無い'))),
          `泉温・湧出量・pH・泉質が A・B とも「公開データに無い」(${naRows.length} 行)`);
        check(/この温泉の値ではありません/.test(ct), '都道府県の集計を参考として分けている');
        const over = await page.evaluate(() => {
          const el = document.querySelector('.compare-panel');
          return el ? el.scrollWidth > el.clientWidth + 1 : true;
        });
        check(!over, '比較パネルに横のはみ出しが無い');
      }
      await page.locator('.compare-panel .close').click().catch(() => {});
    }

    // 重なった点を選べる(SPEC F-21)。P12 の点に他の層の点が重なっている位置を探して押し、
    // 一覧から P12 の点を選ぶと、P12 にしか無い AI の見立てまで届くことを確かめる。
    // 以前は画素 1 点で上の層の点だけを開いており、この位置の P12 の点には届かなかった
    const overlapPx = await page.evaluate(() => {
      const m = window.__map;
      if (!m) return null;
      const layers = ['onsen', 'onsen-wd', 'onsen-fac', 'onsen-wp'].filter((id) => m.getLayer(id));
      for (const f of m.queryRenderedFeatures({ layers: ['onsen'] })) {
        const p = m.project(f.geometry.coordinates);
        const hits = m.queryRenderedFeatures(p, { layers });
        if (hits.length >= 2 && hits.some((h) => h.layer.id !== 'onsen')) {
          return { x: p.x, y: p.y, name: f.properties.name };
        }
      }
      return null;
    });
    check(overlapPx !== null, '初期表示に P12 と他の層が重なった点がある(検品の前提)');
    if (overlapPx) {
      await page.evaluate(({ x, y }) => {
        const c = window.__map.getCanvas();
        const r = c.getBoundingClientRect();
        c.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: x + r.left, clientY: y + r.top }));
      }, overlapPx);
      let chooser = false;
      try {
        await page.waitForSelector('.feature-panel .point-chooser li', { timeout: 10000 });
        chooser = true;
      } catch { /* 下の check で不合格になる */ }
      const items = chooser ? await page.locator('.feature-panel .point-chooser li').allInnerTexts() : [];
      check(chooser && items.length >= 2, `重なった位置を押すと選択肢の一覧が出る(${items.length} 件)`);
      const ksj = page.locator('.feature-panel .point-chooser li', { hasText: '温泉（国土数値情報）' }).first();
      if (chooser && (await ksj.count()) > 0) {
        await ksj.locator('button').click();
        let reached = false;
        try {
          await page.waitForSelector('.feature-panel .ai-explain .ai-contrib', { timeout: 20000 });
          reached = true;
        } catch { /* 下の check で不合格になる */ }
        check(reached, '一覧から国土数値情報の点を選ぶと AI の見立てまで届く');
        const back = page.getByText(/重なっている \d+ 件の一覧に戻る/);
        check((await back.count()) > 0, '選んだ点の詳細から一覧に戻れる');
        if ((await back.count()) > 0) {
          await back.first().click();
          const again = await page.locator('.feature-panel .point-chooser li').count();
          check(again === items.length, `一覧に戻ると同じ候補が並ぶ(${again} 件)`);
        }
      } else {
        check(false, '選択肢に国土数値情報の点がある', items.join(' / '));
      }
      await page.locator('.feature-panel .close').click().catch(() => {});
    }

    // 入浴施設の層(第三の層)。全国 108 点しかないので、**その場所へ寄ってから**数える。
    // 発端になった「ほったらかし温泉」が実際に出ることを、名前で確かめる。
    const fac = await page.evaluate(async () => {
      const m = window.__map;
      if (!m || !m.getLayer('onsen-fac')) return null;
      m.jumpTo({ center: [138.652222, 35.706111], zoom: 12 });
      const wait = (ms) => new Promise((r) => setTimeout(r, ms));
      const until = Date.now() + 20000;
      let f = [];
      while (Date.now() < until && f.length === 0) {
        await wait(250);
        f = m.queryRenderedFeatures({ layers: ['onsen-fac'] });
      }
      return {
        count: f.length,
        names: f.map((x) => x.properties?.name).filter(Boolean),
        cls: f.map((x) => x.properties?.facility_class).filter(Boolean),
      };
    });
    check(fac !== null, '入浴施設の層がある');
    if (fac) {
      check(fac.count > 0, `入浴施設が地図に描かれている(${fac.count} 件)`);
      check(fac.names.includes('ほったらかし温泉'), 'ほったらかし温泉が地図に出る', fac.names.join('/'));
      check(fac.cls.some((c) => /入浴施設|銭湯|浴場/.test(c)), '入浴施設の分類が属性に入っている', fac.cls.join('/'));
      // クリックすると「温泉とは限らない」と断っているか
      const opened = await page.evaluate(() => {
        const m = window.__map;
        const f = m.queryRenderedFeatures({ layers: ['onsen-fac'] })[0];
        if (!f) return false;
        const p = m.project(f.geometry.coordinates);
        const r = m.getCanvas().getBoundingClientRect();
        m.getCanvas().dispatchEvent(new MouseEvent('click', {
          bubbles: true, clientX: p.x + r.left, clientY: p.y + r.top,
        }));
        return true;
      });
      if (opened) {
        const t = await page.locator('.feature-panel').innerText().catch(() => '');
        check(/温泉とは限りません/.test(t), '入浴施設は温泉とは限らないと断っている');
        check(/統計（温泉と地理環境）にはこの層を使っていません/.test(t), '入浴施設が統計に使われないと書かれている');
      }
      await page.evaluate(() => window.__map.jumpTo({ center: [138.35, 35.98], zoom: 9.2 }));
      await page.locator('.feature-panel .close').click().catch(() => {});
    }

    // 第四の層(Wikipedia の温泉記事)。既定では消えているので、点けてから数える。
    const wpToggle = page.getByText('温泉記事（Wikipedia）');
    const hasWp = (await wpToggle.count()) > 0;
    check(hasWp, 'Wikipedia の温泉記事の層がある');
    if (hasWp) {
      await wpToggle.click();
      let wp = 0;
      try {
        await page.waitForFunction(
          () => (window.__map?.querySourceFeatures('onsen-wp') ?? []).length > 0,
          null, { timeout: 30000 },
        );
        wp = await page.evaluate(() => window.__map.querySourceFeatures('onsen-wp').length);
      } catch { /* 下の check で不合格になる */ }
      check(wp > 0, 'Wikipedia の温泉記事が地図に載っている', `${wp} 件`);
      await wpToggle.click();
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
    // 地域比較(設計書 §58)。表は regions.json を読んでから出るので、出るまで待つ
    await page.goto(`${base}/regions/`, { waitUntil: 'domcontentloaded' });
    let regionTable = false;
    try {
      await page.waitForSelector('.region-table', { timeout: 20000 });
      regionTable = true;
    } catch { /* 下の check で不合格になる */ }
    check(regionTable, '地域比較の表が出る');
    if (regionTable) {
      const heads = await page.locator('.region-table thead th').allInnerTexts();
      const want = ['八ヶ岳', '富士山', '箱根', '草津', '別府'];
      check(want.every((w) => heads.some((h) => h.includes(w))), '設計書の 5 地域が列に並ぶ', heads.join('/'));
      const rt = await page.locator('main').innerText();
      check(/境界を定めていません/.test(rt), '地域の境界を推測しないと書かれている');
      check(/円が重なっている組があります/.test(rt), '円の重なりを注記している');
      check(/足していません/.test(rt), '出所ごとの点を足さないと書かれている');
      // 気象庁の火山を足すと列が 1 つ増える
      const before = heads.length;
      await page.locator('.region-controls select').nth(1).selectOption({ index: 1 });
      const after = await page.locator('.region-table thead th').count();
      check(after === before + 1, `活火山を基準点に足すと列が増える(${before - 1} → ${after - 1})`);
      bad = await overflowing(page);
      check(bad.length === 0, '地域比較の画面に横のはみ出しが無い', bad.join(' / '));
    }

    // AI(設計書 Phase 4〜5)。免責(§36)の文言がそのまま出て、禁じた表現を使っていないこと
    await page.goto(`${base}/ai/`, { waitUntil: 'domcontentloaded' });
    const at = await page.locator('main').innerText();
    check(at.includes('この結果は公開データから学習した統計モデルによる推定です。温泉の存在・泉質・湧出量を保証するものではありません。'),
      'AI の免責(設計書 §36)が文言どおり出ている');
    check(!/掘れば/.test(at), 'AI の画面で「掘れば」という表現を使っていない');
    check(/温泉が湧くか」ではなく/.test(at), 'AI が当てているのは温泉の存在ではないと書かれている');
    const gateRows = await page.locator('main table').first().locator('tbody tr').count();
    check(gateRows === 3, `事前登録した合否が 3 行並ぶ(${gateRows})`);
    check(/Logistic Regression/.test(at) && /Random Forest/.test(at) && /XGBoost/.test(at), '3 つのモデルが並ぶ');
    check(/陰性対照/.test(at), '陰性対照の結果が書かれている');
    bad = await overflowing(page);
    check(bad.length === 0, 'AI の画面に横のはみ出しが無い', bad.join(' / '));

    // 地図に出せない温泉の一覧(名前は分かるが位置が公開データに無いもの)
    await page.goto(`${base}/missing/`, { waitUntil: 'domcontentloaded' });
    const ms = await page.locator('main').innerText();
    check(/架空のデータを作ること/.test(ms), '座標を作らない理由が書かれている');
    check(/山中湖温泉/.test(ms), '指摘された温泉が一覧に載っている');
    check(/大田区の黒湯温泉/.test(ms), '大田区の黒湯温泉が一覧に載っている');
    check(/まとまり/.test(ms) && /概念/.test(ms), '一覧にまとまりや概念が混ざると断っている');
    const names = await page.locator('.name-list li').count();
    check(names > 900, `一覧に名前が並んでいる(${names} 件)`);
    bad = await overflowing(page);
    check(bad.length === 0, '未掲載一覧に横のはみ出しが無い', bad.join(' / '));

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
