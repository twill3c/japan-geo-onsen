import { readFileSync } from 'node:fs';
import path from 'node:path';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'AI（ベースラインの比較） — 日本列島 自然環境・温泉GIS',
  description:
    '温泉として登録された場所の地理環境を、Logistic Regression・Random Forest・XGBoost で当ててみる。合否は学習の前に書いた。温泉の存在を当てるモデルではない。',
};

/** 設計書 §36 の AI 免責。文言を変えずに必ず出す。 */
const AI_DISCLAIMER =
  'この結果は公開データから学習した統計モデルによる推定です。温泉の存在・泉質・湧出量を保証するものではありません。';

type Metrics = { accuracy: number; precision: number; recall: number; f1: number; roc_auc: number; pr_auc: number };
type Results = {
  question: string;
  preregistration: string;
  preregistration_sha256: string;
  seed: number;
  rows: number; positives: number; negatives: number; prefectures: number;
  features: string[];
  versions: Record<string, string>;
  models: Record<string, { label: string; grouped: Metrics; random: Metrics; hyperparameters: Record<string, unknown> }>;
  best_model: string;
  baselines: {
    constant: { grouped_roc_auc: number };
    single_feature: Record<string, number>;
    best_single_feature: { feature: string; grouped_roc_auc: number };
  };
  negative_control: { method: string; roc_auc: number };
  gates: Record<string, { rule: string; value: number; passed: boolean }>;
  permutation_importance: { model: string; metric: string; features: Record<string, { mean: number; sd: number }> };
};

const FEATURE_LABEL: Record<string, string> = {
  elevation_m: '標高',
  slope_deg: '傾斜',
  local_relief_m: '局所起伏',
  distance_to_volcano_km: '活火山までの距離',
  distance_to_river_km: '河川までの距離',
  distance_to_lake_km: '湖沼までの距離',
  vegetation_naturalness: '植生自然度',
  geology_group: '地質の大区分',
};

function load(): Results {
  return JSON.parse(readFileSync(path.join(process.cwd(), 'public', 'data', 'ai', 'baselines.json'), 'utf8')) as Results;
}

const f3 = (v: number) => v.toFixed(3);

export default function Page() {
  const r = load();
  const best = r.models[r.best_model];
  const imp = Object.entries(r.permutation_importance.features).sort((a, b) => b[1].mean - a[1].mean);
  const maxImp = Math.max(...imp.map(([, v]) => v.mean), 1e-9);
  const singles = Object.entries(r.baselines.single_feature).sort((a, b) => b[1] - a[1]);
  const allPassed = Object.values(r.gates).every((g) => g.passed);

  return (
    <article className="prose wide">
      <h1>AI：温泉として登録された場所の傾向を当ててみる</h1>
      <p className="ai-disclaimer" role="note">{AI_DISCLAIMER}</p>

      <h2>何を当てているのか</h2>
      <p>
        設計書は AI で「温泉ポテンシャル」を出すことを求めています。ただし、地点ごとの
        <strong>泉温・湧出量・泉質の公開データはありません</strong>。温泉が「無い」ことを示すデータもありません
        （設計書 §33：「温泉が確認されていない場所」は「温泉が無い場所」ではない）。
      </p>
      <p>
        そこでこのモデルが当てるのは次の問いです：<strong>{r.question}</strong>。
        正例は観光資源データの温泉 {r.positives.toLocaleString('ja-JP')} 点、負例は同じデータの温泉以外の観光資源から
        都道府県ごとに同じ数を選んだ {r.negatives.toLocaleString('ja-JP')} 点です。
        つまりこれは<strong>「温泉が湧くか」ではなく「温泉として登録された場所がどんな地理環境にあるか」</strong>を
        学んだモデルです。
      </p>

      <h2>合否（学習の前に書いた基準）</h2>
      <p className="hint">
        基準は <a href={`https://github.com/twill3c/japan-geo-onsen/blob/master/${r.preregistration}`}>{r.preregistration}</a> に
        モデルを学習させる前に書いて積み、結果はそのファイルの SHA-256（<code>{r.preregistration_sha256.slice(0, 12)}…</code>）を持っています。
        結果を見てから基準を動かしていないことを、テストが確かめます。
      </p>
      <div className="table-scroll">
        <table className="ai-gates">
          <thead><tr><th>ID</th><th>基準</th><th>結果</th><th>判定</th></tr></thead>
          <tbody>
            {Object.entries(r.gates).map(([id, g]) => (
              <tr key={id}>
                <td>{id}</td>
                <td>{g.rule}</td>
                <td className="num">{id === 'G-22b' ? `${g.value >= 0 ? '+' : ''}${f3(g.value)}` : f3(g.value)}</td>
                <td><strong>{g.passed ? '通過' : '不通過'}</strong></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        {allPassed
          ? <>3 つの基準をすべて通りました。</>
          : <>通らなかった基準があります。<strong>基準を下げたり特徴量を足して取り直したりはしていません</strong>。</>}
        最良は <strong>{best.label}</strong>（都道府県ごとに分けた検証で ROC-AUC {f3(best.grouped.roc_auc)}）、
        最も強い 1 変数は<strong>{FEATURE_LABEL[r.baselines.best_single_feature.feature]}</strong>
        （同 {f3(r.baselines.best_single_feature.grouped_roc_auc)}）です。
      </p>

      <h2>3 つのモデルの比較（設計書 §31 の指標）</h2>
      <p className="hint">
        「都道府県分割」は、都道府県を丸ごと検証側に回した 5 分割です。近くの温泉が学習と検証の両方に入ると、
        場所を覚えただけで当たったように見えるため、合否はこちらで判定します。「無作為分割」は漏れの大きさを見るための参考です。
        しきい値は 0.5。
      </p>
      <div className="table-scroll">
        <table className="ai-table">
          <thead>
            <tr>
              <th>モデル</th><th>分割</th>
              <th className="num">Accuracy</th><th className="num">Precision</th><th className="num">Recall</th>
              <th className="num">F1</th><th className="num">ROC-AUC</th><th className="num">PR-AUC</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(r.models).flatMap(([key, m]) => (['grouped', 'random'] as const).map((s) => (
              <tr key={`${key}-${s}`} className={key === r.best_model && s === 'grouped' ? 'best' : undefined}>
                <td>{s === 'grouped' ? m.label : ''}</td>
                <td>{s === 'grouped' ? '都道府県分割' : '無作為分割（参考）'}</td>
                <td className="num">{f3(m[s].accuracy)}</td>
                <td className="num">{f3(m[s].precision)}</td>
                <td className="num">{f3(m[s].recall)}</td>
                <td className="num">{f3(m[s].f1)}</td>
                <td className="num"><strong>{f3(m[s].roc_auc)}</strong></td>
                <td className="num">{f3(m[s].pr_auc)}</td>
              </tr>
            )))}
            <tr>
              <td>定数の予測</td><td>—</td><td className="num" colSpan={4}>—</td>
              <td className="num">{f3(r.baselines.constant.grouped_roc_auc)}</td><td className="num">—</td>
            </tr>
          </tbody>
        </table>
      </div>

      <h3>1 変数だけのロジスティック回帰（都道府県分割の ROC-AUC）</h3>
      <div className="table-scroll">
        <table className="ai-table">
          <tbody>
            {singles.map(([k, v]) => (
              <tr key={k}>
                <th>{FEATURE_LABEL[k] ?? k}</th>
                <td className="num">{f3(v)}</td>
                <td className="bar-cell"><span className="region-bar"><span style={{ width: `${Math.max(0, (v - 0.5) / 0.5) * 100}%` }} /></span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="hint">棒は 0.5（偶然）から 1.0 までのうち、どこまで届いたかを示します。</p>

      <h3>陰性対照</h3>
      <p>
        都道府県の中でラベルを無作為に入れ替えて同じ手順で学習し直すと、ROC-AUC は <strong>{f3(r.negative_control.roc_auc)}</strong> でした。
        ラベルと地理環境の結び付きを壊すと偶然（0.5）に戻ることを確かめています。
        ここが 0.5 から大きく外れていたら、手順のどこかでラベルが漏れていることになります。
      </p>

      <h2>何が効いているか（設計書 §35）</h2>
      <p className="hint">
        最良モデル（{r.models[r.permutation_importance.model].label}）で、検証側の 1 列だけを無作為に入れ替えたときに
        ROC-AUC がどれだけ下がるか（都道府県分割の各分割で 5 回ずつの平均）。
        <strong>効いているのは「温泉として登録された場所」との結び付きで、温泉が湧く原因ではありません。</strong>
      </p>
      <div className="table-scroll">
        <table className="ai-table">
          <tbody>
            {imp.map(([k, v]) => (
              <tr key={k}>
                <th>{FEATURE_LABEL[k] ?? k}</th>
                <td className="num">{v.mean >= 0 ? '−' : '+'}{f3(Math.abs(v.mean))}</td>
                <td className="num small">±{f3(v.sd)}</td>
                <td className="bar-cell"><span className="region-bar"><span style={{ width: `${Math.max(0, v.mean / maxImp) * 100}%` }} /></span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>温泉ごとの見立て（設計書 §35）</h2>
      <p>
        地図で国土数値情報の温泉をクリックすると、詳細の「AI の見立て」に、その温泉についての
        <strong>モデルの出力（0〜1）</strong>と、出力を押し上げた・押し下げた特徴量（SHAP の寄与）が出ます。
      </p>
      <ul>
        <li>
          出力と寄与は、<strong>その温泉の都道府県を学習に使っていないモデル</strong>のものです。
          学習に使ったモデルで説明すると、Random Forest は点を覚えて 1 に近い値を出してしまいます。
          説明のために学び直したモデルの分割外 ROC-AUC は、上の合否を判定した値と一致しています。
        </li>
        <li>
          出力は<strong>確率ではありません</strong>（較正していません）。設計書の例のような「存在可能性 ○%」の形では出していません。
        </li>
        <li>
          寄与はすべて足すと、基準値から出力までの差にちょうどなります（SHAP の加法性。全 1,320 点で誤差 100 万分の 1 未満を確認）。
        </li>
      </ul>

      <h2>この段でしていないこと</h2>
      <ul>
        <li>
          <strong>全国の「AI 温泉ポテンシャル」地図（設計書 Phase 7）は塗っていません。</strong>
          このモデルが当てているのは「登録のされ方」なので、全国の格子に塗ると、
          その場所で温泉が得られるかのように読まれてしまいます（設計書 §36 が禁じている読まれ方です）。
        </li>
        <li>
          <strong>CNN（Phase 6）は試していません。</strong>設計書 §32 は「十分なデータが得られた場合のみ」としています。
          正例は {r.positives.toLocaleString('ja-JP')} 点で、表形式のモデルの結果をまず見てから判断します。
        </li>
        <li>
          断層（設計書 §52）は取り込んでいません。泉温・湧出量・泉質は地点別の公開データが無いので、特徴量にも目的変数にもしていません。
        </li>
      </ul>

      <h2>データと再現</h2>
      <p className="hint">
        学習に使った表：<a href="/data/ai/dataset.csv">dataset.csv</a>（{r.rows.toLocaleString('ja-JP')} 行・{r.prefectures} 都道府県）、
        列の説明：<a href="/data/ai/dataset_dictionary.json">dataset_dictionary.json</a>、
        結果：<a href="/data/ai/baselines.json">baselines.json</a>。
        学習はローカルで行い（設計書 §37）、この画面は結果を表示するだけです。
        乱数の種 {r.seed}、scikit-learn {r.versions['scikit-learn']}・XGBoost {r.versions.xgboost}。
      </p>
      <p className="ai-disclaimer" role="note">{AI_DISCLAIMER}</p>
    </article>
  );
}
