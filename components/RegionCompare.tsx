'use client';

/**
 * 地域を並べて比べる(設計書 §58)。
 *
 * 地域は「基準点 + 半径」で定める。境界を推測で描かないためである。
 * 設計書の 5 地域(八ヶ岳・富士山・箱根・草津・別府)を初期表示にし、
 * 気象庁の活火山 111 を基準点として足せるようにする。
 *
 * 色で区分を分ける図は使わない(植生の帯は 6 区分あり、既存の検証済みパレットは 4 色)。
 * 割合は**数字と単色の棒**で出す —— 色の見分けに頼らない。
 */
import { useEffect, useMemo, useState } from 'react';
import { haversineKm } from '@/lib/profile';

type Points = { ksj: number; wikidata: number; facility: number; wikipedia: number };
type Summary = {
  n: number;
  elevation_median_m: number | null;
  elevation_min_m: number | null;
  elevation_max_m: number | null;
  river_median_km: number | null;
  geology_share: Record<string, number>;
};
type ByRadius = {
  points: Points;
  coverage_note: string | null;
  volcanoes: number;
  lakes: number;
  vegetation_meshes: number;
  vegetation_share: Record<string, number>;
  onsen_summary: Summary;
};
export type Region = {
  id: string;
  label: string;
  kind: 'spec' | 'volcano';
  lon: number;
  lat: number;
  source: string;
  wikidata_id?: string;
  volcano_id?: string;
  nearest_volcano: { name: string; distance_km: number };
  by_radius: Record<string, ByRadius>;
};
type Doc = { radii_km: number[]; bands: string[]; regions: Region[] };

const n = (v: number) => v.toLocaleString('ja-JP');
const km = (v: number | null) => (v == null ? '—' : `${(Math.round(v * 10) / 10).toLocaleString('ja-JP')} km`);
const m = (v: number | null) => (v == null ? '—' : `${Math.round(v).toLocaleString('ja-JP')} m`);
const pct = (v: number | undefined) => (v == null ? '—' : `${(100 * v).toFixed(0)}%`);

function Bar({ share }: { share: number | undefined }) {
  const w = Math.max(0, Math.min(1, share ?? 0)) * 100;
  return (
    <span className="region-bar" aria-hidden="true">
      <span style={{ width: `${w}%` }} />
    </span>
  );
}

export default function RegionCompare() {
  const [doc, setDoc] = useState<Doc | null | undefined>(undefined);
  const [radius, setRadius] = useState('25');
  const [selected, setSelected] = useState<string[]>([]);
  const [adding, setAdding] = useState('');

  useEffect(() => {
    fetch('/data/regions.json')
      .then((r) => (r.ok ? (r.json() as Promise<Doc>) : null))
      .then((d) => {
        setDoc(d);
        if (d) setSelected(d.regions.filter((r) => r.kind === 'spec').map((r) => r.id));
      })
      .catch(() => setDoc(null));
  }, []);

  const byId = useMemo(() => new Map((doc?.regions ?? []).map((r) => [r.id, r])), [doc]);
  const cols = selected.map((id) => byId.get(id)).filter((r): r is Region => !!r);

  const overlaps = useMemo(() => {
    const out: { a: string; b: string; d: number }[] = [];
    const rad = Number(radius);
    for (let i = 0; i < cols.length; i++) {
      for (let j = i + 1; j < cols.length; j++) {
        const d = haversineKm(cols[i].lon, cols[i].lat, cols[j].lon, cols[j].lat);
        if (d < 2 * rad) out.push({ a: cols[i].label, b: cols[j].label, d });
      }
    }
    return out;
  }, [cols, radius]);

  if (doc === undefined) return <p className="status">地域のデータを読み込み中…</p>;
  if (doc === null) return <p className="status">地域のデータを取得できませんでした</p>;

  const volcanoes = doc.regions.filter((r) => r.kind === 'volcano' && !selected.includes(r.id));
  const s = (r: Region) => r.by_radius[radius];
  const geologyKeys = [...new Set(cols.flatMap((r) => Object.keys(s(r).onsen_summary.geology_share)))]
    .sort((x, y) => cols.reduce((t, r) => t + (s(r).onsen_summary.geology_share[y] ?? 0), 0)
      - cols.reduce((t, r) => t + (s(r).onsen_summary.geology_share[x] ?? 0), 0))
    .slice(0, 5);

  return (
    <div className="region-compare">
      <div className="region-controls">
        <label>
          半径{' '}
          <select value={radius} onChange={(e) => setRadius(e.target.value)}>
            {doc.radii_km.map((r) => <option key={r} value={String(r)}>{r} km</option>)}
          </select>
        </label>
        <label>
          活火山を基準点に足す{' '}
          <select value={adding} onChange={(e) => {
            const id = e.target.value;
            if (id) setSelected((prev) => [...prev, id]);
            setAdding('');
          }}>
            <option value="">（選ぶ）</option>
            {volcanoes.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
          </select>
        </label>
      </div>

      {overlaps.length > 0 && (
        <p className="hint">
          <strong>円が重なっている組があります</strong>（重なりの中の温泉は両方の地域で数えています）：
          {overlaps.map((o) => `${o.a}と${o.b}（基準点の間 ${km(o.d)}）`).join('、')}
        </p>
      )}

      <div className="table-scroll">
        <table className="region-table">
          <thead>
            <tr>
              <th />
              {cols.map((r) => (
                <th key={r.id} className="num">
                  {r.label}
                  <button type="button" className="remove" aria-label={`${r.label}を外す`}
                    onClick={() => setSelected((prev) => prev.filter((x) => x !== r.id))}>×</button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="group"><th colSpan={cols.length + 1}>基準点</th></tr>
            <tr>
              <th>基準点の出所</th>
              {cols.map((r) => <td key={r.id} className="num small">{r.source}</td>)}
            </tr>
            <tr>
              <th>最寄りの活火山</th>
              {cols.map((r) => (
                <td key={r.id} className="num small">
                  {r.nearest_volcano.name}（{km(r.nearest_volcano.distance_km)}）
                </td>
              ))}
            </tr>

            <tr className="group"><th colSpan={cols.length + 1}>円の中の点（出所ごと・足していない）</th></tr>
            {([['ksj', '温泉 P12'], ['wikidata', '温泉 WD'], ['facility', '入浴施設 WD'], ['wikipedia', '温泉記事 WP']] as [keyof Points, string][])
              .map(([key, label]) => (
                <tr key={key}>
                  <th>{label}</th>
                  {cols.map((r) => <td key={r.id} className="num">{n(s(r).points[key])}</td>)}
                </tr>
              ))}
            <tr>
              <th>注記</th>
              {cols.map((r) => <td key={r.id} className="num small">{s(r).coverage_note ?? ''}</td>)}
            </tr>

            <tr className="group"><th colSpan={cols.length + 1}>円の中の温泉（P12 だけで要約）</th></tr>
            <tr>
              <th>標高の中央値</th>
              {cols.map((r) => <td key={r.id} className="num">{m(s(r).onsen_summary.elevation_median_m)}</td>)}
            </tr>
            <tr>
              <th>標高の幅</th>
              {cols.map((r) => {
                const o = s(r).onsen_summary;
                return <td key={r.id} className="num small">{o.n ? `${m(o.elevation_min_m)}〜${m(o.elevation_max_m)}` : '—'}</td>;
              })}
            </tr>
            <tr>
              <th>河川距離の中央値</th>
              {cols.map((r) => <td key={r.id} className="num">{km(s(r).onsen_summary.river_median_km)}</td>)}
            </tr>
            {geologyKeys.map((g) => (
              <tr key={g}>
                <th>地質: {g}</th>
                {cols.map((r) => {
                  const o = s(r).onsen_summary;
                  return (
                    <td key={r.id} className="num">
                      {o.n ? <>{pct(o.geology_share[g] ?? 0)}<Bar share={o.geology_share[g] ?? 0} /></> : '—'}
                    </td>
                  );
                })}
              </tr>
            ))}

            <tr className="group"><th colSpan={cols.length + 1}>円の中の地理環境</th></tr>
            <tr>
              <th>活火山</th>
              {cols.map((r) => <td key={r.id} className="num">{n(s(r).volcanoes)}</td>)}
            </tr>
            <tr>
              <th>湖沼</th>
              {cols.map((r) => <td key={r.id} className="num">{n(s(r).lakes)}</td>)}
            </tr>
            {doc.bands.map((b) => (
              <tr key={b}>
                <th>植生 {b}</th>
                {cols.map((r) => (
                  <td key={r.id} className="num">
                    {pct(s(r).vegetation_share[b])}<Bar share={s(r).vegetation_share[b]} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
