/**
 * 一本の帯で構成比を見せる。
 *
 * 区分は 4 つで順序があり(温度の帯)、合計に対する割合だけを読ませたいので
 * 円ではなく一本の帯にした。値は帯の下に直接書く —— 色だけで区分を伝えない。
 *
 * 色は dataviz の validate_palette.js で全項目 PASS(light, surface #ffffff)。
 * 隣接対の CVD ΔE 最小 9.2 / 通常視 ΔE 最小 24.0。
 * `#1baf7a` は面のコントラストが 2.82 で 3:1 を下回るため、規約どおり
 * **直接ラベルを必ず出す**(relief rule)。
 */

const COLORS = ['#2a78d6', '#1baf7a', '#eb6834', '#4a3aa7'];

export type Segment = { label: string; value: number };

export default function StackedBar({ segments }: { segments: Segment[] }) {
  const total = segments.reduce((s, x) => s + x.value, 0);
  if (total <= 0) return <p className="hint">集計できる値がありません。</p>;

  const W = 640;
  const H = 34;
  let x = 0;
  const parts = segments.map((s, i) => {
    const w = (s.value / total) * W;
    const item = { ...s, x, w, color: COLORS[i % COLORS.length], pct: (100 * s.value) / total };
    x += w;
    return item;
  });

  return (
    <figure className="viz">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="温度別の源泉数の構成比">
        {parts.map((p) => (
          <g key={p.label}>
            {/* 区分の間に 2px の隙間を置いて、色が隣り合わないようにする */}
            <rect x={p.x} y={0} width={Math.max(0, p.w - 2)} height={H} fill={p.color} rx={2} />
          </g>
        ))}
      </svg>
      <ul className="seg-legend">
        {parts.map((p) => (
          <li key={p.label}>
            <i className="swatch" style={{ background: p.color }} />
            {p.label} <strong>{p.pct.toFixed(1)}%</strong>
            <span className="muted">（{p.value.toLocaleString('ja-JP')}）</span>
          </li>
        ))}
      </ul>
    </figure>
  );
}
