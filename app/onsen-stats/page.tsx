import { readFileSync } from 'node:fs';
import path from 'node:path';
import type { Metadata } from 'next';
import StackedBar from '@/components/StackedBar';

export const metadata: Metadata = {
  title: '温泉の統計（都道府県別） — 日本列島 自然環境・温泉GIS',
  description:
    '環境省の温泉利用状況から、源泉数・温度別源泉数・湧出量を都道府県別に出す。地点別の泉温は公開されていないが、都道府県別なら実データがある。',
};

type Pref = {
  prefecture: string;
  onsen_areas: number;
  sources_total: number;
  used_self_flowing: number;
  used_pumped: number;
  unused_self_flowing: number;
  unused_pumped: number;
  temp_under25: number;
  temp_25_42: number;
  temp_over42: number;
  temp_steam_gas: number;
  discharge_total: number;
  discharge_self_flowing: number;
  discharge_pumped: number;
  lodging_facilities: number;
};

type Stats = {
  source: string;
  dataset: string;
  source_url: string;
  license: string;
  download_date: string;
  processing_method: string;
  source_mismatches: {
    prefecture: string; sum_of_parts: number; stated_total: number; difference: number;
  }[];
  national: Record<string, number>;
  temperature_coverage: number;
  prefectures: Pref[];
  coverage: {
    points_total: number;
    onsen_areas_total: number;
    sources_total: number;
    points_per_onsen_area: number;
    prefectures_with_zero_points: string[];
    rows: { prefecture: string; points: number; onsen_areas: number; sources_total: number }[];
  };
};

function load(): Stats {
  return JSON.parse(
    readFileSync(path.join(process.cwd(), 'public', 'data', 'onsen_stats.json'), 'utf8'),
  ) as Stats;
}

const n = (v: number) => v.toLocaleString('ja-JP');

export default function OnsenStatsPage() {
  const s = load();
  const nat = s.national;
  const tempTotal = nat.temp_under25 + nat.temp_25_42 + nat.temp_over42 + nat.temp_steam_gas;

  // 温度別の多い順に県を並べる用（42度以上の割合）
  const hot = [...s.prefectures]
    .map((p) => {
      const t = p.temp_under25 + p.temp_25_42 + p.temp_over42 + p.temp_steam_gas;
      return { ...p, tempKnown: t, hotShare: t > 0 ? (100 * p.temp_over42) / t : null };
    })
    .filter((p) => p.tempKnown >= 50)
    .sort((a, b) => (b.hotShare ?? 0) - (a.hotShare ?? 0));

  return (
    <div className="prose">
      <h2>泉温と湧出量は、都道府県別になら実データがある</h2>
      <p>
        この地図は温泉の泉質・泉温・湧出量を<strong>地点ごとには出せません</strong>。
        そういう全国の公開データが無いからです（<a href="/about/">調べた範囲</a>）。
        ただし<strong>都道府県ごとの集計</strong>なら環境省が毎年公表しています。
        このページはそれを読んだものです。
      </p>

      <h2>全国の数</h2>
      <div className="table-scroll">
        <table>
          <tbody>
            <tr><th>源泉の総数</th><td>{n(nat.sources_total)}</td></tr>
            <tr><th>うち温度の記録があるもの</th><td>{n(tempTotal)}（{(100 * s.temperature_coverage).toFixed(1)}%）</td></tr>
            <tr><th>湧出量の合計</th><td>{n(nat.discharge_total_l_per_min)} L/分</td></tr>
            <tr><th>温泉地の数</th><td>{n(nat.onsen_areas)}</td></tr>
            <tr><th>宿泊施設の数</th><td>{n(nat.lodging_facilities)}</td></tr>
          </tbody>
        </table>
      </div>
      <p className="hint">
        源泉の <strong>{(100 * (1 - s.temperature_coverage)).toFixed(1)}%</strong> は温度別の区分に入っていません。
        温度が測られていない源泉があるということです。以下の割合はすべて
        「温度の記録がある源泉」を分母にしています。
      </p>

      <h2>温度別の源泉数（全国）</h2>
      <StackedBar
        segments={[
          { label: '25 度未満', value: nat.temp_under25 },
          { label: '25〜42 度', value: nat.temp_25_42 },
          { label: '42 度以上', value: nat.temp_over42 },
          { label: '水蒸気・ガス', value: nat.temp_steam_gas },
        ]}
      />
      <p>
        温度の記録がある {n(tempTotal)} 源泉のうち、
        <strong>{((100 * nat.temp_over42) / tempTotal).toFixed(1)}% が 42 度以上</strong>です。
        いわゆる「そのまま入れる湯」の割合にあたります。
      </p>

      <h2>42 度以上の割合が高い都道府県</h2>
      <p className="hint">
        温度の記録が 50 源泉以上ある県だけを並べています（{hot.length} 県）。
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr><th>都道府県</th><th>42 度以上</th><th>温度の記録がある源泉</th><th>源泉総数</th><th>湧出量 L/分</th></tr>
          </thead>
          <tbody>
            {hot.slice(0, 12).map((p) => (
              <tr key={p.prefecture}>
                <td>{p.prefecture}</td>
                <td>{p.hotShare?.toFixed(1)}%</td>
                <td>{n(p.tempKnown)}</td>
                <td>{n(p.sources_total)}</td>
                <td>{n(p.discharge_total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>地図の点は、温泉の一覧ではない</h2>
      <p>
        地図に出している温泉の点は <strong>{n(s.coverage.points_total)} 点</strong>です。
        環境省が数えている温泉地は <strong>{n(s.coverage.onsen_areas_total)}</strong>、
        源泉は <strong>{n(s.coverage.sources_total)}</strong> あります。
        点は温泉地のおよそ <strong>{(100 * s.coverage.points_per_onsen_area).toFixed(0)}%</strong> にあたる数で、
        源泉の数には遠く及びません。
      </p>
      <p>
        しかも <strong>{s.coverage.prefectures_with_zero_points.length} 都府県には点が 1 つもありません</strong>
        （{s.coverage.prefectures_with_zero_points.join('・')}）。
        いずれも環境省の集計には源泉があります。
        <strong>点が無いことは温泉が無いことを意味しません。</strong>
      </p>
      <details>
        <summary>都道府県ごとの対比</summary>
        <div className="table-scroll">
          <table>
            <thead>
              <tr><th>都道府県</th><th>地図の点</th><th>温泉地</th><th>源泉</th></tr>
            </thead>
            <tbody>
              {s.coverage.rows.map((r) => (
                <tr key={r.prefecture}>
                  <td>{r.prefecture}</td>
                  <td>{n(r.points)}</td>
                  <td>{n(r.onsen_areas)}</td>
                  <td>{n(r.sources_total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>

      <h2>読み取りについて</h2>
      <p className="hint">{s.processing_method}</p>
      {s.source_mismatches.length > 0 && (
        <p className="caution">
          出典の表には食い違いが {s.source_mismatches.length} 件あります。
          {s.source_mismatches.map((m) => (
            <span key={m.prefecture}>
              {m.prefecture}は内訳の合計が {n(m.sum_of_parts)} で、表に書かれた総数 {n(m.stated_total)} と
              {Math.abs(m.difference)} 違います。
            </span>
          ))}
          直さずそのまま出しています。
        </p>
      )}
      <p className="hint">
        出典: {s.source}「{s.dataset}」（{s.download_date} 取得）・
        <a href={s.source_url} target="_blank" rel="noreferrer">元データ</a>
      </p>
    </div>
  );
}
