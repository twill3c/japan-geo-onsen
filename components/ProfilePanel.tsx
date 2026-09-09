'use client';

/**
 * 地形断面の図(設計書 §56)。
 *
 * 断面図は**縦を引き伸ばして描く**。何倍に伸ばしたかを言わずに出すと、実際より
 * 険しい地形に見える。倍率を図の中に必ず書く。
 *
 * 欠測はつながない。標高タイルの無い区間・無効値の区間は線を切り、
 * 何点欠けたかを数で出す(埋めれば図は綺麗になるが、無いものを描くことになる)。
 */
import { useMemo } from 'react';
import { MAX_SAMPLES, verticalExaggeration, type ProfileResult } from '@/lib/profile';

const W = 720;
const H = 210;
const PAD = { left: 52, right: 14, top: 14, bottom: 30 };

export type ProfileState =
  | { phase: 'idle' }
  | { phase: 'picking'; a: [number, number] }
  | { phase: 'loading'; a: [number, number]; b: [number, number] }
  | { phase: 'done'; a: [number, number]; b: [number, number]; result: ProfileResult };

export default function ProfilePanel({
  state, onClose,
}: { state: ProfileState; onClose: () => void }) {
  const result = state.phase === 'done' ? state.result : null;

  const chart = useMemo(() => {
    if (!result || !result.ok || result.minM === null || result.maxM === null) return null;
    const { samples, lengthKm, minM, maxM } = result;
    // 標高の目盛りは少し余白を取る。起伏 0 の平地でも潰れないようにする
    const span = Math.max(maxM - minM, 1);
    const lo = minM - span * 0.08;
    const hi = maxM + span * 0.08;
    const plotW = W - PAD.left - PAD.right;
    const plotH = H - PAD.top - PAD.bottom;
    const x = (km: number) => PAD.left + (km / lengthKm) * plotW;
    const y = (m: number) => PAD.top + (1 - (m - lo) / (hi - lo)) * plotH;

    // 欠測で切れる折れ線。null をまたいで結ばない
    const paths: string[] = [];
    let cur: string[] = [];
    for (const s of samples) {
      if (s.elevation === null) {
        if (cur.length > 1) paths.push(cur.join(' '));
        cur = [];
        continue;
      }
      cur.push(`${cur.length === 0 ? 'M' : 'L'}${x(s.distanceKm).toFixed(2)},${y(s.elevation).toFixed(2)}`);
    }
    if (cur.length > 1) paths.push(cur.join(' '));

    const ticksY = niceTicks(lo, hi, 4);
    const ticksX = niceTicks(0, lengthKm, 5);
    // 目盛りの桁は**間隔**で決める。値ごとに決めると 0 だけ「0.00」になって揃わない
    const stepX = ticksX.length > 1 ? ticksX[1] - ticksX[0] : lengthKm;
    const exaggeration = verticalExaggeration(lengthKm, plotW, hi - lo, plotH);
    return { paths, ticksX, ticksY, stepX, x, y, exaggeration, plotW, plotH };
  }, [result]);

  return (
    <section className="profile-panel" aria-label="地形断面">
      <button className="close" onClick={onClose} aria-label="断面を閉じる">×</button>
      <h3>地形断面</h3>

      {state.phase === 'picking' && (
        <p className="status">始点を置きました。地図をもう一度クリックして終点を決めてください</p>
      )}
      {state.phase === 'idle' && (
        <p className="status">地図を 2 回クリックすると、その間の標高断面を引きます</p>
      )}
      {state.phase === 'loading' && <p className="status">標高タイルを読み込み中…</p>}

      {result && !result.ok && <p className="status">{result.reason}</p>}

      {result && result.ok && chart && (
        <>
          <svg viewBox={`0 0 ${W} ${H}`} role="img"
               aria-label={`A から B までの標高断面。全長 ${result.lengthKm.toFixed(2)} km、標高 ${Math.round(result.minM!)} m から ${Math.round(result.maxM!)} m`}>
            {chart.ticksY.map((v) => (
              <g key={`y${v}`}>
                <line x1={PAD.left} x2={W - PAD.right} y1={chart.y(v)} y2={chart.y(v)}
                      stroke="#e4ded2" strokeWidth={1} />
                <text x={PAD.left - 6} y={chart.y(v) + 3.5} textAnchor="end"
                      fontSize={10.5} fill="#6d675e">{Math.round(v)}</text>
              </g>
            ))}
            {chart.ticksX.map((v) => (
              <text key={`x${v}`} x={chart.x(v)} y={H - PAD.bottom + 14} textAnchor="middle"
                    fontSize={10.5} fill="#6d675e">{fmtKm(v, chart.stepX)}</text>
            ))}
            <line x1={PAD.left} x2={W - PAD.right} y1={H - PAD.bottom} y2={H - PAD.bottom}
                  stroke="#b8b0a2" strokeWidth={1} />
            <line x1={PAD.left} x2={PAD.left} y1={PAD.top} y2={H - PAD.bottom}
                  stroke="#b8b0a2" strokeWidth={1} />
            {chart.paths.map((d, k) => (
              <path key={k} d={d} fill="none" stroke="#8a4b2a" strokeWidth={1.6}
                    strokeLinejoin="round" strokeLinecap="round" />
            ))}
            <text x={PAD.left} y={H - 4} fontSize={10.5} fill="#6d675e">A</text>
            <text x={W - PAD.right} y={H - 4} textAnchor="end" fontSize={10.5} fill="#6d675e">B</text>
            {/* 上端の文字は viewBox から 0.56px はみ出していた(実測)。基線を下げる */}
            <text x={12} y={PAD.top - 2} fontSize={10.5} fill="#6d675e">標高 m</text>
            <text x={W - PAD.right} y={PAD.top - 2} textAnchor="end" fontSize={10.5} fill="#6d675e">
              距離 km
            </text>
          </svg>

          <p className="figures">
            全長 <b>{result.lengthKm.toFixed(2)} km</b> ／
            標高 <b>{Math.round(result.minM!)}–{Math.round(result.maxM!)} m</b>
            （起伏 {Math.round(result.reliefM)} m）
          </p>
          <p className="hint">
            縦は横の<b>約 {fmtRatio(chart.exaggeration)} 倍</b>に引き伸ばして描いています。
            実際の斜面はこの図より緩やかです。
          </p>
          <p className="hint">
            上り {Math.round(result.gainM)} m・下り {Math.round(result.lossM)} m。
            <b>この 2 つは刻みの細かさで変わります</b>（粗く刻むほど小さくなり、
            1 画素より細かく刻んでも頭打ちになります）。
          </p>
          <p className="hint">
            標高タイル z{result.zoom} を {result.tiles} 枚 ／
            {Math.round(result.spacingM)} m ごとに {result.samples.length} 点
            （1 画素は約 {Math.round(result.pixelM)} m）
            {result.missingSamples > 0 && ` ／ 標高が無い点 ${result.missingSamples} 点（線を切ってあります）`}
            {result.missingTiles > 0 && ` ／ 取得できなかったタイル ${result.missingTiles} 枚`}
          </p>
          {result.spacingM > result.pixelM * 1.2 && (
            <p className="hint">
              点の数に上限（{MAX_SAMPLES}）があるため、この長さでは
              <b>1 画素より粗く刻んでいます</b>。細い尾根や深い谷は写らないことがあり、
              標高の幅（起伏）も実際よりやや小さく出ます。短い線を引くと細かく読みます。
            </p>
          )}
          <p className="hint">
            出典: 国土地理院 標高タイル（dem_png）。標高は
            <b>その点が入る画素の値をそのまま</b>使っています（周りと混ぜていません）。
            この断面は地形を見るためのもので、掘削の可否を示すものではありません。
          </p>
        </>
      )}
    </section>
  );
}

/** 目盛りの値を「切りのよい間隔」で並べる。 */
function niceTicks(lo: number, hi: number, want: number): number[] {
  const span = hi - lo;
  if (!(span > 0)) return [lo];
  const raw = span / want;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? mag * 10;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(v);
  return out;
}

function fmtKm(v: number, step: number): string {
  const digits = step >= 1 ? 0 : step >= 0.1 ? 1 : 2;
  return v.toFixed(digits);
}

function fmtRatio(v: number): string {
  return v >= 10 ? v.toFixed(0) : v.toFixed(1);
}
