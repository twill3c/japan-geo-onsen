/**
 * 地形断面(標高プロファイル)の検算(SPEC G-14 / 設計書 §56)。
 *
 * 断面の誤りは**静かに**出る。画素の添字を 1 つずらしても、南北を裏返しても、
 * 線はそれらしい形で描かれてしまう。だから数を突き合わせる相手を置く。
 *
 *   1. Python 参照実装(etl/profile_ref.py)との**実タイル上での一致**
 *      —— フィクスチャは etl/make_profile_fixture.py が生成する
 *   2. 幾何の性質(端点・区間距離の和・分解能)からの検算
 *
 * 「その標高が本当に正しいか」は二実装では言えない。それは地理院の標高 API との
 * 突き合わせで測り、TEST_SPEC.md に記録した(harness/_probe_elevation.mjs)。
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { PNG } from 'pngjs';
import { decodeDem } from '../lib/dem';
import {
  R_KM, haversineKm, slerp, worldPixel, pixelResolutionM,
  samplePositions, profileFrom, chooseZoom, sampleCount,
  verticalExaggeration, PROFILE_MAX_TILES, MAX_SAMPLES,
} from '../lib/profile';

const tiles = JSON.parse(readFileSync(new URL('./fixtures/dem_tiles.json', import.meta.url), 'utf8'));
const fixture = JSON.parse(readFileSync(new URL('./fixtures/profile.json', import.meta.url), 'utf8'));

/** フィクスチャの実タイル 1 枚を、画素を引ける形にする。 */
function tileLookup(path: string) {
  const t = tiles.tiles.find((x: any) => x.path === path);
  if (!t) throw new Error(`フィクスチャに ${path} が無い`);
  const [z, x, y] = path.split('/').map(Number);
  const png = PNG.sync.read(Buffer.from(t.png_base64, 'base64'));
  return {
    z, x, y,
    lookup: (tx: number, ty: number, i: number, j: number): number | null => {
      if (tx !== x || ty !== y) return null;   // タイルの外は埋めない
      const p = (j * 256 + i) * 4;
      return decodeDem(png.data[p], png.data[p + 1], png.data[p + 2]);
    },
  };
}

describe('距離と大円上の刻み', () => {
  // 期待値の出所: 球面の定義そのもの。半径 6371.0088 km の子午線 1 度は
  // 2πR/360 = 111.1950802335329 km。
  // (最初この定数を 111.19492664455873 と書いて落ちた。実装ではなく定数が誤り)
  it('緯度 1 度の長さが球の定義と一致する', () => {
    const deg = (2 * Math.PI * R_KM) / 360;
    expect(haversineKm(139, 35, 139, 36)).toBeCloseTo(deg, 9);
    expect(deg).toBeCloseTo(111.1950802335329, 10);
  });

  it('赤道の経度 1 度は緯度 1 度と同じ長さ', () => {
    const deg = (2 * Math.PI * R_KM) / 360;
    expect(haversineKm(0, 0, 1, 0)).toBeCloseTo(deg, 9);
  });

  it('同じ点なら 0', () => {
    expect(haversineKm(138.35, 35.98, 138.35, 35.98)).toBe(0);
  });

  it('slerp の両端は A と B そのもの', () => {
    const [aLon, aLat] = slerp(138.0, 35.0, 139.0, 36.0, 0);
    const [bLon, bLat] = slerp(138.0, 35.0, 139.0, 36.0, 1);
    expect(aLon).toBeCloseTo(138.0, 10);
    expect(aLat).toBeCloseTo(35.0, 10);
    expect(bLon).toBeCloseTo(139.0, 10);
    expect(bLat).toBeCloseTo(36.0, 10);
  });

  it('中点は両端から等距離', () => {
    const [mLon, mLat] = slerp(138.0, 35.0, 140.0, 37.0, 0.5);
    const d1 = haversineKm(138.0, 35.0, mLon, mLat);
    const d2 = haversineKm(mLon, mLat, 140.0, 37.0);
    expect(d1).toBeCloseTo(d2, 9);
    expect(d1 + d2).toBeCloseTo(haversineKm(138.0, 35.0, 140.0, 37.0), 9);
  });

  it('刻んだ区間の距離の和が全長に戻る', () => {
    const pts = samplePositions(138.0, 35.0, 140.5, 37.5, 200);
    let sum = 0;
    for (let k = 1; k < pts.length; k++) {
      sum += haversineKm(pts[k - 1].lon, pts[k - 1].lat, pts[k].lon, pts[k].lat);
    }
    const total = haversineKm(138.0, 35.0, 140.5, 37.5);
    expect(sum).toBeCloseTo(total, 6);
    expect(pts[pts.length - 1].distanceKm).toBeCloseTo(total, 10);
  });

  it('2 点未満は例外(黙って通さない)', () => {
    expect(() => samplePositions(138, 35, 139, 36, 1)).toThrow();
  });
});

describe('画素の位置と分解能', () => {
  // 期待値の出所: Web メルカトルの定義。z=0 の 1 タイル 256 画素が全周 360 度。
  it('経度 0・緯度 0 は世界の中心の画素', () => {
    const [px, py] = worldPixel(0, 0, 0);
    expect(px).toBeCloseTo(128, 10);
    expect(py).toBeCloseTo(128, 10);
  });

  it('赤道の 1 画素は全周を 2^z*256 で割った長さ', () => {
    const circumference = 2 * Math.PI * R_KM * 1000;
    expect(pixelResolutionM(0, 0)).toBeCloseTo(circumference / 256, 6);
    expect(pixelResolutionM(14, 0)).toBeCloseTo(circumference / (2 ** 14 * 256), 6);
  });

  it('緯度が上がるほど 1 画素は短くなる', () => {
    expect(pixelResolutionM(14, 36)).toBeLessThan(pixelResolutionM(14, 0));
    expect(pixelResolutionM(14, 36)).toBeCloseTo(pixelResolutionM(14, 0) * Math.cos((36 * Math.PI) / 180), 9);
  });
});

describe('段と点数の決め方', () => {
  it('短い線ほど細かい段を使い、上限を超えない', () => {
    const zShort = chooseZoom(1, 36);
    const zLong = chooseZoom(300, 36);
    expect(zShort).toBe(14);
    expect(zLong).toBeLessThan(zShort);
    expect(zLong).toBeGreaterThanOrEqual(8);
  });

  it('段は長さに対して単調(長くなって細かくなることはない)', () => {
    let prev = 15;
    for (const km of [0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000]) {
      const z = chooseZoom(km, 36);
      expect(z).toBeLessThanOrEqual(prev);
      prev = z;
    }
  });

  it('選んだ段でのタイル枚数の見積もりが上限以内', () => {
    for (const km of [1, 5, 20, 80, 300]) {
      const z = chooseZoom(km, 36);
      const tileKm = (pixelResolutionM(z, 36) * 256) / 1000;
      expect(Math.ceil(km / tileKm) + 1).toBeLessThanOrEqual(PROFILE_MAX_TILES);
    }
  });

  it('点数は 2 以上・上限以下で、1 画素より細かくは刻まない', () => {
    for (const km of [0.05, 1, 20, 300]) {
      const z = chooseZoom(km, 36);
      const n = sampleCount(km, z, 36);
      expect(n).toBeGreaterThanOrEqual(2);
      expect(n).toBeLessThanOrEqual(MAX_SAMPLES);
      if (n < MAX_SAMPLES) {
        // 上限に当たっていないなら、点の間隔は 1 画素以上ある
        const spacing = (km * 1000) / (n - 1);
        expect(spacing).toBeGreaterThanOrEqual(pixelResolutionM(z, 36) * 0.999);
      }
    }
  });
});

describe('高さの誇張倍率', () => {
  // 断面図は縦を引き伸ばして描く。何倍かを言わずに出すと、実際より険しく見える。
  it('縦横の縮尺の比になる', () => {
    // 幅 800px に 10 km、高さ 200px に 500 m → 横 12.5 m/px、縦 2.5 m/px → 5 倍
    expect(verticalExaggeration(10, 800, 500, 200)).toBeCloseTo(5, 9);
  });

  it('高さの幅が 0 なら 1 倍(0 除算にしない)', () => {
    expect(verticalExaggeration(10, 800, 0, 200)).toBe(1);
  });
});

describe('実タイル上で Python 参照実装と一致する(SPEC G-14)', () => {
  it.each(fixture.lines as any[])('$tile の断面が全点一致する', (line: any) => {
    const { lookup } = tileLookup(line.tile);
    const got = profileFrom(line.a[0], line.a[1], line.b[0], line.b[1], line.count, line.zoom, lookup);

    expect(got.length).toBe(line.samples.length);
    for (let k = 0; k < got.length; k++) {
      const want = line.samples[k];
      expect(got[k].lon).toBeCloseTo(want.lon, 9);
      expect(got[k].lat).toBeCloseTo(want.lat, 9);
      expect(got[k].distanceKm).toBeCloseTo(want.distance_km, 9);
      // 画素の添字は丸めではなく**同じ整数**でなければならない
      expect([got[k].i, got[k].j]).toEqual([want.i, want.j]);
      if (want.elevation === null) {
        expect(got[k].elevation).toBeNull();
      } else {
        expect(got[k].elevation).toBeCloseTo(want.elevation, 6);
      }
    }
  });

  it('全長と分解能もフィクスチャと一致する', () => {
    for (const line of fixture.lines as any[]) {
      expect(haversineKm(line.a[0], line.a[1], line.b[0], line.b[1])).toBeCloseTo(line.length_km, 9);
      const midLat = (line.a[1] + line.b[1]) / 2;
      expect(pixelResolutionM(line.zoom, midLat)).toBeCloseTo(line.pixel_resolution_m, 6);
    }
  });

  it('欠測を通る線が実在し、その点は null のまま', () => {
    // 欠測を一度も通らない線しか試していなければ、欠測の扱いは検査されていない
    const withGap = (fixture.lines as any[]).filter((l) => l.valid < l.count);
    expect(withGap.length).toBeGreaterThan(0);
    for (const line of withGap) {
      const { lookup } = tileLookup(line.tile);
      const got = profileFrom(line.a[0], line.a[1], line.b[0], line.b[1], line.count, line.zoom, lookup);
      expect(got.filter((s) => s.elevation !== null).length).toBe(line.valid);
      expect(got.filter((s) => s.elevation === null).length).toBe(line.count - line.valid);
    }
  });

  it('起伏の大きい線では標高が実際に動いている(平らな線で通していない)', () => {
    const line = (fixture.lines as any[])[0];
    const { lookup } = tileLookup(line.tile);
    const got = profileFrom(line.a[0], line.a[1], line.b[0], line.b[1], line.count, line.zoom, lookup);
    const vals = got.map((s) => s.elevation).filter((v): v is number => v !== null);
    expect(Math.max(...vals) - Math.min(...vals)).toBeGreaterThan(100);
    expect(Math.min(...vals)).toBeCloseTo(line.min_m, 6);
    expect(Math.max(...vals)).toBeCloseTo(line.max_m, 6);
  });
});
