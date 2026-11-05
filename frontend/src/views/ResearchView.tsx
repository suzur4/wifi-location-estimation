import { useEffect, useState } from 'react';
import { api, type Metric, type Research, type SeriesRow } from '../api';
import { apNames, SignalChart } from '../components/SignalChart';
import { fullDateTime, percent } from '../lib/format';
import { algorithmLabels, preprocessingLabels } from '../lib/teachers';

export function ResearchView({ areaLabel }: { areaLabel: (id: string | null) => string }) {
  const [dataset, setDataset] = useState('simulation');
  const [data, setData] = useState<Research | null>(null);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    // Ignore a slow response for a dataset that is no longer selected.
    let current = true;
    setError('');
    api<Research>(`/research?dataset=${encodeURIComponent(dataset)}`)
      .then(result => { if (current) setData(result); })
      .catch((e: Error) => { if (current) setError(e.message); });
    return () => { current = false; };
  }, [dataset, retry]);

  const shown = data?.dataset === dataset || (data && !data.dataset) ? data : null;
  return (
    <>
      <div className="page-head">
        <div>
          <h1 id="page-title" tabIndex={-1}>実験データ</h1>
          <p className="lead">位置推定の方式を比べた実験の結果です。模擬データと公開データによる評価で、学校での精度を示すものではありません。</p>
        </div>
      </div>

      {data && data.datasets?.length > 1 && (
        <fieldset className="segmented">
          <legend>表示するデータ</legend>
          {data.datasets.map(option => (
            <label key={option.id}>
              <input type="radio" name="dataset" value={option.id} checked={dataset === option.id}
                onChange={() => setDataset(option.id)} />
              <span>{option.label}</span>
            </label>
          ))}
        </fieldset>
      )}

      {error ? (
        <div className="alert alert-error" role="alert"><p><strong>実験データを取得できませんでした。</strong>{error}</p>
          <button type="button" className="button-text" onClick={() => setRetry(value => value + 1)}>再試行</button></div>
      ) : !shown ? (
        <p className="empty" role="status">読み込んでいます…</p>
      ) : (
        <ResearchBody data={shown} areaLabel={areaLabel} />
      )}
    </>
  );
}

function ResearchBody({ data, areaLabel }: { data: Research; areaLabel: (id: string | null) => string }) {
  const [train, validation, test] = data.counts ?? [];
  const hasIds = data.metrics.some(m => m.id);
  const topScore = Math.max(...data.candidates.map(c => c.score), 0.001);
  return (
    <>
      <dl className="facts">
        <div><dt>実験ID</dt><dd>{data.experiment_id && data.experiment_id !== 'not-run' ? data.experiment_id : '未実行'}</dd></div>
        <div><dt>データ</dt><dd>{data.source === 'simulation' ? '模擬データ' : data.source === 'ujindoorloc' ? 'UJIIndoorLoc（公開データ）' : data.source}</dd></div>
        {test !== undefined && <div><dt>件数</dt><dd>学習 {train} / 閾値の調整 {validation} / テスト {test}</dd></div>}
        {data.created_at && <div><dt>実行日時</dt><dd>{fullDateTime(data.created_at)}</dd></div>}
      </dl>

      {data.series.length > 0 && (
        <div className="columns">
          <section className="section">
            <h2>APごとのRSSI</h2>
            <SignalChart series={data.series} />
            <p className="caption">1つの静止測定（{data.series.length}回）の模擬観測値です。単位はdBmで、0に近いほど電波が強いことを表します。</p>
          </section>
          <section className="section">
            <h2>APごとの受信状況</h2>
            <ReceptionTable series={data.series} />
          </section>
        </div>
      )}

      {data.candidates.length > 0 && (
        <section className="section">
          <h2>推定候補の比較</h2>
          <ul className="bars">
            {data.candidates.map(c => (
              <li key={c.area}>
                <span className="bar-label">{areaLabel(c.area)}</span>
                <span className="bar-track"><span className="bar-fill" style={{ width: `${Math.max(0, Math.min(100, c.score / topScore * 100))}%` }} /></span>
                <span className="bar-value">{c.score.toFixed(3)}</span>
              </li>
            ))}
          </ul>
          <p className="caption">スコアは方式どうしを比べるための値で、正解する確率ではありません。</p>
        </section>
      )}

      <section className="section">
        <h2>方式別の評価結果</h2>
        {data.metrics.length ? (
          <>
            <div className="table-scroll">
              <table className="data">
                <thead>
                  <tr>
                    {hasIds && <th scope="col">実験</th>}
                    <th scope="col">推定方式</th><th scope="col">前処理</th>
                    <th scope="col" className="num">エリア正解率</th><th scope="col" className="num">誤表示率</th>
                    <th scope="col" className="num">位置不明率</th><th scope="col" className="num">表示した結果の正解率</th>
                    <th scope="col" className="num">推定時間</th>
                  </tr>
                </thead>
                <tbody>
                  {data.metrics.map((m, i) => (
                    <tr key={m.id ?? `${m.algorithm}-${i}`}>
                      {hasIds && <td>{m.id}</td>}
                      <td>{methodLabel(m)}</td>
                      <td>{preprocessingLabel(m)}</td>
                      <td className="num strong">{percent(m.accuracy)}</td>
                      <td className="num">{percent(m.false_display_rate)}</td>
                      <td className="num">{percent(m.unknown_rate)}</td>
                      <td className="num">{m.precision == null ? '—' : percent(m.precision)}</td>
                      <td className="num">{m.latency_ms.toFixed(2)} ms</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="caption">
              エリア正解率・誤表示率・位置不明率は、すべてのテスト測定に対する割合です。「表示した結果の正解率」は、場所を表示した測定だけに対する割合です。
            </p>
          </>
        ) : (
          <p className="empty">保存された実験結果がありません。READMEの「比較実験」のコマンドを実行してください。</p>
        )}
      </section>

      <section className="section">
        <h2>結果の読み方</h2>
        <p>{data.note || 'シミュレーションは開発・比較用です。実測データでの検証が必要です。'}</p>
        {data.citation && <p className="caption">出典：{data.citation}{data.license ? `（${data.license}）` : ''}</p>}
      </section>
    </>
  );
}

// k and AP selection are shown so that, e.g., k-NN with k=3 and k=5 do not look identical.
function methodLabel(m: Metric) {
  const label = algorithmLabels[m.algorithm] ?? m.algorithm;
  return (m.algorithm === 'knn' || m.algorithm === 'weighted_knn') && m.k ? `${label}（k=${m.k}）` : label;
}

function preprocessingLabel(m: Metric) {
  const label = preprocessingLabels[m.preprocessing] ?? m.preprocessing;
  if (!m.selection || m.selection === 'all') return label;
  return `${label}＋AP選択${m.selected_aps?.length ? `（${m.selected_aps.length}台）` : ''}`;
}

function ReceptionTable({ series }: { series: SeriesRow[] }) {
  // Also serves as the text alternative to the chart's colors.
  return (
    <table className="data">
      <thead>
        <tr><th scope="col">AP</th><th scope="col" className="num">受信</th><th scope="col" className="num">平均</th><th scope="col" className="num">範囲</th></tr>
      </thead>
      <tbody>
        {apNames(series).map((ap, slot) => {
          const values = series.map(row => row[ap]).filter((v): v is number => typeof v === 'number');
          const mean = values.reduce((sum, v) => sum + v, 0) / values.length;
          return (
            <tr key={ap}>
              <td><i className={`swatch s${slot + 1}`} />{ap}</td>
              <td className="num">{values.length}/{series.length}回</td>
              <td className="num">{mean.toFixed(1)}</td>
              <td className="num">{Math.min(...values).toFixed(0)} 〜 {Math.max(...values).toFixed(0)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
