/**
 * 温泉比較の検算(SPEC G-20 / 設計書 §57)。
 *
 * 設計書の比較表には 泉温・湧出量・pH が並んでいる。けれど地点別の公開データは無い
 * (SPEC G-03)。比較画面は**表の形に引っ張られて数を作りやすい**場所なので、
 * 次を検査で固定する。
 *
 * - 公開データに無い項目は、どちらの温泉でも「公開データに無い」と出す(数を作らない)
 * - 値が欠けている項目は「—」で、0 と取り違えない
 * - 差は両方に数があるときだけ出す
 * - 都道府県の集計は「この温泉の値ではない」参考として別に出し、所在県が無い点では出さない
 *
 * 入力は出荷している実データを使う(4 層すべて)。
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { compareRows, prefectureReference, SPEC_ORDER, UNAVAILABLE_LABEL } from '../lib/compare';

const read = (f: string) => JSON.parse(readFileSync(new URL(`../public/data/${f}`, import.meta.url), 'utf8'));
const layers = {
  ksj: read('onsen.geojson'),
  wikidata: read('onsen_wikidata.geojson'),
  facility: read('onsen_facility.geojson'),
  wikipedia: read('onsen_wikipedia.geojson'),
};
const stats = read('onsen_stats.json');
const props = (fc: any, i = 0) => fc.features[i].properties as Record<string, unknown>;

describe('比較表の形(設計書 §57)', () => {
  it('設計書の表と同じ順で始まる', () => {
    const rows = compareRows(props(layers.ksj, 0), props(layers.ksj, 1));
    const head = rows.slice(0, SPEC_ORDER.length).map((r) => r.label);
    expect(head).toEqual(SPEC_ORDER);
    expect(SPEC_ORDER).toEqual(['標高', '泉温', '湧出量', 'pH', '火山距離', '河川距離']);
  });

  it('行の鍵が重複しない', () => {
    const rows = compareRows(props(layers.ksj, 0), props(layers.ksj, 1));
    const keys = rows.map((r) => r.key);
    expect(new Set(keys).size).toBe(keys.length);
  });
});

describe('数を作らない(SPEC G-03 / G-20)', () => {
  it('泉温・湧出量・pH・泉質は、4 層どの組でも「公開データに無い」', () => {
    const picks = Object.values(layers).map((fc) => props(fc, 0));
    for (const a of picks) {
      for (const b of picks) {
        const rows = compareRows(a, b);
        for (const label of ['泉温', '湧出量', 'pH', '泉質']) {
          const r = rows.find((x) => x.label === label)!;
          expect(r, label).toBeDefined();
          expect(r.kind).toBe('unavailable');
          expect(r.a).toBe(UNAVAILABLE_LABEL);
          expect(r.b).toBe(UNAVAILABLE_LABEL);
          expect(r.diff).toBeNull();
        }
      }
    }
  });

  it('値が欠けた項目は「—」で、0 と取り違えない', () => {
    const rows = compareRows({ elevation_m: null }, { elevation_m: 0 });
    const r = rows.find((x) => x.key === 'elevation_m')!;
    expect(r.a).toBe('—');
    expect(r.b).toBe('0 m');
    expect(r.diff).toBeNull();
  });

  it('差は両方に数があるときだけ、B − A の向きで出す', () => {
    const rows = compareRows(
      { elevation_m: 620, distance_to_volcano_km: 18 },
      { elevation_m: 850, distance_to_volcano_km: 7 },
    );
    expect(rows.find((x) => x.key === 'elevation_m')!.diff).toBe('+230 m');
    expect(rows.find((x) => x.key === 'distance_to_volcano_km')!.diff).toBe('−11 km');
  });

  it('実データのどの組でも、表示に NaN・undefined・null の文字が出ない', () => {
    const picks = Object.values(layers).flatMap((fc) => [props(fc, 0), props(fc, fc.features.length - 1)]);
    for (const a of picks) {
      for (const b of picks) {
        for (const r of compareRows(a, b)) {
          for (const s of [r.a, r.b, r.diff ?? '']) {
            expect(s).not.toMatch(/NaN|undefined|null|Infinity/);
          }
        }
      }
    }
  });
});

describe('都道府県の集計は参考として別に出す', () => {
  it('所在県の 42℃以上の割合を、温度の区分がある源泉から計算する', () => {
    const hk = stats.prefectures.find((p: any) => p.prefecture === '北海道');
    const ref = prefectureReference('北海道', stats)!;
    const denom = hk.temp_under25 + hk.temp_25_42 + hk.temp_over42 + hk.temp_steam_gas;
    expect(ref.sourcesTotal).toBe(hk.sources_total);
    expect(ref.over42Share).toBeCloseTo(hk.temp_over42 / denom, 12);
    // 出典: 環境省 令和6年度温泉利用状況。北海道は 1,086 / (207+487+1,086+2)
    expect(ref.over42Share).toBeCloseTo(1086 / 1782, 12);
  });

  it('所在県を持たない点(Wikipedia の層など)では出さない', () => {
    expect('prefecture' in props(layers.wikipedia)).toBe(false);
    expect(prefectureReference(undefined, stats)).toBeNull();
    expect(prefectureReference('存在しない県', stats)).toBeNull();
  });
});
