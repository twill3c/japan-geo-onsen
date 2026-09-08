import { readFileSync } from 'node:fs';
import path from 'node:path';
import type { Metadata } from 'next';
import Dumbbell, { type Row } from '@/components/Dumbbell';

export const metadata: Metadata = {
  title: '温泉と地理環境 — 日本列島 自然環境・温泉GIS',
  description: '温泉の点と、同じデータの温泉以外の観光地点を対照に置いて、地質・標高・傾斜・火山距離の分布を比べる。',
};

type Axis = {
  key: string;
  label: string;
  note: string;
  onsen_n: number;
  control_n: number;
  onsen_missing: number;
  control_missing: number;
  rows: Row[];
  chi_square: number;
  null_mean_chi_square: number;
  p_permutation: number;
  cramers_v: number;
};

type Stats = {
  generated_from: { onsen: number; control: number };
  method: { control: string; test: string; effect_size: string; caution: string };
  seed: number;
  permutations: number;
  axes: Axis[];
};

function load(): Stats {
  const p = path.join(process.cwd(), 'public', 'data', 'stats.json');
  return JSON.parse(readFileSync(p, 'utf8')) as Stats;
}

export default function StatsPage() {
  const stats = load();

  return (
    <div className="prose">
      <h2>温泉は、どんな場所にあるのか</h2>
      <p>
        温泉の点だけを数えて「4 割が火山岩の上にある」と言っても、それが温泉の性質なのか、
        「人が観光地として登録する場所」の性質なのかは分かりません。
        そこで<strong>同じ観光資源データの、温泉ではない点</strong>を対照に置きました。
        都道府県ごとに温泉と同じ数だけ無作為に選んでいます（seed {stats.seed}）。
        調査・提出経路・県の構成はそろうので、残る違いは地理環境の違いに寄ります。
      </p>
      <p>
        温泉 {stats.generated_from.onsen} 点、対照 {stats.generated_from.control} 点。
        差が偶然でないかは、温泉／対照のラベルだけを {stats.permutations} 回入れ替えて
        χ² を作り直し、観測値がその分布のどこに来るかで見ています。
      </p>
      <p className="caution">{stats.method.caution}</p>
      <p className="hint">
        地図には <strong>Wikidata から採った温泉の層</strong>も出していますが、
        <strong>この集計には使っていません</strong>。対照群は同じ観光資源データの中から選ぶことで
        「人が登録した場所」という偏りを打ち消しています。出所の違う点を混ぜると、その揃えが崩れるためです。
      </p>

      <h2>いちばん大きな差</h2>
      <p className="hint">
        軸ごとに、温泉のほうが多い区分と少ない区分を、差の大きい順に一つずつ出しています
        （数字は集計から取り出したもので、書き写していません）。
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr><th>軸</th><th>温泉に多い</th><th>温泉に少ない</th><th>効果の大きさ</th></tr>
          </thead>
          <tbody>
            {stats.axes.map((a) => {
              const sorted = [...a.rows].filter((r) => r.diff_pt !== null)
                .sort((x, y) => (y.diff_pt as number) - (x.diff_pt as number));
              const hi = sorted[0];
              const lo = sorted[sorted.length - 1];
              return (
                <tr key={a.key}>
                  <td>{a.label}</td>
                  <td>{hi.category}（{hi.diff_pt as number >= 0 ? '+' : ''}{hi.diff_pt} pt）</td>
                  <td>{lo.category}（{lo.diff_pt} pt）</td>
                  <td>V = {a.cramers_v}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {(() => {
        // 数は集計から取り出す。文章に書き写すと、軸が増えた日に静かに嘘になる。
        const sorted = [...stats.axes].sort((a, b) => b.cramers_v - a.cramers_v);
        const top = sorted[0];
        const weak = sorted[sorted.length - 1];
        const notSig = stats.axes.filter((a) => a.p_permutation > 0.05);
        return (
          <>
            <p>
              いちばん効果が大きいのは<strong>{top.label}</strong>（V = {top.cramers_v}）、
              いちばん小さいのは<strong>{weak.label}</strong>（V = {weak.cramers_v}）です。
              V が 0.3 に届く軸はひとつもなく、どの軸でも<strong>分布は大きく重なっています</strong>。
              「温泉はこういう場所にある」と言い切れるほどの偏りではありません。
            </p>
            {notSig.length > 0 && (
              <p>
                このうち{notSig.map((a) => a.label).join('・')}は、
                ラベルを入れ替えた分布の中に観測値が埋もれており
                （p = {notSig.map((a) => a.p_permutation).join('、')}）、
                <strong>差があるとは言えません</strong>。出なかったことも結果として載せています。
              </p>
            )}
          </>
        );
      })()}

      {stats.axes.map((a) => (
        <section key={a.key}>
          <h2>{a.label}</h2>
          <p className="hint">{a.note}</p>
          <Dumbbell rows={a.rows} />
          <p className="stat-line">
            χ² = {a.chi_square}（ラベルを入れ替えたときの平均 {a.null_mean_chi_square}）
            {/* p = (観測以上の回数 + 1) / (回数 + 1)。下限に張り付いたときは
                「一度も届かなかった」と書く —— 0.0005 という数字だけを出すと、
                測れた値のように見えてしまう */}
            ・{a.p_permutation <= 1 / stats.permutations
              ? `p < ${(1 / stats.permutations).toFixed(4)}（${stats.permutations} 回の入れ替えで一度も観測値に届かなかった）`
              : `p = ${a.p_permutation}`}
            ・Cramér の V = {a.cramers_v}
            {a.cramers_v < 0.1 && <>（V が小さいので、差はあっても分布の重なりは大きい）</>}
          </p>
          {(a.onsen_missing > 0 || a.control_missing > 0) && (
            <p className="hint">
              この軸の値が取れなかった点: 温泉 {a.onsen_missing} 点 / 対照 {a.control_missing} 点。
              集計から外しています（埋めていません）。
            </p>
          )}
          <details>
            <summary>数の表</summary>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr><th>区分</th><th>温泉</th><th>温泉 %</th><th>対照</th><th>対照 %</th><th>差</th></tr>
                </thead>
                <tbody>
                  {a.rows.map((r) => (
                    <tr key={r.category}>
                      <td>{r.category}</td>
                      <td>{r.onsen}</td>
                      <td>{r.onsen_pct}%</td>
                      <td>{r.control}</td>
                      <td>{r.control_pct}%</td>
                      <td>{r.diff_pt !== null && r.diff_pt >= 0 ? '+' : ''}{r.diff_pt} pt</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </section>
      ))}

      <h2>この数の読み方</h2>
      <ul>
        <li>
          ここにあるのは<strong>共起の記述</strong>です。温泉ができる原因を示すものではありません。
        </li>
        <li>
          温泉の点は観光資源データの「温泉・健康」分類から取ったもので、源泉の台帳ではありません。
          <a href="/about/">10 都府県には 1 点もありません</a>。対照も同じ偏りを持ちますが、
          偏りが完全に打ち消せているとは限りません。
        </li>
        <li>
          最寄りの活火山までの距離は地理的な距離です。近いことは、その温泉が火山性であることを意味しません。
          実際、<strong>100 km 以上離れた区分では温泉と対照がほとんど同じ割合</strong>になっており、
          差が出ているのは中距離の帯だけです。
        </li>
        <li>
          標高の差も一方向ではありません。温泉は 200〜800 m の帯に寄る一方、
          <strong>1200 m 以上では対照のほうが多い</strong>（山頂や高原の観光地が対照に入るため）。
          「高いところほど温泉がある」ではありません。
        </li>
        <li>
          河川との近さがいちばん大きく出ますが、これは
          <strong>温泉が谷底や川沿いの平地にあることの裏返し</strong>でもあります。
          対照に選んだ観光地点も人が行ける場所なので、地形の効果を完全に切り分けてはいません。
        </li>
        <li>
          植生自然度で差が出るのは<strong>中ほどの段階だけ</strong>です。温泉は市街地・農耕地に少なく
          （−14.2 pt）、植林地・二次林に多い（+7.1 / +8.5 pt）一方、
          <strong>自然林・自然草原では差がほぼありません</strong>（+0.09 pt）。
          「自然が濃いほど温泉がある」ではありません。
        </li>
        <li>
          植生の調査は <strong>1992〜1996 年</strong>のもので、約 1 km のメッシュの代表値です。
          いまの土地被覆とは違いうるうえ、1 km 四方を 1 つの区分で代表しています。
        </li>
        <li>
          河川の距離は全 286,437 区間から測っており、細い流れも含みます。
          <strong>地図に描いている 1 級河川の直轄区間だけで測った値ではありません。</strong>
        </li>
      </ul>
    </div>
  );
}
