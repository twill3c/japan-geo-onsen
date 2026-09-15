/**
 * クリックで拾った点の候補を並べる(SPEC G-24)。
 *
 * 点が重なっていると、画素 1 点の問い合わせでは上に描かれた層の点しか選べず、下の層に届かない。
 * 1 つの層を優先すると別の層が隠れるので、**候補が複数なら一覧を出して選ばせる**。
 * 画面から切り離した純粋な関数にして、tests-js/pick.test.ts で検算する。
 */

/** 距離が同じときの並び。統計の母集団(国土数値情報)を先に置き、火山を最後にする。 */
export const LAYER_ORDER = ['onsen', 'onsen-wd', 'onsen-fac', 'onsen-wp', 'volcano'];

export type RawHit = {
  layerId: string;
  properties: Record<string, unknown>;
  /** その地物の画面上の位置(px) */
  px: [number, number];
};

export type Candidate = {
  /** 層 + ID(ID が無ければ名前と位置)。同じ地物の二重返りを落とす鍵 */
  key: string;
  layerId: string;
  name: string;
  properties: Record<string, unknown>;
  distancePx: number;
};

function keyOf(h: RawHit): string {
  const id = h.properties.onsen_id ?? h.properties.volcano_id;
  if (id !== undefined && id !== null && id !== '') return `${h.layerId}:${String(id)}`;
  return `${h.layerId}:${String(h.properties.name ?? '')}@${Math.round(h.px[0])},${Math.round(h.px[1])}`;
}

function layerRank(layerId: string): number {
  const i = LAYER_ORDER.indexOf(layerId);
  return i < 0 ? LAYER_ORDER.length : i;
}

export function collectCandidates(hits: RawHit[], click: [number, number], radiusPx: number): Candidate[] {
  const seen = new Map<string, Candidate>();
  for (const h of hits) {
    const d = Math.hypot(h.px[0] - click[0], h.px[1] - click[1]);
    if (d > radiusPx) continue;
    const key = keyOf(h);
    const prev = seen.get(key);
    if (prev && prev.distancePx <= d) continue;
    seen.set(key, {
      key,
      layerId: h.layerId,
      name: h.properties.name == null || h.properties.name === '' ? '(名称なし)' : String(h.properties.name),
      properties: h.properties,
      distancePx: d,
    });
  }
  return [...seen.values()].sort((a, b) =>
    a.distancePx - b.distancePx
    || layerRank(a.layerId) - layerRank(b.layerId)
    || a.name.localeCompare(b.name, 'ja'));
}

/** 2 件以上なら一覧を出す。1 件はそのまま開き、0 件は何も出さない。 */
export function needsChooser(candidates: Candidate[]): boolean {
  return candidates.length > 1;
}

/**
 * 地図に描く点の半径の段(縮尺 → px)。**地図の描画(MapView の circle-radius)もここを使う**。
 * 「押した位置の下にあるか」を描画と別の数で判定すると、見た目と選ばれ方が食い違う。
 */
export const RADIUS_STOPS: Record<'onsen' | 'volcano', [number, number][]> = {
  onsen: [[5, 2.4], [10, 4.6], [14, 7]],
  volcano: [[5, 3.2], [10, 6.5], [14, 9]],
};

/** MapLibre の ['interpolate', ['linear'], ['zoom'], ...] と同じ線形補間(段の外は端の値)。 */
export function dotRadiusPx(layerId: string, zoom: number): number {
  const stops = layerId === 'volcano' ? RADIUS_STOPS.volcano : RADIUS_STOPS.onsen;
  if (zoom <= stops[0][0]) return stops[0][1];
  for (let i = 1; i < stops.length; i++) {
    const [z1, r1] = stops[i];
    if (zoom <= z1) {
      const [z0, r0] = stops[i - 1];
      return r0 + ((zoom - z0) / (z1 - z0)) * (r1 - r0);
    }
  }
  return stops[stops.length - 1][1];
}

/**
 * 押した位置で選ぶ候補。
 *
 * 当たり判定を広げる理由は二つあり、答えが別である(HC-290)。
 * - **重なりを解く**: 一覧にするのは**カーソルの下に重なっている点**だけ。「下にある」かどうかは
 *   **地図の描画系そのもの**に問う(画素 1 点の queryRenderedFeatures が返す全件 = `under`)
 * - **押し損ねを許す**: 下に何も無いときに限り、周りの箱で拾った点(`near`)のうち最寄りの 1 点
 *
 * 経緯: 箱で集めた点をそのまま一覧にすると、1 つの点を押しても近くの点が入った(縮尺 9.2 で 40 点中 6 点)。
 * 次に「下にある」を描画と同じ段から計算した半径 + 1px で判定したが、描画系の当たり判定と 1px 前後ずれて
 * 40 点中 10 点で一覧が出た。判定を自前で計算するのをやめ、描画系の答えを使う。
 */
export function pickCandidates(
  under: RawHit[], near: RawHit[], click: [number, number], nearRadiusPx: number,
): Candidate[] {
  if (under.length > 0) return collectCandidates(under, click, Number.POSITIVE_INFINITY);
  const around = collectCandidates(near, click, nearRadiusPx);
  return around.length > 0 ? [around[0]] : [];
}

/** MapLibre の circle-radius に渡す式を段から作る。 */
export function radiusExpression(layer: 'onsen' | 'volcano'): unknown[] {
  return ['interpolate', ['linear'], ['zoom'], ...RADIUS_STOPS[layer].flat()];
}
