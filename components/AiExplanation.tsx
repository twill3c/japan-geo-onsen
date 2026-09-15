'use client';

/**
 * 温泉ごとの AI の見立て(設計書 §35)。
 *
 * 設計書の例は「温泉存在可能性 82%」だが、このモデルが当てているのは
 * 「P12 に登録された地点が温泉の分類か」で、出力も確率に較正していない。
 * だから % にせず、**何を当てたモデルの、どのモデルの出力か**を先に書く。
 *
 * 出力と寄与は、その温泉の都道府県を学習に使っていないモデルのもの(out-of-fold)。
 * データは点を開いたときに初めて読む。
 */
import { useEffect, useState } from 'react';

type Doc = {
  features: string[];
  base_by_fold: Record<string, number>;
  points: Record<string, { score: number; contrib: number[]; fold: number; prefecture: string }>;
};

const LABEL: Record<string, string> = {
  elevation_m: '標高',
  slope_deg: '傾斜',
  local_relief_m: '局所起伏',
  distance_to_volcano_km: '活火山までの距離',
  distance_to_river_km: '河川までの距離',
  distance_to_lake_km: '湖沼までの距離',
  vegetation_naturalness: '植生自然度',
  geology_group: '地質の大区分',
};

/** 設計書 §36 の AI 免責。文言を変えない。 */
const AI_DISCLAIMER =
  'この結果は公開データから学習した統計モデルによる推定です。温泉の存在・泉質・湧出量を保証するものではありません。';

let cache: Promise<Doc | null> | null = null;
function load(): Promise<Doc | null> {
  if (!cache) {
    cache = fetch('/data/ai/explanations_onsen.json')
      .then((r) => (r.ok ? (r.json() as Promise<Doc>) : null))
      .catch(() => null);
  }
  return cache;
}

export default function AiExplanation({ provenance, onsenId }: { provenance: unknown; onsenId: unknown }) {
  const isKsj = provenance == null || provenance === 'ksj-p12';
  const [doc, setDoc] = useState<Doc | null | undefined>(undefined);

  useEffect(() => {
    if (!isKsj) return;
    let alive = true;
    load().then((d) => { if (alive) setDoc(d); });
    return () => { alive = false; };
  }, [isKsj]);

  if (!isKsj) {
    return (
      <p className="hint">
        この層の点は AI の学習に使っていないので、AI の見立ては出していません
        （学習に使ったのは国土数値情報の温泉だけです）。
      </p>
    );
  }
  if (doc === undefined) return <p className="status">AI の見立てを読み込み中…</p>;
  const p = doc && onsenId != null ? doc.points[String(onsenId)] : undefined;
  if (!doc || !p) return <p className="hint">この点の AI の見立てはありません。</p>;

  const items = doc.features
    .map((f, i) => ({ f, v: p.contrib[i] }))
    .sort((a, b) => Math.abs(b.v) - Math.abs(a.v));
  const top = items.slice(0, 4);
  const maxAbs = Math.max(...items.map((x) => Math.abs(x.v)), 1e-9);

  return (
    <div className="ai-explain">
      <p className="ai-question">
        このモデルは<strong>「観光資源データに登録された地点が温泉の分類か」</strong>を当てるものです。
        温泉が湧くかどうかを当てるものではありません。
      </p>
      <table>
        <tbody>
          <tr>
            <th>モデルの出力</th>
            <td>
              <strong>{p.score.toFixed(2)}</strong>
              <span className="ai-score"><span style={{ width: `${Math.round(p.score * 100)}%` }} /></span>
            </td>
          </tr>
        </tbody>
      </table>
      <p className="hint">
        0〜1 の値で、<strong>確率ではありません</strong>。温泉の分類で登録された地点の地理環境に
        どれだけ似ているかを示します。{p.prefecture}を学習に使っていないモデルの出力です
        （学習に使ったモデルだと、点を覚えて 1 に近い値が出るため）。
      </p>
      <h5>出力を押し上げた・押し下げた特徴量（SHAP・大きい順に 4 つ）</h5>
      <table className="ai-contrib">
        <tbody>
          {top.map(({ f, v }) => (
            <tr key={f}>
              <th>{LABEL[f] ?? f}</th>
              <td className="num">{v >= 0 ? '+' : '−'}{Math.abs(v).toFixed(3)}</td>
              <td className="bar">
                <span className={v >= 0 ? 'up' : 'down'} style={{ width: `${(Math.abs(v) / maxAbs) * 100}%` }} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="hint">
        ＋は温泉の分類に近づける向き、−は遠ざける向き。すべての特徴量の寄与を足すと、
        基準値（{doc.base_by_fold[String(p.fold)].toFixed(2)}）から出力までの差になります。
        効いているのは<strong>「温泉として登録された場所」との結び付き</strong>で、温泉が湧く原因ではありません。
      </p>
      <p className="ai-disclaimer small" role="note">{AI_DISCLAIMER}</p>
    </div>
  );
}
