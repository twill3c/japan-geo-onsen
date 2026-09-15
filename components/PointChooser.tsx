'use client';

/**
 * クリックした位置に点が重なっているときの選択肢(SPEC F-21)。
 *
 * どの層も優先しない。層の色と名前・点の名前を並べ、利用者に選んでもらう。
 * 近い順に並ぶ(同じ距離なら 国土数値情報 → Wikidata 温泉 → 入浴施設 → Wikipedia → 火山)。
 */
import { ONSEN_LAYERS } from '@/lib/layers';
import type { Candidate } from '@/lib/pick';

const LAYER_INFO: Record<string, { label: string; color: string }> = {
  ...Object.fromEntries(ONSEN_LAYERS.map((o) => [o.id, { label: o.label, color: o.color }])),
  volcano: { label: '活火山（気象庁）', color: '#1f2937' },
};

export default function PointChooser({
  candidates, onChoose, lead,
}: { candidates: Candidate[]; onChoose: (c: Candidate) => void; lead?: string }) {
  return (
    <div className="point-chooser">
      <p className="status">
        {lead ?? 'この位置には点が重なっています。'}<strong>{candidates.length} 件</strong>から選んでください。
      </p>
      <ul>
        {candidates.map((c) => {
          const info = LAYER_INFO[c.layerId] ?? { label: c.layerId, color: '#6d675e' };
          return (
            <li key={c.key}>
              <button type="button" onClick={() => onChoose(c)}>
                <i className="dot" style={{ background: info.color }} aria-hidden="true" />
                <span className="name">{c.name}</span>
                <span className="layer">{info.label}</span>
              </button>
            </li>
          );
        })}
      </ul>
      <p className="hint">
        近い順に並べています。拡大すると点が離れて、地図の上でも押し分けられます。
      </p>
    </div>
  );
}
