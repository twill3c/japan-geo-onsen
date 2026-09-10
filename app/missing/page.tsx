import { readFileSync } from 'node:fs';
import path from 'node:path';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: '地図に出せない温泉 — 日本列島 自然環境・温泉GIS',
  description:
    '名前は分かっているのに、位置が公開データのどこにも無い温泉の一覧。緯度経度を作れば地図には出せるが、それは架空のデータを作ることになるので出さずに名前で残す。',
};

type Row = { name: string | null; wikidata_id?: string | null; url?: string; admin?: string | null; classes?: string[] };
type Missing = {
  note: string;
  generated_at: string;
  sources: { source: string; license: string; source_url: string; what: string; count: number }[];
  wikipedia: Row[];
  wikidata: Row[];
  wikidata_classes: Record<string, number>;
};

function load(): Missing {
  const p = path.join(process.cwd(), 'public', 'data', 'onsen_missing.json');
  return JSON.parse(readFileSync(p, 'utf8')) as Missing;
}

const n = (v: number) => v.toLocaleString('ja-JP');

export default function Page() {
  const d = load();
  const total = d.wikipedia.length + d.wikidata.length;

  return (
    <article className="prose">
      <h1>地図に出せない温泉</h1>
      <p>
        名前は分かっているのに、<strong>位置が公開データのどこにも無い</strong>温泉が
        <strong> {n(total)} 件</strong>あります。緯度経度を作れば地図には出せますが、
        それは<strong>架空のデータを作ること</strong>なので、出さずにここに名前で残します。
      </p>
      <p className="hint">
        なお {n(total)} 件がすべて「個々の温泉」ではありません。温泉郷のような
        <strong>まとまり</strong>や、「日本三古湯」のような<strong>概念</strong>も同じ分類で
        登録されています。下の一覧では分類を添えてあります。
      </p>
      <p className="hint">
        この一覧は「日本の温泉で地図に無いもの」の全部ではありません。
        <strong>Wikipedia に記事があるか、Wikidata に項目があるものだけ</strong>です。
        環境省が数えている温泉地は 2,839、源泉は 27,899 あり、その一覧は公開されていません。
      </p>

      <h2>なぜ出せないのか</h2>
      <p>
        この地図の点は、<a href="/about/">4 つの出所</a>から来ています。どれも
        <strong>座標を持っているものだけ</strong>を採っています。名前しか無いものは、
        地図の上のどこに置くかを決められません。実際に指摘のあった 2 件はこうでした。
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr><th>温泉</th><th>Wikidata</th><th>分類</th><th>座標</th><th>結果</th></tr>
          </thead>
          <tbody>
            <tr>
              <td>ほったらかし温泉</td><td>Q11277778</td><td>日帰り入浴施設</td><td>あり</td>
              <td>分類が「温泉」でないため 2 層から漏れていた → <strong>第三の層に追加</strong></td>
            </tr>
            <tr>
              <td>大田区の黒湯温泉</td><td>Q671405</td><td><strong>温泉</strong></td><td><strong>無し</strong></td>
              <td>分類は合うが座標が無い → <strong>この一覧</strong></td>
            </tr>
            <tr>
              <td>山中湖温泉</td><td>Q108702377</td><td>温泉街・単純温泉</td><td><strong>無し</strong></td>
              <td>記事にも座標が無い → <strong>この一覧</strong></td>
            </tr>
          </tbody>
        </table>
      </div>

      <h2>出所</h2>
      <div className="table-scroll">
        <table>
          <thead><tr><th>出典</th><th>内容</th><th>件数</th><th>利用条件</th></tr></thead>
          <tbody>
            {d.sources.map((s) => (
              <tr key={s.source}>
                <td><a href={s.source_url} target="_blank" rel="noreferrer">{s.source}</a></td>
                <td>{s.what}</td>
                <td>{n(s.count)}</td>
                <td>{s.license}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>Wikipedia に記事があるが座標が無いもの（{n(d.wikipedia.length)} 件）</h2>
      <p className="hint">
        都道府県別「○○の温泉」カテゴリの記事のうち、記事にも Wikidata にも座標が無いものです。
      </p>
      <ul className="name-list">
        {d.wikipedia.map((r) => (
          <li key={r.url}>
            <a href={r.url} target="_blank" rel="noreferrer">{r.name}</a>
          </li>
        ))}
      </ul>

      <h2>Wikidata に項目があるが座標が無いもの（{n(d.wikidata.length)} 件）</h2>
      <p className="hint">
        「温泉」に分類され、国が日本である項目のうち、座標（P625）を持たないものです。
        <strong>個々の温泉だけではありません。</strong>温泉郷や「別府八湯」のような
        <strong>まとまり</strong>、「名湯百選」「日本三古湯」のような<strong>概念</strong>、
        閉業した施設も同じ分類で登録されています。分類を各項目に添えました。
      </p>
      <div className="table-scroll">
        <table>
          <thead><tr><th>分類</th><th>件数</th></tr></thead>
          <tbody>
            {Object.entries(d.wikidata_classes).slice(0, 10).map(([k, v]) => (
              <tr key={k}><td>{k}</td><td>{n(v)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="name-list">
        {d.wikidata.map((r) => (
          <li key={r.wikidata_id}>
            <a href={`https://www.wikidata.org/wiki/${r.wikidata_id}`} target="_blank" rel="noreferrer">
              {r.name ?? r.wikidata_id}
            </a>
            {(r.classes?.length || r.admin) && (
              <span className="hint">
                {' '}・{[r.classes?.join('・'), r.admin].filter(Boolean).join(' / ')}
              </span>
            )}
          </li>
        ))}
      </ul>

      <h2>この一覧を埋めるには</h2>
      <p>
        座標は、その温泉を知っている人が <a href="https://www.wikidata.org/" target="_blank" rel="noreferrer">Wikidata</a> に
        <code>P625（座標）</code>を足せば、次にこの地図のデータを作り直したときに点として出ます。
        こちらで推測して埋めることはしません。
      </p>
      <p className="hint">取得日: {d.generated_at}</p>
    </article>
  );
}
