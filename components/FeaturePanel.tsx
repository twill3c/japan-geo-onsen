'use client';

export type Selection = {
  kind: 'onsen' | 'volcano' | 'geology';
  properties: Record<string, unknown>;
  loading?: boolean;
  error?: string;
  lngLat?: [number, number];
};

/** 公開データに無い項目。値を作らず、無い理由ごと見せる(SPEC G-03 / 設計書 §72)。 */
const UNAVAILABLE: [string, string][] = [
  ['泉質', 'spring_quality'],
  ['泉温', 'temperature_c'],
  ['湧出量', 'discharge_l_min'],
  ['pH', 'ph'],
];

function txt(v: unknown): string | null {
  if (v === null || v === undefined || v === '') return null;
  return String(v);
}

function Row({ label, value, unit }: { label: string; value: unknown; unit?: string }) {
  const s = txt(value);
  return (
    <tr>
      <th>{label}</th>
      <td>{s === null ? <span className="none">—</span> : <>{s}{unit ? ` ${unit}` : ''}</>}</td>
    </tr>
  );
}

export default function FeaturePanel({ selection, onClose }: { selection: Selection | null; onClose: () => void }) {
  if (!selection) return null;
  const p = selection.properties;

  return (
    <div className="feature-panel">
      <button className="close" onClick={onClose} aria-label="閉じる">×</button>

      {selection.kind === 'onsen' && (
        <>
          <h3>{p.provenance === 'wikidata-facility' ? '🛁' : '♨'} {txt(p.name) ?? '(名称なし)'}</h3>
          <p className="where">
            {p.provenance === 'wikidata' ? 'Wikidata の温泉'
              : p.provenance === 'wikidata-facility'
                ? `Wikidata の入浴施設${txt(p.facility_class) ? `（${txt(p.facility_class)}）` : ''}`
                : `${txt(p.prefecture) ?? ''}${txt(p.address) ? ` ・ ${txt(p.address)}` : ''}`}
          </p>

          {p.provenance === 'wikidata-facility' && (
            <p className="hint">
              この点は<strong>入浴施設として登録された場所</strong>です。温泉とは限りません
              （銭湯・公衆浴場も同じ分類に入ります）。
            </p>
          )}

          <h4>温泉の属性</h4>
          <table>
            <tbody>
              {UNAVAILABLE.map(([label, key]) => (
                <tr key={key}>
                  <th>{label}</th>
                  <td><span className="none">公開データに無い</span></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="hint">
            泉質・泉温・湧出量を地点ごとに載せた全国の公開データは見つかりませんでした
            （<a href="/about/">調べた範囲</a>）。空欄は「測っていない」ことを表しています。
            <strong>都道府県ごとの集計</strong>なら環境省の実データがあります
            （<a href="/onsen-stats/">温泉の統計</a>）。
          </p>

          <h4>まわりの地理環境</h4>
          <table>
            <tbody>
              <Row label="標高" value={p.elevation_m} unit="m" />
              <Row label="傾斜" value={p.slope_deg} unit="°" />
              <Row label="斜面方位" value={p.aspect_deg} unit="°" />
              <Row label="局所起伏" value={p.local_relief_m} unit="m" />
              <Row label="地質(大区分)" value={p.geology_group} />
              <Row label="岩相" value={p.geology_lithology} />
              <Row label="地質時代" value={p.geology_age} />
              <Row label="最寄りの活火山" value={p.nearest_volcano} />
              <Row label="その距離" value={p.distance_to_volcano_km} unit="km" />
              <Row label="最寄りの河川" value={p.nearest_river} />
              <Row label="その距離" value={p.distance_to_river_km} unit="km" />
              <Row label="最寄りの湖沼" value={p.nearest_lake} />
              <Row label="その距離" value={p.distance_to_lake_km} unit="km" />
              <Row label="植生" value={p.vegetation_community} />
              <Row
                label="植生自然度"
                value={txt(p.vegetation_naturalness)
                  ? `${Number(p.vegetation_naturalness)}（${txt(p.vegetation_naturalness_label)}）`
                  : null}
              />
              <Row label="植生の帯" value={p.vegetation_zone} />
            </tbody>
          </table>
          <p className="hint">
            火山に近いことは、その温泉が火山性であることを意味しません。地理的な距離を示しているだけです。
            河川の距離は全 286,437 区間から測っています（地図に描いているのは 1 級河川の直轄区間だけです）。
            植生は約 1 km のメッシュの代表値で、調査は 1992〜1996 年のものです。
          </p>

          <h4>この点の出所</h4>
          {p.provenance === 'wikidata' || p.provenance === 'wikidata-facility' ? (
            <>
              <table>
                <tbody>
                  <Row label="出典" value="Wikidata（CC0）" />
                  <Row label="項目" value={p.wikidata_id} />
                  {p.provenance === 'wikidata-facility' && (
                    <Row label="分類" value={p.facility_class} />
                  )}
                </tbody>
              </table>
              <p className="hint">
                {txt(p.wikidata_id) && (
                  <a
                    href={`https://www.wikidata.org/wiki/${txt(p.wikidata_id)}`}
                    target="_blank" rel="noreferrer"
                  >
                    Wikidata で見る
                  </a>
                )}
                。
                {p.provenance === 'wikidata-facility'
                  ? '国土数値情報にも、Wikidata の「温泉」分類にも入らない場所です。'
                  : '記事が書かれた温泉が載っているデータで、行政の悉皆調査ではありません。'}
                <strong>統計（温泉と地理環境）にはこの層を使っていません。</strong>
              </p>
            </>
          ) : (
            <table>
              <tbody>
                <Row label="出典" value="国土数値情報 観光資源データ(P12, 2014年版)" />
                <Row label="元 ID" value={p.source_id} />
                <Row label="分類" value={txt(p.kind_name) ?? (p.category_code === '3' ? '観光資源分類コード 3(温泉・健康)' : null)} />
              </tbody>
            </table>
          )}
        </>
      )}

      {selection.kind === 'volcano' && (
        <>
          <h3>▲ {txt(p.name) ?? ''}</h3>
          <p className="where">{txt(p.name_en)}</p>
          <table>
            <tbody>
              <Row label="火山番号" value={p.volcano_id} />
              <Row
                label="噴火警戒レベル"
                value={p.warning_level_operated === true || p.warning_level_operated === 'true' ? '運用中' : '運用なし'}
              />
              <Row label="火口等の細分" value={parseList(p.craters)} />
            </tbody>
          </table>
          <p className="hint">
            出典は気象庁の火山一覧です。噴火警戒レベルの現在値は載せていません
            （<a href="https://www.jma.go.jp/bosai/volcano/" target="_blank" rel="noreferrer">気象庁のページ</a>で確認してください）。
          </p>
        </>
      )}

      {selection.kind === 'geology' && (
        <>
          <h3>地質</h3>
          {selection.lngLat && (
            <p className="where">
              {selection.lngLat[1].toFixed(5)}, {selection.lngLat[0].toFixed(5)}
            </p>
          )}
          {selection.loading && <p className="status">凡例を問い合わせ中…</p>}
          {selection.error && <p className="status">{selection.error}</p>}
          {!selection.loading && !selection.error && (
            txt(p.symbol) ? (
              <table>
                <tbody>
                  <Row label="大区分" value={p.group_ja} />
                  <Row label="岩相" value={p.lithology_ja} />
                  <Row label="形成時代" value={p.formationAge_ja} />
                  <Row label="凡例記号" value={p.symbol} />
                </tbody>
              </table>
            ) : (
              <p className="status">この地点には地質図の凡例がありません（海域など）。</p>
            )
          )}
          <p className="hint">
            出典: 産総研 地質調査総合センター「20万分の1日本シームレス地質図V2」
          </p>
        </>
      )}
    </div>
  );
}

function parseList(v: unknown): string | null {
  if (Array.isArray(v)) return v.length ? v.join('、') : null;
  if (typeof v === 'string') {
    try {
      const a = JSON.parse(v);
      return Array.isArray(a) && a.length ? a.join('、') : null;
    } catch {
      return v || null;
    }
  }
  return null;
}
