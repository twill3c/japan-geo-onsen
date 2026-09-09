/**
 * 地形断面(標高プロファイル)。設計書 §56「地図上に線を引く → 標高断面図」。
 *
 * 標高タイルをその場で読んで断面を作る。サーバは持たない(SPEC F-12)。
 * Python 参照実装(etl/profile_ref.py)と**同じ入力に同じ出力**を返すことを
 * tests-js/profile.test.ts が実タイルで照合する(SPEC G-14)。
 *
 * ## 決めごと
 *
 * - **点の並べ方**: A→B を大円上で等間隔に刻む(球面線形補間)。
 *   平面で刻むと緯度の高い所で間隔が歪む
 * - **標高の引き方**: その点が入る画素の値を**そのまま**使う(最近傍)。
 *   周りと混ぜない —— 混ぜると元データに無い標高が図に出る
 *   (等高線で欠測セルを補間しないのと同じ理由)
 * - **刻みの細かさ**: 1 画素より細かくは刻まない。細かく刻んでも情報は増えず、
 *   「元データより細かく測れている」という誤解だけが増える
 * - **欠測**: 無効値(x=2^23)とタイルの無い場所は null。線は途切れさせる
 */
import { DEM } from './layers';
import { loadDemTile } from './contour-tiles';

/** 球の半径[km]。etl/common.py・etl/profile_ref.py と同じ球を使う。 */
export const R_KM = 6371.0088;

/** 1 本の断面で読む標高タイルの上限。超える長さでは段を粗くする。 */
export const PROFILE_MAX_TILES = 24;
/** 断面の点数の上限。図に描ける密度と、読むタイル数の両方の歯止め。 */
export const MAX_SAMPLES = 800;

/** 球面(半径 6371.0088 km)での大円距離[km]。 */
export function haversineKm(lon1: number, lat1: number, lon2: number, lat2: number): number {
  const p1 = (lat1 * Math.PI) / 180;
  const p2 = (lat2 * Math.PI) / 180;
  const dp = p2 - p1;
  const dl = ((lon2 - lon1) * Math.PI) / 180;
  const a = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * R_KM * Math.asin(Math.min(1, Math.sqrt(a)));
}

/** 大円上を A から B へ割合 t だけ進んだ点(球面線形補間)。 */
export function slerp(
  lon1: number, lat1: number, lon2: number, lat2: number, t: number,
): [number, number] {
  const p1 = (lat1 * Math.PI) / 180;
  const l1 = (lon1 * Math.PI) / 180;
  const p2 = (lat2 * Math.PI) / 180;
  const l2 = (lon2 * Math.PI) / 180;
  const d = 2 * Math.asin(Math.min(1, Math.sqrt(
    Math.sin((p2 - p1) / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin((l2 - l1) / 2) ** 2,
  )));
  if (d === 0) return [lon1, lat1];
  const a = Math.sin((1 - t) * d) / Math.sin(d);
  const b = Math.sin(t * d) / Math.sin(d);
  const x = a * Math.cos(p1) * Math.cos(l1) + b * Math.cos(p2) * Math.cos(l2);
  const y = a * Math.cos(p1) * Math.sin(l1) + b * Math.cos(p2) * Math.sin(l2);
  const z = a * Math.sin(p1) + b * Math.sin(p2);
  return [(Math.atan2(y, x) * 180) / Math.PI, (Math.atan2(z, Math.hypot(x, y)) * 180) / Math.PI];
}

/** Web メルカトルの世界画素座標(小数)。 */
export function worldPixel(lon: number, lat: number, z: number, tileSize = 256): [number, number] {
  const n = 2 ** z * tileSize;
  const px = ((lon + 180) / 360) * n;
  const rad = (lat * Math.PI) / 180;
  const py = ((1 - Math.asinh(Math.tan(rad)) / Math.PI) / 2) * n;
  return [px, py];
}

/** その緯度・その段の 1 画素が地上で何 m か。 */
export function pixelResolutionM(z: number, lat: number, tileSize = 256): number {
  return (2 * Math.PI * R_KM * 1000 * Math.cos((lat * Math.PI) / 180)) / (2 ** z * tileSize);
}

export type Position = { t: number; lon: number; lat: number; distanceKm: number };
export type Sample = Position & {
  tileX: number; tileY: number; i: number; j: number; elevation: number | null;
};

/** A→B を count 点に刻む。両端を含む。 */
export function samplePositions(
  lon1: number, lat1: number, lon2: number, lat2: number, count: number,
): Position[] {
  if (!Number.isFinite(count) || count < 2) {
    throw new Error(`断面の点は 2 点以上でなければならない: ${count}`);
  }
  const total = haversineKm(lon1, lat1, lon2, lat2);
  const out: Position[] = [];
  for (let k = 0; k < count; k++) {
    const t = k / (count - 1);
    const [lon, lat] = slerp(lon1, lat1, lon2, lat2, t);
    out.push({ t, lon, lat, distanceKm: total * t });
  }
  return out;
}

/** 断面。lookup が標高[m] または null(欠測)を返す。 */
export function profileFrom(
  lon1: number, lat1: number, lon2: number, lat2: number, count: number, z: number,
  lookup: (tileX: number, tileY: number, i: number, j: number) => number | null,
): Sample[] {
  return samplePositions(lon1, lat1, lon2, lat2, count).map((p) => {
    const [px, py] = worldPixel(p.lon, p.lat, z);
    const tileX = Math.floor(px / 256);
    const tileY = Math.floor(py / 256);
    const i = Math.floor(px) % 256;
    const j = Math.floor(py) % 256;
    return { ...p, tileX, tileY, i, j, elevation: lookup(tileX, tileY, i, j) };
  });
}

/**
 * 使う標高タイルの段を決める。
 *
 * 線に沿って必要になるタイル枚数を長さから見積もり、上限に収まる**いちばん細かい段**を選ぶ。
 * 斜めの線は見積もりより多くのタイルにまたがるので、実際の枚数は buildProfile で数え直す。
 */
export function chooseZoom(lengthKm: number, lat: number, budget = PROFILE_MAX_TILES): number {
  for (let z = DEM.maxzoom; z > DEM.minzoom; z--) {
    const tileKm = (pixelResolutionM(z, lat) * 256) / 1000;
    if (Math.ceil(lengthKm / tileKm) + 1 <= budget) return z;
  }
  return DEM.minzoom;
}

/** 点数。1 画素より細かくは刻まない(元データより細かく見せない)。 */
export function sampleCount(lengthKm: number, z: number, lat: number): number {
  const steps = Math.floor((lengthKm * 1000) / pixelResolutionM(z, lat));
  return Math.max(2, Math.min(MAX_SAMPLES, steps + 1));
}

/** 断面図の縦の誇張倍率(横の縮尺 ÷ 縦の縮尺)。 */
export function verticalExaggeration(
  lengthKm: number, widthPx: number, reliefM: number, heightPx: number,
): number {
  if (reliefM <= 0 || widthPx <= 0 || heightPx <= 0) return 1;
  const horizontal = (lengthKm * 1000) / widthPx;   // m/px
  const vertical = reliefM / heightPx;              // m/px
  return horizontal / vertical;
}

export type ProfileResult =
  | {
      ok: true;
      samples: Sample[];
      lengthKm: number;
      zoom: number;
      spacingM: number;
      pixelM: number;
      tiles: number;
      missingTiles: number;
      missingSamples: number;
      minM: number | null;
      maxM: number | null;
      reliefM: number;
      gainM: number;
      lossM: number;
    }
  | { ok: false; reason: string };

/** A→B の断面を作る。標高タイルは表示範囲と同じ経路で取り、キャッシュを共有する。 */
export async function buildProfile(
  a: [number, number], b: [number, number],
): Promise<ProfileResult> {
  const lengthKm = haversineKm(a[0], a[1], b[0], b[1]);
  if (!(lengthKm > 0)) return { ok: false, reason: '始点と終点が同じ位置です' };

  const midLat = (a[1] + b[1]) / 2;
  let z = chooseZoom(lengthKm, midLat);
  let positions = samplePositions(a[0], a[1], b[0], b[1], sampleCount(lengthKm, z, midLat));
  let keys = tileKeys(positions, z);
  // 斜めの線は見積もりより多くのタイルをまたぐ。実際に数えて、超えていれば段を粗くする
  while (keys.length > PROFILE_MAX_TILES && z > DEM.minzoom) {
    z -= 1;
    positions = samplePositions(a[0], a[1], b[0], b[1], sampleCount(lengthKm, z, midLat));
    keys = tileKeys(positions, z);
  }
  if (keys.length > PROFILE_MAX_TILES) {
    return { ok: false, reason: `この長さでは標高タイルが ${keys.length} 枚必要です(上限 ${PROFILE_MAX_TILES} 枚)。線を短くしてください` };
  }

  const loaded = new Map<string, (number | null)[] | null>();
  await Promise.all(keys.map(async (k) => {
    const [x, y] = k.split('/').map(Number);
    loaded.set(k, await loadDemTile(z, x, y));
  }));
  const missingTiles = [...loaded.values()].filter((v) => v === null).length;
  if (missingTiles === loaded.size) return { ok: false, reason: '標高タイルを取得できませんでした' };

  const samples = profileFrom(
    a[0], a[1], b[0], b[1], positions.length, z,
    (tx, ty, i, j) => {
      const tile = loaded.get(`${tx}/${ty}`);
      return tile ? tile[j * 256 + i] : null;
    },
  );

  const vals = samples.map((s) => s.elevation).filter((v): v is number => v !== null);
  let gainM = 0;
  let lossM = 0;
  for (let k = 1; k < samples.length; k++) {
    const p = samples[k - 1].elevation;
    const c = samples[k].elevation;
    if (p === null || c === null) continue;   // 欠測をまたいだ差はとらない
    if (c > p) gainM += c - p; else lossM += p - c;
  }

  return {
    ok: true,
    samples,
    lengthKm,
    zoom: z,
    spacingM: (lengthKm * 1000) / (samples.length - 1),
    pixelM: pixelResolutionM(z, midLat),
    tiles: loaded.size,
    missingTiles,
    missingSamples: samples.length - vals.length,
    minM: vals.length ? Math.min(...vals) : null,
    maxM: vals.length ? Math.max(...vals) : null,
    reliefM: vals.length ? Math.max(...vals) - Math.min(...vals) : 0,
    gainM,
    lossM,
  };
}

function tileKeys(positions: Position[], z: number): string[] {
  const set = new Set<string>();
  for (const p of positions) {
    const [px, py] = worldPixel(p.lon, p.lat, z);
    set.add(`${Math.floor(px / 256)}/${Math.floor(py / 256)}`);
  }
  return [...set];
}
