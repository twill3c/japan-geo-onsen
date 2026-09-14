/**
 * 2 つの温泉を比べる表の中身(設計書 §57 / SPEC G-20)。
 *
 * 画面から切り離した純粋な関数にして、出荷データで検算する(tests-js/compare.test.ts)。
 *
 * 比較表は「どの行にも数が並ぶ」形に引っ張られやすい。けれど泉温・湧出量・pH・泉質は
 * 地点別の公開データが無い(SPEC G-03)。だから
 * - それらの行は「公開データに無い」と出す(0 や推定値を入れない)
 * - 欠けた値は「—」で、0 と取り違えない
 * - 差は両方に数があるときだけ出す
 */

export const UNAVAILABLE_LABEL = '公開データに無い';

/** 設計書 §57 の表の行の並び。画面もこの順で始める。 */
export const SPEC_ORDER = ['標高', '泉温', '湧出量', 'pH', '火山距離', '河川距離'];

type Kind = 'num' | 'text' | 'unavailable' | 'naturalness';
type RowDef = { key: string; label: string; kind: Kind; unit?: string };

const ROWS: RowDef[] = [
  // ---- 設計書 §57 の表と同じ順 ----
  { key: 'elevation_m', label: '標高', kind: 'num', unit: 'm' },
  { key: 'temperature_c', label: '泉温', kind: 'unavailable' },
  { key: 'discharge_l_min', label: '湧出量', kind: 'unavailable' },
  { key: 'ph', label: 'pH', kind: 'unavailable' },
  { key: 'distance_to_volcano_km', label: '火山距離', kind: 'num', unit: 'km' },
  { key: 'distance_to_river_km', label: '河川距離', kind: 'num', unit: 'km' },
  // ---- ここから、この地図が実データで持っているもの ----
  { key: 'spring_quality', label: '泉質', kind: 'unavailable' },
  { key: 'distance_to_lake_km', label: '湖沼距離', kind: 'num', unit: 'km' },
  { key: 'slope_deg', label: '傾斜', kind: 'num', unit: '°' },
  { key: 'local_relief_m', label: '局所起伏', kind: 'num', unit: 'm' },
  { key: 'nearest_volcano', label: '最寄りの活火山', kind: 'text' },
  { key: 'nearest_river', label: '最寄りの河川', kind: 'text' },
  { key: 'geology_group', label: '地質(大区分)', kind: 'text' },
  { key: 'geology_lithology', label: '岩相', kind: 'text' },
  { key: 'vegetation_naturalness', label: '植生自然度', kind: 'naturalness' },
  { key: 'prefecture', label: '所在都道府県', kind: 'text' },
];

export type CompareRow = {
  key: string;
  label: string;
  a: string;
  b: string;
  /** B − A。両方に数があるときだけ */
  diff: string | null;
  kind: 'value' | 'unavailable';
};

function asNumber(v: unknown): number | null {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  if (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v))) return Number(v);
  return null;
}

function isBlank(v: unknown): boolean {
  return v === null || v === undefined || v === '';
}

/** 小数 1 桁まで。末尾の 0 は付けない。 */
function fmt(v: number): string {
  const r = Math.round(v * 10) / 10;
  return (Object.is(r, -0) ? 0 : r).toLocaleString('ja-JP', { maximumFractionDigits: 1 });
}

function withUnit(s: string, unit?: string): string {
  return unit ? `${s} ${unit}` : s;
}

function signed(v: number, unit?: string): string {
  const r = Math.round(v * 10) / 10;
  if (r === 0) return withUnit('±0', unit);
  return withUnit(r > 0 ? `+${fmt(r)}` : `−${fmt(-r)}`, unit);
}

function cell(p: Record<string, unknown>, def: RowDef): string {
  const v = p[def.key];
  if (def.kind === 'unavailable') return isBlank(v) ? UNAVAILABLE_LABEL : String(v);
  if (isBlank(v)) return '—';
  if (def.kind === 'num') {
    const n = asNumber(v);
    return n === null ? '—' : withUnit(fmt(n), def.unit);
  }
  if (def.kind === 'naturalness') {
    const n = asNumber(v);
    const label = isBlank(p.vegetation_naturalness_label) ? '' : `（${String(p.vegetation_naturalness_label)}）`;
    return n === null ? '—' : `${n}${label}`;
  }
  return String(v);
}

export function compareRows(a: Record<string, unknown>, b: Record<string, unknown>): CompareRow[] {
  return ROWS.map((def) => {
    const ca = cell(a, def);
    const cb = cell(b, def);
    let diff: string | null = null;
    if (def.kind === 'num') {
      const na = asNumber(a[def.key]);
      const nb = asNumber(b[def.key]);
      if (na !== null && nb !== null && !isBlank(a[def.key]) && !isBlank(b[def.key])) {
        diff = signed(nb - na, def.unit);
      }
    }
    const unavailable = def.kind === 'unavailable' && ca === UNAVAILABLE_LABEL && cb === UNAVAILABLE_LABEL;
    return { key: def.key, label: def.label, a: ca, b: cb, diff, kind: unavailable ? 'unavailable' : 'value' };
  });
}

export type PrefStats = {
  prefectures: Array<{
    prefecture: string;
    sources_total: number;
    temp_under25: number;
    temp_25_42: number;
    temp_over42: number;
    temp_steam_gas: number;
  }>;
};

export type PrefReference = { prefecture: string; sourcesTotal: number; over42Share: number };

/**
 * 所在都道府県の集計(**この温泉の値ではない**)。
 *
 * 42℃以上の割合の分母は「温度の区分がある源泉」の合計。全国で温度の記録があるのは
 * 源泉総数の 88.4% しかないので、総数で割ると割合が低く出る。
 */
export function prefectureReference(prefecture: string | undefined, stats: PrefStats | null): PrefReference | null {
  if (!prefecture || !stats) return null;
  const row = stats.prefectures.find((p) => p.prefecture === prefecture);
  if (!row) return null;
  const denom = row.temp_under25 + row.temp_25_42 + row.temp_over42 + row.temp_steam_gas;
  if (!(denom > 0)) return null;
  return { prefecture, sourcesTotal: row.sources_total, over42Share: row.temp_over42 / denom };
}
