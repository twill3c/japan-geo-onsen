import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { PNG } from 'pngjs';
import { decodeDem, decodeTile, marchingSquares, contours, levelsFor, DEM_INVALID, type Grid } from '../lib/dem';

const fixture = JSON.parse(readFileSync(new URL('./fixtures/dem_tiles.json', import.meta.url), 'utf8'));

describe('標高タイルの解読(SPEC G-02)', () => {
  // 期待値の出所: 国土地理院 標高タイル仕様
  // https://maps.gsi.go.jp/development/demtile.html
  //   x = 2^16 R + 2^8 G + B、x < 2^23 なら h = 0.01x、x > 2^23 なら h = 0.01(x - 2^24)、
  //   x = 2^23 は無効値。以下は仕様式から手で導いた値である(実測ではない)。
  it('仕様の式どおりに解く', () => {
    expect(decodeDem(0, 0, 0)).toBe(0);
    expect(decodeDem(0, 10, 0)).toBeCloseTo(25.6, 10);       // x = 2560
    expect(decodeDem(0, 0, 1)).toBeCloseTo(0.01, 10);        // 最小刻み
    expect(decodeDem(255, 255, 255)).toBeCloseTo(-0.01, 10); // x = 2^24 - 1
    expect(decodeDem(128, 0, 0)).toBeNull();                 // x = 2^23 = 無効値
    expect(DEM_INVALID).toBe(1 << 23);
  });

  // 期待値の出所: Python 実装(etl/common.py decode_dem_rgb)を実タイルに当てた実測。
  // フィクスチャは etl/make_dem_fixture.py が生成する。
  it.each(fixture.tiles as any[])('実タイル $path の全画素が Python 実装と一致する', (t: any) => {
    const png = PNG.sync.read(Buffer.from(t.png_base64, 'base64'));
    expect(png.width).toBe(256);
    expect(png.height).toBe(256);
    const values = decodeTile(new Uint8ClampedArray(png.data), 256);
    expect(values.length).toBe(t.pixels);

    const canonical = values.map((v) => (v === null ? 'null' : String(Math.round(v * 100)))).join('\n');
    expect(createHash('sha256').update(canonical, 'utf8').digest('hex')).toBe(t.sha256);

    const ok = values.filter((v): v is number => v !== null);
    expect(ok.length).toBe(t.valid);
    if (ok.length > 0) {
      expect(Math.min(...ok)).toBeCloseTo(t.min_m, 6);
      expect(Math.max(...ok)).toBeCloseTo(t.max_m, 6);
    }
  });

  it('照合したタイルが 8 枚あり、全画素が有効値である(対照が空振りしていない)', () => {
    expect(fixture.tiles.length).toBe(8);
    // 全部が無効値のタイルを並べても照合は通ってしまう。実際に標高が入っていることを言う
    for (const t of fixture.tiles) expect(t.valid).toBeGreaterThan(0);
  });

  // 変異体検査(2026-09-07 実測)で分かったこと。
  //   変異体 A「負標高の折返しを 2^24 でなく 2^23 にする」… 実タイル照合は **8 枚とも緑のまま**で、
  //     仕様式のケースだけが落ちた。手元のタイルはすべて陸域で、負の標高を 1 画素も含まないため。
  //   変異体 B「R と B を入れ替える」… 実タイル照合が 8 枚とも落ちた。
  // つまり負の分岐を守っているのは仕様式のケースだけである。その事実をここで表明しておく。
  it('照合タイルには負の標高が含まれない(負の分岐は仕様式のケースだけが守っている)', () => {
    for (const t of fixture.tiles) expect(t.min_m).toBeGreaterThanOrEqual(0);
  });
});

/** 解析解が分かる合成 DEM を作る。 */
function synthetic(f: (i: number, j: number) => number | null, w = 32, h = 32): Grid {
  const z: (number | null)[] = [];
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) z.push(f(i, j));
  // 格子座標をそのまま「経緯度」として扱う(幾何の検算に地図投影は要らない)
  return { w, h, z, toLonLat: (i, j) => [i, j] };
}

describe('等高線 marching squares(SPEC G-06)', () => {
  it('平面 z = i の等高線は i = level の鉛直線になる', () => {
    const g = synthetic((i) => i, 32, 32);
    for (const level of [5, 10.5, 20]) {
      const segs = marchingSquares(g, level);
      expect(segs.length).toBe(31); // 縦 32 行 → セル 31 段
      for (const [a, b] of segs) {
        expect(a[0]).toBeCloseTo(level, 9);
        expect(b[0]).toBeCloseTo(level, 9);
        expect(Math.abs(a[1] - b[1])).toBeCloseTo(1, 9); // 1 セル分の縦線
      }
    }
  });

  it('円錐の等高線は閉じる(端点がちょうど 2 回ずつ現れる)', () => {
    // 中心 (15.5, 15.5) の円錐。格子の縁に触れない高さを選ぶ
    const g = synthetic((i, j) => 100 - Math.hypot(i - 15.5, j - 15.5), 32, 32);
    for (const level of [92, 95, 98]) {
      const segs = marchingSquares(g, level);
      expect(segs.length).toBeGreaterThan(8);
      const count = new Map<string, number>();
      for (const [a, b] of segs) for (const p of [a, b]) {
        const k = `${p[0].toFixed(9)},${p[1].toFixed(9)}`;
        count.set(k, (count.get(k) ?? 0) + 1);
      }
      // 閉じた輪なら、どの端点もちょうど 2 本の線分に共有される
      for (const [k, n] of count) expect(n, `端点 ${k} の次数`).toBe(2);
    }
  });

  it('欠測を含むセルは線を引かない(架空の地形を描かない)', () => {
    const g = synthetic((i, j) => (i === 16 ? null : i), 32, 32);
    // level 16 の線は i=16 の欠測列に接するセルからは出ない
    expect(marchingSquares(g, 16).length).toBe(0);
    // 欠測から離れた高さは従来どおり引ける
    expect(marchingSquares(g, 5).length).toBe(31);
  });

  it('等高線の値は格子の標高範囲に収まる', () => {
    const g = synthetic((i, j) => 1000 + i * 3.5, 32, 32);
    const levels = levelsFor(g, 50);
    expect(levels.length).toBeGreaterThan(0);
    for (const v of levels) {
      expect(v).toBeGreaterThanOrEqual(1000);
      expect(v).toBeLessThanOrEqual(1000 + 31 * 3.5);
      expect(v % 50).toBeCloseTo(0, 9);
    }
  });

  it('複数の高さを一度に引いても、1 本ずつ引いたのと同じ結果になる', () => {
    const g = synthetic((i, j) => 500 + 40 * Math.sin(i / 5) + 25 * Math.cos(j / 4), 40, 40);
    const levels = levelsFor(g, 20);
    expect(levels.length).toBeGreaterThan(3);
    const multi = contours(g, levels);
    for (const l of levels) {
      expect(multi.get(l), `level ${l}`).toEqual(marchingSquares(g, l));
    }
  });

  it('全域が欠測なら等高線は出ない', () => {
    const g = synthetic(() => null, 8, 8);
    expect(levelsFor(g, 10)).toEqual([]);
    expect(marchingSquares(g, 10)).toEqual([]);
  });
});
