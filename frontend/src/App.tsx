import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { adminApi, api, type AdminTeacher, type AreaConfig, type Config, type Research, type Teacher } from './api';

type View = 'students' | 'display' | 'research' | 'admin';
const views: { id: View; label: string }[] = [
  { id: 'students', label: '先生をさがす' }, { id: 'display', label: '一覧ディスプレイ' },
  { id: 'research', label: '実験データ' }, { id: 'admin', label: '開発用管理' },
];
const reasonLabels: Record<string, string> = {
  stale: '測定情報が古くなっています', stale_data: '測定情報が古くなっています',
  insufficient_data: '測定データが足りません', insufficient_aps: '測定できたAPが不足しています',
  unknown_ap: '対応するAPが確認できません', unmapped_ap: '対応するAPが確認できません',
  low_confidence: '候補を絞り込めません', ambiguous: '複数の候補が拮抗しています',
  unfamiliar: '登録エリアと測定値が異なります', unknown_area: '登録エリアと測定値が異なります',
  no_observation: '測定情報がありません', no_data: '測定情報がありません',
  future: '測定時刻を確認してください', future_timestamp: '測定時刻を確認してください', future_measurement: '測定時刻を確認してください',
  unfamiliar_pattern: '登録エリアと測定値が異なります', insufficient_overlap: '照合できるAPが不足しています',
  source_mismatch: '測定データの取得方式を確認してください', no_training_data: '学習データがありません',
};
function Icon({ name, size = 18 }: { name: string; size?: number }) {
  const paths: Record<string, ReactNode> = {
    search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4.5 4.5" /></>,
    refresh: <><path d="M20 7v5h-5M4 17v-5h5" /><path d="M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1" /></>,
    close: <path d="m6 6 12 12M6 18 18 6" />,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}
function relativeTime(value: string | null) {
  if (!value) return '測定なし';
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 60000));
  if (!Number.isFinite(minutes)) return '時刻不明';
  if (minutes < 1) return '1分未満前';
  if (minutes < 60) return `${minutes}分前`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)}時間前`;
  return `${Math.floor(minutes / 1440)}日前`;
}
function dateLabel(value: string | null) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString('ja-JP', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}
function normalizeName(value: string) { return value.normalize('NFKC').replace(/\s+/g, '').replace(/先生$/, '').toLocaleLowerCase(); }
function readView(): View {
  const value = window.location.hash.slice(1);
  return views.some(v => v.id === value) ? value as View : 'students';
}
export default function App() {
  const [view, setView] = useState<View>(readView);
  const [teachers, setTeachers] = useState<Teacher[]>([]);
  const [areas, setAreas] = useState<AreaConfig>({ areas: [], ap_areas: {} });
  const [config, setConfig] = useState<Config>({ algorithm: 'knn', algorithms: [], demo: true });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [lastFetch, setLastFetch] = useState<string | null>(null);
  const [clockNow, setClockNow] = useState(Date.now);
  const [query, setQuery] = useState('');
  const [subject, setSubject] = useState('');
  const requestSequence = useRef(0);
  const searchInput = useRef<HTMLInputElement>(null);
  const loadTeachers = useCallback(async () => {
    // A slow older request must never replace a newer privacy or area response.
    const sequence = ++requestSequence.current;
    try {
      const result = await api<{ teachers: Teacher[] }>('/teachers');
      if (sequence !== requestSequence.current) return;
      setTeachers(result.teachers); setClockNow(Date.now()); setError(''); setLastFetch(new Date().toISOString());
    } catch (e) { if (sequence === requestSequence.current) setError((e as Error).message); }
    finally { if (sequence === requestSequence.current) setLoading(false); }
  }, []);
  useEffect(() => {
    void loadTeachers();
    void Promise.all([api<Pick<AreaConfig, 'areas'>>('/areas'), api<Config>('/config')]).then(([a, c]) => { setAreas({ ...a, ap_areas: {} }); setConfig(c); }).catch(e => setError(e.message));
    const interval = window.setInterval(() => void loadTeachers(), 30000);
    const clockInterval = window.setInterval(() => setClockNow(Date.now()), 15000);
    const change = () => setView(readView());
    window.addEventListener('hashchange', change);
    return () => { ++requestSequence.current; window.clearInterval(interval); window.clearInterval(clockInterval); window.removeEventListener('hashchange', change); };
  }, [loadTeachers]);
  const areaLabel = useCallback((id: string | null) => areas.areas.find(a => a.id === id)?.label || id || '位置不明', [areas]);
  const subjects = useMemo(() => [...new Set(teachers.map(t => t.subject))].sort(), [teachers]);
  const safeTeachers = teachers.map(t => {
    if (t.status !== 'located') return t;
    const measuredAt = t.updated_at ? new Date(t.updated_at).getTime() : NaN;
    if (!Number.isFinite(measuredAt) || clockNow - measuredAt >= 180000) return { ...t, status: 'unknown' as const, area: null, reason: 'stale' };
    return measuredAt - clockNow > 5000 ? { ...t, status: 'unknown' as const, area: null, reason: 'future_measurement' } : t;
  });
  const filtered = safeTeachers.filter(t => normalizeName(t.name).includes(normalizeName(query)) && (!subject || t.subject === subject));
  const shownTeachers = view === 'display' ? safeTeachers : filtered;
  const navigate = (id: View) => { window.location.hash = id; setView(id); };
  const clearSearch = () => { setQuery(''); searchInput.current?.focus(); };
  return <div className={`app ${view === 'display' ? 'display-mode' : ''}`}>
    <a className="skip-link" href="#main" onClick={e => { e.preventDefault(); document.getElementById('main')?.focus(); }}>本文へ移動</a>
    <header className="site-header"><div className="header-inner">
      <a href="#students" className="school-name" onClick={() => navigate('students')}>市川昴高等学校<span>研究プロトタイプ</span></a>
      <nav className="primary-nav" aria-label="メインナビゲーション">{views.slice(0, 2).map(v => <button key={v.id} aria-current={view === v.id ? 'page' : undefined} onClick={() => navigate(v.id)}>{v.label}</button>)}</nav>
      <nav className="tools-nav" aria-label="研究・開発用">{views.slice(2).map(v => <button key={v.id} aria-current={view === v.id ? 'page' : undefined} onClick={() => navigate(v.id)}>{v.label}</button>)}</nav>
    </div></header>
    <main id="main" tabIndex={-1}>
      {(view === 'students' || view === 'display') && <>
        <section className="page-heading directory-heading">
          <div><h1>教員PCのエリア案内</h1><p>PCの推定エリアです。先生本人の現在地を保証するものではありません。</p></div>
          <span className="demo-note">模擬データ<br /><small>先生・測定値はすべて架空です</small></span>
        </section>
        {view === 'students' && <section className="search-section" aria-label="先生の検索">
          <label className="name-field"><span>先生の名前</span><div className="search-control"><Icon name="search" /><input ref={searchInput} type="search" aria-label="先生の名前で検索" placeholder="姓・名の一部でも検索できます" value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); clearSearch(); } }} />{query && <button type="button" className="clear-search" aria-label="名前検索をクリア" onClick={clearSearch}><Icon name="close" size={16} /></button>}</div></label>
          <label className="subject-field"><span>教科</span><select aria-label="教科で絞り込み" value={subject} onChange={e => setSubject(e.target.value)}><option value="">すべての教科</option>{subjects.map(s => <option key={s}>{s}</option>)}</select></label>
        </section>}
        <div className="list-meta"><p>{view === 'students' && (query || subject) ? <><strong>{shownTeachers.length}名</strong><span> / 登録 {teachers.length}名</span></> : <><strong>{teachers.length}名</strong><span>{view === 'display' ? 'を表示' : 'を登録'}</span></>}</p><div className="refresh-meta"><span>{lastFetch ? `画面取得 ${dateLabel(lastFetch)}` : '読み込み中'}<small>30秒ごとに更新</small></span><button className="text-button refresh-button" onClick={() => void loadTeachers()} aria-label="最新の情報に更新"><Icon name="refresh" size={16} />更新</button></div></div>
        {error && <div className="error-box" role="alert"><strong>データを更新できませんでした。</strong> {error}<p>前回取得した情報を表示しています。3分を過ぎた測定は「位置不明」になります。</p></div>}
        {loading ? <div className="empty-state" role="status">先生の情報を読み込んでいます…</div> : shownTeachers.length ? <div className="directory-wrap"><table className="directory-table" aria-label="先生の検索結果"><thead><tr><th scope="col">名前</th><th scope="col">教科</th><th scope="col">PCの推定エリア</th><th scope="col">最終測定</th></tr></thead><tbody>{shownTeachers.map(t => <TeacherRow key={t.id} teacher={t} areaLabel={areaLabel} />)}</tbody></table></div> : <div className="empty-state"><h2>条件に合う先生が見つかりません</h2><p>名前や教科の条件を変更してください。</p><button className="secondary-button" onClick={() => { setQuery(''); setSubject(''); searchInput.current?.focus(); }}>検索条件をクリア</button></div>}
        <aside className="directory-help"><p><strong>「位置不明」について</strong>測定から3分以上経過した場合や、候補を絞れない場合に表示します。</p><p>先生にご用の際は、必要に応じて職員室へお声がけください。</p></aside>
      </>}
      {view === 'research' && <ResearchView areaLabel={areaLabel} />}
      {view === 'admin' && <AdminView config={config} setConfig={setConfig} areas={areas} setAreas={setAreas} onUpdated={loadTeachers} areaLabel={areaLabel} />}
    </main>
    <footer className="site-footer"><span>コンピューター部・大学生による共同研究</span><span>実ネットワーク未接続</span></footer>
  </div>;
}
function TeacherRow({ teacher: t, areaLabel }: { teacher: Teacher; areaLabel: (id: string | null) => string }) {
  const located = t.status === 'located';
  const privateStatus = t.status === 'private';
  const reason = reasonLabels[t.reason || ''] || '測定情報が不足しているか、候補を絞り込めません。';
  return <tr className={`teacher-row ${t.status}`}>
    <th scope="row" className="teacher-name"><h2>{t.name}<span>{t.name.endsWith('先生') ? '' : '先生'}</span></h2></th>
    <td className="teacher-subject">{t.subject}</td>
    <td className="teacher-area"><span className="mobile-label">PCの推定エリア</span><strong>{privateStatus ? '非公開' : located ? areaLabel(t.area) : '位置不明'}</strong>{!located && <small>{privateStatus ? '所在情報は公開されていません' : reason}</small>}</td>
    <td className="teacher-time"><span className="mobile-label">最終測定</span>{privateStatus ? <span className="not-applicable">—</span> : t.updated_at ? <><time dateTime={t.updated_at} title={new Date(t.updated_at).toLocaleString('ja-JP')}>{dateLabel(t.updated_at)}</time><small>{relativeTime(t.updated_at)}</small></> : <span className="not-applicable">測定情報なし</span>}</td>
  </tr>;
}
const algorithmLabels: Record<string, string> = { strongest_ap: '最強AP', connected_ap: '接続先AP', knn: 'k-NN', weighted_knn: '距離重み付きk-NN', '1nn': '1-NN', rank: 'RSSI順位', gaussian: '確率的分類' };
const preprocessingLabels: Record<string, string> = { none: 'なし', mean: '平均', median: '中央値', ema: 'EMA', kalman: 'カルマンフィルタ', robust_mean: '頑健な平均' };
function ResearchView({ areaLabel }: { areaLabel: (id: string | null) => string }) {
  const [data, setData] = useState<Research | null>(null);
  const [error, setError] = useState('');
  useEffect(() => { void api<Research>('/research').then(setData).catch(e => setError(e.message)); }, []);
  return <>
    <section className="page-heading"><div><h1>実験データ</h1><p>位置推定方式の比較と、模擬RSSIの観測記録。</p></div></section>
    <p className="research-disclaimer">シミュレーションによる評価です。学校の実環境での精度を示すものではありません。</p>
    {error ? <div role="alert" className="error-box">実験データを取得できませんでした。{error}</div> : !data ? <div role="status" className="empty-state">実験データを読み込んでいます…</div> : <>
      <dl className="research-meta"><div><dt>実験ID</dt><dd>{data.experiment_id || '未実行'}</dd></div><div><dt>データソース</dt><dd>{data.source === 'simulation' ? '模擬データ' : data.source}</dd></div><div><dt>評価方法</dt><dd>学習・検証・テストを分離</dd></div></dl>
      <div className="research-grid"><section className="notebook-section"><div className="section-heading"><h2>APごとのRSSI</h2><span className="unit">単位：dBm</span></div>{data.series?.length ? <SignalChart series={data.series} /> : <p className="section-empty">時系列データはまだありません。</p>}<p className="chart-caption">静止セッションの模擬観測値。値が0に近いほど電波が強いことを表します。</p></section>
      <section className="notebook-section"><div className="section-heading"><h2>推定候補の比較</h2></div>{data.candidates?.length ? <div className="candidate-list">{data.candidates.map(c => <div className="candidate" key={c.area}><div><span>{areaLabel(c.area)}</span><strong>{c.score.toFixed(3)}</strong></div><div className="bar-track"><i style={{ width: `${Math.max(0, Math.min(100, c.score / Math.max(...data.candidates.map(x => x.score), .001) * 100))}%` }} /></div></div>)}</div> : <p className="section-empty">候補データはありません。</p>}<p className="chart-caption">類似度は比較用のスコアです。正解する確率ではありません。</p></section></div>
      <section className="notebook-section results-section"><div className="section-heading"><h2>方式別の評価結果</h2><span>A〜N 比較実験</span></div>{data.metrics?.length ? <><div className="table-scroll"><table className="data-table"><thead><tr><th>実験</th><th>推定方式 / 前処理</th><th>エリア正解率</th><th>誤表示率</th><th>位置不明率</th><th>表示した結果の正解率</th><th>推定時間</th></tr></thead><tbody>{data.metrics.map(m => <tr key={m.id}><td>{m.id}</td><td><strong>{algorithmLabels[m.algorithm] || m.algorithm}</strong><small>{preprocessingLabels[m.preprocessing] || m.preprocessing}</small></td><td className="metric-primary">{percent(m.accuracy)}</td><td>{percent(m.false_display_rate)}</td><td>{percent(m.unknown_rate)}</td><td>{m.precision == null ? '—' : percent(m.precision)}</td><td>{m.latency_ms.toFixed(2)} ms</td></tr>)}</tbody></table></div><p className="chart-caption">正解率・誤表示率・位置不明率の分母は全テスト測定。表示した結果の正解率の分母は、位置を表示した測定です。</p></> : <div className="section-empty"><h3>保存された実験結果はありません</h3><p>READMEの実験コマンドを実行すると、集計結果を確認できます。</p></div>}</section>
      <aside className="research-note"><h2>結果の読み方と制約</h2><p>{data.note || 'シミュレーションは開発・比較用です。実測データでの検証が必要です。'}</p></aside>
    </>}
  </>;
}
function percent(value: number) { return `${(value * 100).toFixed(1)}%`; }
function SignalChart({ series }: { series: Research['series'] }) {
  const colors = ['#a34e32', '#233f59', '#b18a39', '#757b77'];
  const aps = [...new Set(series.flatMap(row => Object.keys(row).filter(k => k !== 'time')))].filter(k => series.some(row => typeof row[k] === 'number'));
  const width = 640, height = 232, left = 44, right = 16, top = 12, bottom = 32;
  const x = (i: number) => left + i / Math.max(1, series.length - 1) * (width - left - right);
  const y = (n: number) => top + (Math.min(-20, Math.max(-110, n)) + 20) / -90 * (height - top - bottom);
  return <><svg className="signal-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`模擬RSSI時系列、${aps.join('、')}、${series.length}測定`}>
    {[-20, -40, -60, -80, -100].map(n => <g key={n}><line x1={left} y1={y(n)} x2={width - right} y2={y(n)} stroke="#deddd5" /><text x={left - 9} y={y(n) + 4} textAnchor="end" fill="#6c736e" fontSize="11">{n}</text></g>)}
    {aps.map((ap, ai) => {
      let path = '', open = false;
      series.forEach((row, i) => { const v = row[ap]; if (typeof v !== 'number') { open = false; return; } path += `${open ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)} `; open = true; });
      return <path key={ap} d={path} fill="none" stroke={colors[ai % colors.length]} strokeWidth="2" strokeLinejoin="round" />;
    })}
    {[0, Math.floor((series.length - 1) / 2), series.length - 1].map((i, ix) => <text key={ix} x={x(i)} y={height - 8} textAnchor={ix === 0 ? 'start' : ix === 2 ? 'end' : 'middle'} fill="#6c736e" fontSize="11">{String(series[i]?.time || '').slice(11, 19) || `測定 ${i + 1}`}</text>)}
  </svg><div className="chart-legend">{aps.map((ap, i) => <span key={ap}><i style={{ background: colors[i % colors.length] }} />{ap}</span>)}</div></>;
}
function AdminView({ config, setConfig, areas, setAreas, onUpdated, areaLabel }: { config: Config; setConfig: (c: Config) => void; areas: AreaConfig; setAreas: (a: AreaConfig) => void; onUpdated: () => Promise<void>; areaLabel: (id: string | null) => string }) {
  const [token, setToken] = useState('dev-demo-token');
  const [teachers, setTeachers] = useState<AdminTeacher[]>([]);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [pending, setPending] = useState(false);
  const [newName, setNewName] = useState('');
  const [newSubject, setNewSubject] = useState('');
  const [newDevice, setNewDevice] = useState('');
  const [teacherId, setTeacherId] = useState('');
  const [readings, setReadings] = useState<Record<string, string>>({ AP_A: '-48', AP_B: '-68', AP_C: '-78', AP_D: '-84' });
  const [connectedAp, setConnectedAp] = useState('AP_A');
  const [timestamp, setTimestamp] = useState('');
  const [algorithm, setAlgorithm] = useState(config.algorithm);
  const [mapping, setMapping] = useState(areas.ap_areas);
  useEffect(() => setAlgorithm(config.algorithm), [config.algorithm]);
  useEffect(() => setMapping(areas.ap_areas), [areas.ap_areas]);
  const refresh = useCallback(async (key: string) => {
    const [result, apConfig] = await Promise.all([adminApi<{ teachers: AdminTeacher[] }>('/teachers', key), adminApi<{ ap_areas: Record<string, string> }>('/ap-areas', key)]);
    setTeachers(result.teachers); setMapping(apConfig.ap_areas);
    setTeacherId(current => current || result.teachers[0]?.id || '');
  }, []);
  useEffect(() => { void refresh('dev-demo-token').catch(e => setError(e.message)); }, [refresh]);
  async function action(fn: () => Promise<void>, success: string) {
    setError(''); setMessage(''); setPending(true);
    let completed = false;
    try { await fn(); completed = true; await refresh(token); await onUpdated(); setMessage(success); }
    catch (e) { setError((completed ? '操作は完了しましたが、表示の再取得に失敗しました。' : '') + (e as Error).message); }
    finally { setPending(false); }
  }
  const register = (e: FormEvent) => {
    e.preventDefault();
    void action(async () => { await adminApi('/teachers', token, 'POST', { name: newName.trim(), subject: newSubject.trim(), device_id: newDevice.trim() }); setNewName(''); setNewSubject(''); setNewDevice(''); }, '架空の先生を登録しました。');
  };
  const submitObservation = (e: FormEvent) => {
    e.preventDefault();
    const values = Object.fromEntries(Object.entries(readings).filter(([, v]) => v.trim() !== '').map(([k, v]) => [k, Number(v)]));
    if (!Object.keys(values).length) { setError('RSSIを1つ以上入力してください。'); return; }
    void action(async () => {
      await adminApi('/observations', token, 'POST', { teacher_id: teacherId, readings: values, ...(connectedAp ? { connected_ap: connectedAp } : {}), ...(timestamp ? { timestamp: new Date(timestamp).toISOString() } : {}) });
    }, '模擬測定値を投入し、推定結果を更新しました。');
  };
  return <>
    <section className="page-heading"><div><h1>開発用管理</h1><p>架空の先生と模擬測定値を使って、推定動作を確認します。</p></div><span className="plain-label">ローカル開発専用</span></section>
    <p className="admin-disclaimer"><strong>実在する教員の情報は登録しないでください。</strong>実運用には学校の承認、本人の同意、個別アカウントによる認証・認可が必要です。</p>
    <section className="auth-bar" aria-label="開発用API認証"><label>開発用APIトークン<input type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} /></label><button className="secondary-button" disabled={pending} onClick={() => void action(() => refresh(token), '管理データを取得しました。')}>接続を確認</button><p>トークンはこの画面のメモリ内だけで保持します。</p></section>
    {error && <div className="error-box" role="alert">{error}</div>}{message && <div className="success-box" role="status">{message}</div>}
    <div className="admin-grid">
      <section className="task-section"><h2>架空の先生を登録</h2><form className="form-stack" onSubmit={register}><label>表示名<input required maxLength={60} placeholder="例：星野 あかり" value={newName} onChange={e => setNewName(e.target.value)} /></label><div className="form-row"><label>教科<input required maxLength={30} placeholder="例：情報科" value={newSubject} onChange={e => setNewSubject(e.target.value)} /></label><label>実験端末ID<input required maxLength={80} placeholder="例：demo-pc-07" value={newDevice} onChange={e => setNewDevice(e.target.value)} /></label></div><p className="field-help">実験端末IDは生徒用のAPI・画面に表示しません。</p><button className="primary-button" disabled={pending}>先生を登録する</button></form></section>
      <section className="task-section"><h2>推定方式を選ぶ</h2><form className="form-stack" onSubmit={e => { e.preventDefault(); void action(async () => { await adminApi('/config', token, 'PUT', { algorithm }); setConfig({ ...config, algorithm }); }, '推定方式を変更しました。'); }}><label>アルゴリズム<select value={algorithm} onChange={e => setAlgorithm(e.target.value)}>{config.algorithms.map(a => <option key={a.id} value={a.id}>{a.label}</option>)}</select></label><p className="field-help">信頼性判定を満たさない測定には「位置不明」を返します。スコアは確率ではありません。</p><button className="primary-button" disabled={pending || !config.algorithms.length}>推定方式を適用</button></form></section>
      <section className="task-section"><h2>模擬RSSIを投入</h2><form className="form-stack" onSubmit={submitObservation}><label>対象の先生<select required value={teacherId} onChange={e => setTeacherId(e.target.value)}><option value="" disabled>先生を選択</option>{teachers.map(t => <option key={t.id} value={t.id}>{t.name} / {t.subject}</option>)}</select></label><div className="rssi-inputs">{Object.keys(readings).map(ap => <label key={ap}>{ap}<div><input type="number" min={-120} max={-1} step="0.1" aria-label={`${ap} RSSI`} value={readings[ap]} onChange={e => setReadings({ ...readings, [ap]: e.target.value })} /><span>dBm</span></div></label>)}</div><p className="field-help">空欄はAP欠損として送信します。RSSIは −120〜−1 dBm。</p><div className="form-row"><label>接続AP<select value={connectedAp} onChange={e => setConnectedAp(e.target.value)}><option value="">不明</option>{Object.keys(readings).map(ap => <option key={ap}>{ap}</option>)}</select></label><label>測定日時（空欄＝現在）<input type="datetime-local" value={timestamp} onChange={e => setTimestamp(e.target.value)} /></label></div><button className="primary-button" disabled={pending || !teacherId}>測定値を送って推定</button></form></section>
      <section className="task-section"><h2>APとエリアの対応</h2><form className="form-stack" onSubmit={e => { e.preventDefault(); void action(async () => { await adminApi('/ap-areas', token, 'PUT', { ap_areas: mapping }); setAreas({ ...areas, ap_areas: mapping }); }, 'APとエリアの対応を更新しました。'); }}><div className="ap-mapping">{Object.entries(mapping).map(([ap, area]) => <label key={ap}><span>{ap}</span><select aria-label={`${ap} の対応エリア`} value={area} onChange={e => setMapping({ ...mapping, [ap]: e.target.value })}>{areas.areas.map(a => <option key={a.id} value={a.id}>{a.label}</option>)}</select></label>)}</div><p className="field-help">接続AP・最強AP方式の対応表です。実際の学校のAP構成は未確認です。</p><button className="primary-button" disabled={pending || !Object.keys(mapping).length}>対応表を保存</button></form></section>
    </div>
    <section className="notebook-section admin-teachers"><div className="section-heading"><h2>表示状態を確認</h2><button className="secondary-button" disabled={pending} onClick={() => void action(async () => { await adminApi('/demo-refresh', token, 'POST'); }, '架空の先生の模擬測定値を更新しました。')}><Icon name="refresh" size={16} />模擬データを更新</button></div><p className="field-help directory-help">更新ボタンは新しい模擬測定を生成します。実ネットワークへの接続は行いません。</p><div className="table-scroll"><table className="data-table"><thead><tr><th>先生 / 教科</th><th>実験端末ID</th><th>表示状態</th><th>推定エリア</th><th>公開設定</th></tr></thead><tbody>{teachers.map(t => <tr key={t.id}><td><strong>{t.name}</strong><small>{t.subject}</small></td><td><code>{t.device_id}</code></td><td>{t.status === 'located' ? 'エリア推定あり' : t.status === 'private' ? '非公開' : '位置不明'}</td><td>{t.status === 'located' ? areaLabel(t.area) : '—'}</td><td><button className="text-button privacy-button" disabled={pending} aria-label={`${t.name}を${t.private ? '公開' : '非公開'}にする`} onClick={() => void action(async () => { await adminApi(`/teachers/${t.id}`, token, 'PATCH', { private: !t.private }); }, `${t.name}の公開設定を変更しました。`)}>{t.private ? '公開にする' : '非公開にする'}</button></td></tr>)}</tbody></table></div>{!teachers.length && <p className="section-empty">管理データがありません。APIトークンと接続を確認してください。</p>}</section>
  </>;
}
