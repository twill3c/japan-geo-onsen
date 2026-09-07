'use client';

import { BASEMAPS, OVERLAYS, SOURCES } from '@/lib/layers';

type Props = {
  basemap: string;
  setBasemap: (v: string) => void;
  visible: Record<string, boolean>;
  setVisible: (f: (prev: Record<string, boolean>) => Record<string, boolean>) => void;
  opacity: Record<string, number>;
  setOpacity: (f: (prev: Record<string, number>) => Record<string, number>) => void;
  contourOn: boolean;
  setContourOn: (v: boolean) => void;
  interval: number;
  setInterval: (v: number) => void;
  intervals: number[];
  contourNote: string;
  demZoomNote: string;
  onsenNameOnly: boolean;
  setOnsenNameOnly: (v: boolean) => void;
};

export default function LayerControl(p: Props) {
  const toggle = (id: string) => p.setVisible((prev) => ({ ...prev, [id]: !prev[id] }));
  const setOp = (id: string, v: number) => p.setOpacity((prev) => ({ ...prev, [id]: v }));

  return (
    <aside className="layer-panel">
      <section>
        <h2>ベース地図</h2>
        {BASEMAPS.map((b) => (
          <label key={b.id} className="row">
            <input
              type="radio" name="basemap" checked={p.basemap === b.id}
              onChange={() => p.setBasemap(b.id)}
            />
            <span>{b.label}</span>
          </label>
        ))}
      </section>

      <section>
        <h2>重ねる図</h2>
        {OVERLAYS.map((o) => (
          <div key={o.id} className="layer-item">
            <label className="row">
              <input type="checkbox" checked={!!p.visible[o.id]} onChange={() => toggle(o.id)} />
              <span>{o.label}</span>
            </label>
            <input
              type="range" min={0} max={1} step={0.05}
              value={p.opacity[o.id]}
              disabled={!p.visible[o.id]}
              onChange={(e) => setOp(o.id, Number(e.target.value))}
              aria-label={`${o.label} の不透明度`}
            />
            {o.note && <p className="hint">{o.note}</p>}
          </div>
        ))}
      </section>

      <section>
        <h2>等高線</h2>
        <label className="row">
          <input type="checkbox" checked={p.contourOn} onChange={(e) => p.setContourOn(e.target.checked)} />
          <span>標高タイルから引く</span>
        </label>
        <label className="row">
          <span>間隔</span>
          <select value={p.interval} onChange={(e) => p.setInterval(Number(e.target.value))} disabled={!p.contourOn}>
            {p.intervals.map((v) => <option key={v} value={v}>{v} m</option>)}
          </select>
        </label>
        <p className="hint">{p.demZoomNote}</p>
        {p.contourOn && p.contourNote && <p className="status">{p.contourNote}</p>}
      </section>

      <section>
        <h2>点で示す図</h2>
        <div className="layer-item">
          <label className="row">
            <input type="checkbox" checked={!!p.visible.onsen} onChange={() => toggle('onsen')} />
            <span><i className="dot onsen" /> 温泉(観光資源)</span>
          </label>
          <label className="row indent">
            <input
              type="checkbox" checked={p.onsenNameOnly}
              disabled={!p.visible.onsen}
              onChange={(e) => p.setOnsenNameOnly(e.target.checked)}
            />
            <span>名称に「温泉」「湯」を含むものだけ</span>
          </label>
          <p className="hint">
            出典は観光資源データの「温泉・健康」分類です。温泉そのものの台帳ではありません。
          </p>
        </div>
        <div className="layer-item">
          <label className="row">
            <input type="checkbox" checked={!!p.visible.volcano} onChange={() => toggle('volcano')} />
            <span><i className="dot volcano" /> 活火山(気象庁 111)</span>
          </label>
          <p className="hint">濃い色は噴火警戒レベルが運用されている火山です。</p>
        </div>
      </section>

      <section className="sources">
        <h2>データ出典</h2>
        <ul>
          {SOURCES.map((s) => (
            <li key={s.name}>
              <a href={s.url} target="_blank" rel="noreferrer">{s.name}</a>
            </li>
          ))}
        </ul>
        <p className="hint"><a href="/about/">利用条件と加工方法</a></p>
      </section>
    </aside>
  );
}
