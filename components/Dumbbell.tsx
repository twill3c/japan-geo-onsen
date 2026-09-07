/**
 * 温泉と対照で、同じ区分に入る割合を並べて見せる連結ドット図。
 *
 * 棒を二本並べるより、二点と、その間の距離(＝差)が読める形にした。
 * 見せたい量は「温泉の割合」ではなく「温泉と対照の差」だからである。
 */

export type Row = {
  category: string;
  onsen: number;
  control: number;
  onsen_pct: number | null;
  control_pct: number | null;
  diff_pt: number | null;
};

const ONSEN = '#eb6834';   // categorical slot 2
const CONTROL = '#2a78d6'; // categorical slot 1
// 上の 2 色は dataviz の validate_palette.js で全項目 PASS(light, surface #ffffff,
// 隣接対 CVD ΔE 24.7 / 通常視 ΔE 33.6)。

const W = 640;
const ROW_H = 30;
const PAD = { top: 26, right: 56, bottom: 26, left: 168 };

export default function Dumbbell({ rows, maxPct }: { rows: Row[]; maxPct?: number }) {
  const usable = rows.filter((r) => r.onsen_pct !== null && r.control_pct !== null);
  if (usable.length === 0) return <p className="hint">この軸には集計できる点がありません。</p>;

  const top = Math.max(
    5,
    maxPct ?? Math.max(...usable.flatMap((r) => [r.onsen_pct ?? 0, r.control_pct ?? 0])),
  );
  const niceTop = Math.ceil(top / 10) * 10;
  const H = PAD.top + usable.length * ROW_H + PAD.bottom;
  const plotW = W - PAD.left - PAD.right;
  const x = (pct: number) => PAD.left + (pct / niceTop) * plotW;
  const ticks = Array.from({ length: 5 }, (_, i) => (niceTop / 4) * i);

  return (
    <figure className="viz">
      <div className="viz-legend">
        <span><i className="swatch" style={{ background: ONSEN }} /> 温泉</span>
        <span><i className="swatch" style={{ background: CONTROL }} /> 対照（温泉以外の観光地点）</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="温泉と対照の割合の比較">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} y1={PAD.top - 8} x2={x(t)} y2={H - PAD.bottom} stroke="#e5e0d6" strokeWidth={1} />
            <text x={x(t)} y={PAD.top - 12} textAnchor="middle" fontSize={10} fill="#6d675e">{t}%</text>
          </g>
        ))}

        {usable.map((r, i) => {
          const y = PAD.top + i * ROW_H + ROW_H / 2;
          const xo = x(r.onsen_pct as number);
          const xc = x(r.control_pct as number);
          const rightmost = Math.max(xo, xc);
          const diff = r.diff_pt ?? 0;
          return (
            <g key={r.category}>
              <text x={PAD.left - 10} y={y + 3.5} textAnchor="end" fontSize={11.5} fill="#22201c">
                {r.category}
              </text>
              <line x1={Math.min(xo, xc)} y1={y} x2={Math.max(xo, xc)} y2={y} stroke="#c9c2b5" strokeWidth={2} />
              <circle cx={xc} cy={y} r={5} fill={CONTROL} stroke="#ffffff" strokeWidth={2}>
                <title>{`対照 ${r.control_pct}%（${r.control} 点）`}</title>
              </circle>
              <circle cx={xo} cy={y} r={5} fill={ONSEN} stroke="#ffffff" strokeWidth={2}>
                <title>{`温泉 ${r.onsen_pct}%（${r.onsen} 点）`}</title>
              </circle>
              <text
                x={rightmost + 10} y={y + 3.5} fontSize={10.5}
                fill={diff >= 0 ? '#9a3412' : '#1e4e8c'}
              >
                {diff >= 0 ? '+' : '−'}{Math.abs(diff).toFixed(1)} pt
              </text>
            </g>
          );
        })}
      </svg>
    </figure>
  );
}
