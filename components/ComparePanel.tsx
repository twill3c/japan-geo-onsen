'use client';

/**
 * 2 つの温泉を並べて比べる(設計書 §57)。
 *
 * 設計書の比較表には泉温・湧出量・pH がある。けれど地点別の公開データは無いので、
 * **比べる画面でも数を作らない**。両方の列に「公開データに無い」と出す。
 * 代わりに、所在都道府県の集計を「この温泉の値ではない参考」として別枠に置く。
 */
import { useEffect, useState } from 'react';
import { compareRows, prefectureReference, type PrefStats } from '@/lib/compare';
import { FILE_OF, load as loadSurroundings, type Doc } from '@/components/Surroundings';
import PointChooser from '@/components/PointChooser';
import type { Candidate } from '@/lib/pick';

type Props = Record<string, unknown>;

let statsPromise: Promise<PrefStats | null> | null = null;
function loadStats(): Promise<PrefStats | null> {
  if (!statsPromise) {
    statsPromise = fetch('/data/onsen_stats.json')
      .then((r) => (r.ok ? (r.json() as Promise<PrefStats>) : null))
      .catch(() => null);
  }
  return statsPromise;
}

const SOURCE_LABEL: Record<string, string> = {
  'ksj-p12': '国土数値情報',
  wikidata: 'Wikidata の温泉',
  'wikidata-facility': 'Wikidata の入浴施設',
  wikipedia: 'Wikipedia の記事',
};

function name(p: Props | null): string {
  if (!p) return '（未選択）';
  return p.name == null || p.name === '' ? '（名称なし）' : String(p.name);
}

function useSurroundings(p: Props | null): { doc: Doc | null; row: number[] | null } {
  const [doc, setDoc] = useState<Doc | null>(null);
  const file = p ? (FILE_OF[String(p.provenance ?? 'ksj-p12')] ?? 'onsen') : null;
  useEffect(() => {
    let alive = true;
    if (!file) { setDoc(null); return; }
    loadSurroundings(file).then((d) => { if (alive) setDoc(d); });
    return () => { alive = false; };
  }, [file]);
  if (!doc || !p) return { doc, row: null };
  const rows = doc.rows[String(p.onsen_id)];
  const i10 = doc.radii_km.indexOf(10);
  return { doc, row: rows && i10 >= 0 ? rows[i10] : null };
}

export default function ComparePanel({
  a, b, onClose, onReset, choices, onChoose,
}: {
  a: Props;
  b: Props | null;
  onClose: () => void;
  onReset: () => void;
  /** B を選ぶクリックの位置に点が重なっていたときの候補 */
  choices?: Candidate[] | null;
  onChoose?: (c: Candidate) => void;
}) {
  const [stats, setStats] = useState<PrefStats | null>(null);
  useEffect(() => { loadStats().then(setStats); }, []);
  const sa = useSurroundings(a);
  const sb = useSurroundings(b);

  const same = b != null && a.onsen_id != null && a.onsen_id === b.onsen_id;

  return (
    <section className="feature-panel compare-panel" aria-label="温泉の比較">
      <button className="close" onClick={onClose} aria-label="比較を閉じる">×</button>
      <h3>温泉を比べる</h3>

      {choices && choices.length > 1 && onChoose && (
        <PointChooser candidates={choices} onChoose={onChoose} lead="比べる相手の位置に点が重なっています。" />
      )}
      {!b && !(choices && choices.length > 1) && (
        <p className="status">
          「{name(a)}」を A にしました。<strong>比べる相手の温泉を地図でクリック</strong>してください。
        </p>
      )}
      {same && <p className="status">同じ温泉です。別の温泉をクリックしてください。</p>}

      {b && !same && (
        <>
          <div className="table-scroll">
            <table className="compare-table">
              <thead>
                <tr>
                  <th />
                  <th className="col-a">A {name(a)}</th>
                  <th className="col-b">B {name(b)}</th>
                  <th className="num">差 (B−A)</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th>出所</th>
                  <td>{SOURCE_LABEL[String(a.provenance ?? 'ksj-p12')] ?? '—'}</td>
                  <td>{SOURCE_LABEL[String(b.provenance ?? 'ksj-p12')] ?? '—'}</td>
                  <td />
                </tr>
                {compareRows(a, b).map((r) => (
                  r.kind === 'unavailable' ? (
                    // 両方とも無い行は 1 つの欄にまとめる。A・B それぞれに書くと
                    // 狭いパネルで 2 行ずつ折れて、表が「無い」で埋まって読めなかった(撮影で確認)
                    <tr key={r.key} className="unavailable">
                      <th>{r.label}</th>
                      <td colSpan={3} className="none">{r.a}（A・B とも）</td>
                    </tr>
                  ) : (
                    <tr key={r.key}>
                      <th>{r.label}</th>
                      <td>{r.a}</td>
                      <td>{r.b}</td>
                      <td className="num">{r.diff ?? ''}</td>
                    </tr>
                  )
                ))}
                {sa.doc && (
                  <>
                    {([['volcanoes', 'まわり 10 km の活火山'], ['onsen_ksj', 'まわり 10 km の温泉 P12'],
                      ['lakes', 'まわり 10 km の湖沼']] as [string, string][]).map(([key, label]) => {
                      const ci = sa.doc!.columns.indexOf(key);
                      const va = sa.row ? sa.row[ci] : null;
                      const vb = sb.row && sb.doc ? sb.row[sb.doc.columns.indexOf(key)] : null;
                      return (
                        <tr key={key}>
                          <th>{label}</th>
                          <td>{va ?? '—'}</td>
                          <td>{vb ?? '—'}</td>
                          <td className="num">{va != null && vb != null ? signed(vb - va) : ''}</td>
                        </tr>
                      );
                    })}
                  </>
                )}
              </tbody>
            </table>
          </div>
          <p className="hint">
            <strong>泉温・湧出量・pH・泉質は、地点ごとの公開データがありません。</strong>
            比べる画面でも値は作っていません。
          </p>

          <h4>参考：所在都道府県の集計（この温泉の値ではありません）</h4>
          {[a, b].map((p, i) => {
            const ref = prefectureReference(p?.prefecture == null ? undefined : String(p.prefecture), stats);
            return (
              <p key={i} className="hint">
                {i === 0 ? 'A' : 'B'} {name(p)}：
                {ref
                  ? <>
                      {ref.prefecture}の源泉 {ref.sourcesTotal.toLocaleString('ja-JP')} 本のうち、
                      温度の区分がある源泉に占める 42℃以上の割合は <strong>{(100 * ref.over42Share).toFixed(1)}%</strong>
                    </>
                  : '所在都道府県が属性に無いため出せません'}
              </p>
            );
          })}
          <p className="hint">出典：環境省「令和6年度温泉利用状況」。<a href="/onsen-stats/">温泉の統計</a></p>
        </>
      )}

      <p className="compare-actions">
        <button type="button" onClick={onReset}>A を選び直す</button>
      </p>
    </section>
  );
}

function signed(v: number): string {
  if (v === 0) return '±0';
  return v > 0 ? `+${v}` : `−${Math.abs(v)}`;
}
