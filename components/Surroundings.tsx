'use client';

/**
 * 温泉のまわり 5/10/25/50 km に何があるか(設計書 §56「周辺環境分析」)。
 *
 * 数は点ファイルに入れず、**点を開いたときに初めて読む**別ファイルにしてある
 * (public/data/surroundings/<層>.json)。起動時に配る量を増やさないため。
 * 同じ層のファイルは一度読んだら使い回す。
 */
import { useEffect, useState } from 'react';

export type Doc = {
  radii_km: number[];
  columns: string[];
  rows: Record<string, number[][]>;
};

export const FILE_OF: Record<string, string> = {
  'ksj-p12': 'onsen',
  wikidata: 'onsen_wikidata',
  'wikidata-facility': 'onsen_facility',
  wikipedia: 'onsen_wikipedia',
};

const cache = new Map<string, Promise<Doc | null>>();

export function load(name: string): Promise<Doc | null> {
  let p = cache.get(name);
  if (!p) {
    p = fetch(`/data/surroundings/${name}.json`)
      .then((r) => (r.ok ? (r.json() as Promise<Doc>) : null))
      .catch(() => null);
    cache.set(name, p);
  }
  return p;
}

// 行見出しは短くし、定義は下の注記に書く。パネルは 320px しかなく、
// 「温泉（国土数値情報）」のままだと 3 行に折れて表が読めなかった(撮影で確認)
const LABELS: [string, string][] = [
  ['volcanoes', '活火山'],
  ['onsen_ksj', '温泉 P12'],
  ['onsen_wikidata', '温泉 WD'],
  ['lakes', '湖沼'],
];

const BAND_SHORT: Record<string, string> = {
  '1〜2(市街地・農耕地)': '市街地・農耕地',
  '3〜5(樹園地・二次草原)': '樹園地・二次草原',
  '6(植林地)': '植林地',
  '7〜8(二次林)': '二次林',
  '9〜10(自然林・自然草原)': '自然林・自然草原',
  'その他(裸地・水域)': '裸地・水域',
};

export default function Surroundings({ provenance, onsenId }: { provenance: unknown; onsenId: unknown }) {
  const name = FILE_OF[String(provenance ?? 'ksj-p12')] ?? 'onsen';
  const id = onsenId == null ? null : String(onsenId);
  const [doc, setDoc] = useState<Doc | null | undefined>(undefined);

  useEffect(() => {
    let alive = true;
    setDoc(undefined);
    load(name).then((d) => { if (alive) setDoc(d); });
    return () => { alive = false; };
  }, [name]);

  if (doc === undefined) return <p className="status">まわりの数を読み込み中…</p>;
  const rows = doc && id ? doc.rows[id] : undefined;
  if (!doc || !rows) return <p className="hint">この点のまわりの数はありません。</p>;

  const col = (key: string) => doc.columns.indexOf(key);
  const bands = doc.columns.filter((c) => c in BAND_SHORT);
  const meshCol = col('vegetation_meshes');

  return (
    <div className="surroundings">
      <table>
        <thead>
          <tr>
            <th>半径</th>
            {doc.radii_km.map((r) => <th key={r} className="num">{r} km</th>)}
          </tr>
        </thead>
        <tbody>
          {LABELS.map(([key, label]) => (
            <tr key={key}>
              <th>{label}</th>
              {rows.map((row, i) => <td key={i} className="num">{row[col(key)].toLocaleString('ja-JP')}</td>)}
            </tr>
          ))}
          <tr>
            <th>自然林の割合</th>
            {rows.map((row, i) => {
              const total = row[meshCol];
              const nat = row[col('9〜10(自然林・自然草原)')];
              return (
                <td key={i} className="num">
                  {total > 0 ? `${Math.round((100 * nat) / total)}%` : '—'}
                </td>
              );
            })}
          </tr>
        </tbody>
      </table>
      <details>
        <summary>植生自然度の内訳（メッシュの数）</summary>
        <table>
          <thead>
            <tr>
              <th>帯</th>
              {doc.radii_km.map((r) => <th key={r} className="num">{r} km</th>)}
            </tr>
          </thead>
          <tbody>
            {bands.map((b) => (
              <tr key={b}>
                <th>{BAND_SHORT[b]}</th>
                {rows.map((row, i) => <td key={i} className="num">{row[col(b)].toLocaleString('ja-JP')}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </details>
      <p className="hint">
        温泉 P12 = 国土数値情報 観光資源データ、温泉 WD = Wikidata の温泉。
        自然林の割合 = 植生自然度 9〜10（自然林・自然草原）のメッシュが半径内に占める割合。
      </p>
      <p className="hint">
        中心からの大円距離で数えています（自分自身は除く）。湖沼は面の縁までの距離、
        植生は約 1 km メッシュの中心が半径内に入るものです。
        <strong>河川と標高の起伏は数えていません</strong>（全区間・全画素を半径ごとに走査する計算量のため。
        最寄りの河川までの距離は上の表にあります）。
      </p>
    </div>
  );
}
