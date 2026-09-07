/**
 * 表示範囲の標高タイルを集めて 1 枚の格子にし、等高線 GeoJSON を作る。
 *
 * タイルを 1 枚ずつ処理すると縁で線が切れるので、範囲の全タイルを継ぎ合わせてから引く。
 * 取れなかったタイル(海域など 404)は欠測のままにする —— 埋めない。
 */
import { DEM } from './layers';
import { contours, decodeTile, levelsFor, tileXToLon, tileYToLat, type Grid } from './dem';

export type Bounds = { west: number; south: number; east: number; north: number };

/** 一度に扱うタイル枚数の上限。超えたら等高線を出さずに理由を返す。 */
export const MAX_TILES = 20;
/** 継ぎ合わせた格子をこの大きさ以下に間引いてから走査する。 */
export const MAX_GRID = 640;

const cache = new Map<string, (number | null)[] | null>();

async function loadTile(z: number, x: number, y: number): Promise<(number | null)[] | null> {
  const key = `${z}/${x}/${y}`;
  const hit = cache.get(key);
  if (hit !== undefined) return hit;
  const url = DEM.url.replace('{z}', String(z)).replace('{x}', String(x)).replace('{y}', String(y));
  try {
    const res = await fetch(url, { mode: 'cors' });
    if (!res.ok) { cache.set(key, null); return null; }
    const bmp = await createImageBitmap(await res.blob());
    const canvas = document.createElement('canvas');
    canvas.width = 256; canvas.height = 256;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) { cache.set(key, null); return null; }
    ctx.drawImage(bmp, 0, 0);
    const grid = decodeTile(ctx.getImageData(0, 0, 256, 256).data, 256);
    cache.set(key, grid);
    return grid;
  } catch {
    cache.set(key, null);
    return null;
  }
}

export type ContourResult =
  | { ok: true; geojson: GeoJSON.FeatureCollection; levels: number[]; tiles: number; missing: number; zoom: number; stride: number }
  | { ok: false; reason: string };

export function demZoomFor(mapZoom: number): number {
  return Math.max(DEM.minzoom, Math.min(DEM.maxzoom, Math.floor(mapZoom)));
}

export async function buildContours(bounds: Bounds, mapZoom: number, interval: number): Promise<ContourResult> {
  const z = demZoomFor(mapZoom);
  const n = 2 ** z;
  const toX = (lon: number) => Math.floor(((lon + 180) / 360) * n);
  const toY = (lat: number) => {
    const rad = (lat * Math.PI) / 180;
    return Math.floor(((1 - Math.asinh(Math.tan(rad)) / Math.PI) / 2) * n);
  };
  const x0 = Math.max(0, toX(bounds.west));
  const x1 = Math.min(n - 1, toX(bounds.east));
  const y0 = Math.max(0, toY(bounds.north));
  const y1 = Math.min(n - 1, toY(bounds.south));
  const nx = x1 - x0 + 1;
  const ny = y1 - y0 + 1;
  if (nx <= 0 || ny <= 0) return { ok: false, reason: '表示範囲が日本の外にあります' };
  if (nx * ny > MAX_TILES) {
    return { ok: false, reason: `この範囲では標高タイルが ${nx * ny} 枚必要です(上限 ${MAX_TILES} 枚)。拡大してください` };
  }

  const tiles = await Promise.all(
    Array.from({ length: nx * ny }, (_, k) => loadTile(z, x0 + (k % nx), y0 + Math.floor(k / nx))),
  );
  const missing = tiles.filter((t) => t === null).length;
  if (missing === tiles.length) return { ok: false, reason: '標高タイルを取得できませんでした' };

  const fullW = nx * 256;
  const fullH = ny * 256;
  const stride = Math.max(1, Math.ceil(Math.max(fullW, fullH) / MAX_GRID));
  const w = Math.floor((fullW - 1) / stride) + 1;
  const h = Math.floor((fullH - 1) / stride) + 1;

  const zbuf = new Array<number | null>(w * h);
  for (let j = 0; j < h; j++) {
    const fj = j * stride;
    const ty = Math.floor(fj / 256);
    for (let i = 0; i < w; i++) {
      const fi = i * stride;
      const tx = Math.floor(fi / 256);
      const tile = tiles[ty * nx + tx];
      zbuf[j * w + i] = tile ? tile[(fj % 256) * 256 + (fi % 256)] : null;
    }
  }

  const grid: Grid = {
    w, h, z: zbuf,
    toLonLat: (i, j) => [
      tileXToLon(x0 + (i * stride) / 256, z),
      tileYToLat(y0 + (j * stride) / 256, z),
    ],
  };

  const levels = levelsFor(grid, interval);
  const byLevel = contours(grid, levels);
  const features: GeoJSON.Feature[] = [];
  for (const [level, segs] of byLevel) {
    if (segs.length === 0) continue;
    features.push({
      type: 'Feature',
      geometry: { type: 'MultiLineString', coordinates: segs },
      // 主曲線(間隔の 5 倍ごと)を太く描くための印
      properties: { level, major: Math.abs(level % (interval * 5)) < 1e-6 },
    });
  }
  return {
    ok: true,
    geojson: { type: 'FeatureCollection', features },
    levels, tiles: tiles.length, missing, zoom: z, stride,
  };
}
