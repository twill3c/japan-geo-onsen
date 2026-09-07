import type { Metadata } from 'next';
import { SOURCES } from '@/lib/layers';

export const metadata: Metadata = {
  title: 'データと出典 — 日本列島 自然環境・温泉GIS',
  description: 'この地図が使っている公開データの出典・利用条件・取得日・加工方法と、探して見つからなかったデータの記録。',
};

export default function About() {
  return (
    <div className="prose">
      <h2>この地図は何をしているか</h2>
      <p>
        日本列島の地形・地質・火山・温泉を、公開データをそのまま重ねて表示します。
        値を推定して埋めることはしません。取れなかった項目は空欄のまま出します。
      </p>

      <h2>データ出典と利用条件</h2>
      <div className="table-scroll">
        <table>
          <thead>
            <tr><th>提供元</th><th>使っているもの</th><th>利用条件</th></tr>
          </thead>
          <tbody>
            {SOURCES.map((s) => (
              <tr key={s.name}>
                <td><a href={s.url} target="_blank" rel="noreferrer">{s.name}</a></td>
                <td>{s.what}</td>
                <td><a href={s.licenseUrl} target="_blank" rel="noreferrer">{s.license}</a></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>加工の方法</h2>
      <h3>活火山(111)</h3>
      <p>
        気象庁の火山一覧 JSON は <strong>120 件</strong>ありますが、気象庁が公表している活火山の数は
        <strong> 111</strong> です。中身を数えると、
      </p>
      <p><code>120 ＝ 111（活火山） ＋ 3（座標を持たない一覧表示用の項目） ＋ 6（親火山の火口の細分）</code></p>
      <p>
        で公表値と合います。細分の 6 件は「草津白根山（湯釜付近）」のように親火山の名前で始まるもので、
        名簿自身から判定できます。この分解が崩れたらデータ生成は止まります。
      </p>

      <h3>温泉(1,320 点)</h3>
      <p>
        国土数値情報の観光資源データ(P12, 2014年版)の全国 17,258 点から、
        <strong>種別名称が「温泉」</strong>のもの、または<strong>観光資源分類コードが 3（温泉・健康）</strong>
        のものを抜き出しました。分類 3 は「温泉・健康」であって温泉そのものの分類ではないため、
        名称に「温泉」「湯」を含むかどうかを属性として持たせ、絞り込みは利用者に委ねています
        （1,320 点中 977 点が該当）。
      </p>
      <p>
        各点には、国土地理院の標高タイルから求めた<strong>標高・傾斜・斜面方位・局所起伏</strong>と、
        シームレス地質図V2の凡例 API から引いた<strong>地質</strong>、
        気象庁の活火山との<strong>距離</strong>を付けています。
      </p>

      <h2>被覆の穴</h2>
      <p>
        この温泉点は観光地点等名簿の提出状況に依存するため、<strong>分布に偏りがあります</strong>。
        福島県・東京都・富山県・福井県・愛知県・大阪府・広島県・香川県・熊本県・宮崎県の
        <strong>10 都府県には 1 点もありません</strong>。
        「点が無い＝温泉が無い」ではありません。
      </p>

      <h2>見つからなかったデータ</h2>
      <p>
        温泉の<strong>泉質・泉温・湧出量</strong>を地点ごとに載せた全国の公開データを探しましたが、
        次のとおり見つかりませんでした（2026-09-07 時点の調査）。
      </p>
      <div className="table-scroll">
        <table>
          <thead><tr><th>探した先</th><th>結果</th></tr></thead>
          <tbody>
            <tr>
              <td>国土数値情報（全 157 データセット）</td>
              <td>温泉のデータセットは無い</td>
            </tr>
            <tr>
              <td>環境省 温泉に関するデータ</td>
              <td>都道府県別の集計 PDF のみ（源泉総数・温度別源泉数・湧出量）。地点別は無い</td>
            </tr>
            <tr>
              <td>OpenStreetMap <code>natural=hot_spring</code></td>
              <td>全国 238 点。<code>temperature</code> タグは 0 件</td>
            </tr>
            <tr>
              <td>OpenStreetMap <code>amenity=public_bath</code> ほか</td>
              <td>
                全国 5,803 件で被覆は広い。ただし源泉ではなく入浴施設であり、
                ODbL の継承条件が政府標準利用規約のデータと混ざるため採らなかった
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <h2>この地図でしていないこと</h2>
      <ul>
        <li>まだ知られていない温泉を「予測」すること</li>
        <li>推定した値を実データとして表示すること</li>
        <li>噴火警戒レベルなど、刻々変わる情報を出すこと</li>
      </ul>

      <h2>作り方</h2>
      <p>
        地図は MapLibre GL JS、外側は Next.js の静的書き出しです。サーバ側の処理はひとつもありません。
        等高線は事前に作ったデータではなく、表示範囲の標高タイルをその場で読んで
        marching squares で引いています。標高タイルの読み方は Python と TypeScript の二つで実装し、
        実タイル 8 枚・524,288 画素すべてで一致することを検査しています。
      </p>
    </div>
  );
}
