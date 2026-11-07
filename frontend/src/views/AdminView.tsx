import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { adminApi, ApiError, type AdminTeacher, type Area, type Config } from '../api';
import { Icon } from '../components/Icon';
import { reasonLabel, withFreshness } from '../lib/teachers';

const APS = ['AP_A', 'AP_B', 'AP_C', 'AP_D'];

type Props = {
  token: string;
  onTokenChange: (token: string) => void;
  config: Config;
  onConfigChange: (config: Config) => void;
  areas: Area[];
  now: number;
  onUpdated: () => Promise<void>;
  areaLabel: (id: string | null) => string;
};

export function AdminView({ token, onTokenChange, config, onConfigChange, areas, now, onUpdated, areaLabel }: Props) {
  const [tokenInput, setTokenInput] = useState('');
  const [teachers, setTeachers] = useState<AdminTeacher[]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [pending, setPending] = useState(false);
  const loadedToken = useRef('');
  const currentToken = useRef(token);
  currentToken.current = token;
  const busy = useRef(false);
  const mounted = useRef(false);
  const session = useRef(0);
  const mappingDirty = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; ++session.current; busy.current = false; };
  }, []);

  // All state writes, including the reload after a saved change, belong to one
  // connection generation. A late response cannot repopulate a disconnected view.
  const load = useCallback(async (key: string, current: () => boolean) => {
    const [list, apAreas] = await Promise.all([
      adminApi<{ teachers: AdminTeacher[] }>('/teachers', key),
      adminApi<{ ap_areas: Record<string, string> }>('/ap-areas', key),
    ]);
    if (!current()) return;
    setTeachers(list.teachers);
    // An unrelated operation must not discard an AP mapping still being edited.
    if (!mappingDirty.current) setMapping(apAreas.ap_areas);
    loadedToken.current = key;
  }, []);

  // Coming back to this view in the same tab reuses the token kept in memory.
  useEffect(() => {
    if (!token || loadedToken.current === token) return;
    const generation = ++session.current;
    const current = () => mounted.current && generation === session.current && currentToken.current === token;
    busy.current = true;
    setPending(true);
    void load(token, current).catch((e: Error) => { if (current()) fail(e); })
      .finally(() => { if (current()) { busy.current = false; setPending(false); } });
  }, [token, load]);

  function invalidateSession() {
    ++session.current;
    loadedToken.current = '';
    currentToken.current = '';
    busy.current = false;
    mappingDirty.current = false;
    onTokenChange('');
    setPending(false);
    setTeachers([]);
    setMapping({});
  }

  function fail(e: Error, prefix = '') {
    if (e instanceof ApiError && e.status === 401) {
      invalidateSession();
      setError('管理トークンが正しくないか、無効になりました。サーバーを起動したターミナルに表示されたトークンを入力してください。');
      return;
    }
    setError(prefix + e.message);
  }

  async function connect(event: FormEvent) {
    event.preventDefault();
    if (busy.current) return;
    const value = tokenInput.trim();
    // A header can carry only visible ASCII, so full-width characters would fail before reaching the server.
    if (!/^[\x21-\x7e]+$/.test(value)) {
      setError('管理トークンに使えない文字が含まれています。半角の英数字と記号で入力してください。');
      return;
    }
    const generation = ++session.current;
    const current = () => mounted.current && generation === session.current;
    busy.current = true;
    setError(''); setMessage(''); setPending(true);
    try {
      await load(value, current);
      if (!current()) return;
      onTokenChange(value);
      setTokenInput('');
      setMessage('管理画面に接続しました。');
    } catch (e) {
      if (current()) fail(e as Error);
    } finally {
      if (current()) { busy.current = false; setPending(false); }
    }
  }

  /** Saved callbacks run only in the session that made the change. */
  async function run(change: () => Promise<unknown>, success: string, after?: () => void, onSaved?: () => void) {
    // Buttons stay focusable while busy (aria-disabled), so a second press is ignored here instead.
    if (busy.current || !token) return;
    const generation = session.current;
    const current = () => mounted.current && generation === session.current && currentToken.current === token;
    busy.current = true;
    setError(''); setMessage(''); setPending(true);
    let saved = false;
    try {
      await change();
      saved = true;
      if (!current()) return;
      onSaved?.();
      await load(token, current);
      if (!current()) return;
      await onUpdated();
      if (!current()) return;
      setMessage(success);
      after?.();
    } catch (e) {
      if (!current()) return;
      if (saved) setMessage(success);
      fail(e as Error, saved ? '操作は完了しましたが、表示の再取得に失敗しました。' : '');
    } finally {
      if (current()) { busy.current = false; setPending(false); }
    }
  }

  function disconnect() {
    invalidateSession();
    setError('');
    setMessage('接続を解除しました。');
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1 id="page-title" tabIndex={-1}>管理（開発用）</h1>
          <p className="lead">架空の先生と模擬測定値で、推定の動きを確かめるための画面です。実在する先生の情報は登録しないでください。</p>
        </div>
      </div>

      {error && <div className="alert alert-error" role="alert"><p>{error}</p></div>}
      {/* The status region stays in the page so screen readers announce each new message. */}
      <div role="status">{message && <div className="alert alert-ok"><p>{message}</p></div>}</div>

      {!token ? (
        <form className="panel connect" onSubmit={connect}>
          <h2>管理トークンで接続</h2>
          <div className="field">
            <label htmlFor="admin-token">管理トークン</label>
            <input id="admin-token" type="password" autoComplete="off" spellCheck={false} required
              value={tokenInput} onChange={event => setTokenInput(event.target.value)} />
            <p className="help">
              サーバーを起動したターミナルに表示されるトークンを入力します。環境変数 <code>WIFI_ADMIN_TOKEN</code> を設定した場合はその値です。トークンはこのタブの中だけで使い、再読み込みすると消えます。
            </p>
          </div>
          <button className="button button-primary" disabled={pending || !tokenInput.trim()}>接続</button>
        </form>
      ) : (
        <>
          <div className="connected">
            <p>管理APIに接続しています</p>
            <button type="button" className="button-text" onClick={disconnect}>接続を解除</button>
          </div>
          <TeacherTable teachers={teachers.map(teacher => ({ ...teacher, ...withFreshness(teacher, now) }))}
            pending={pending} areaLabel={areaLabel} token={token} run={run} />
          <div className="admin-grid">
            <RegisterForm token={token} pending={pending} run={run} />
            <MeasurementForm token={token} pending={pending} run={run} teachers={teachers} />
            <AlgorithmForm token={token} pending={pending} run={run} config={config} onConfigChange={onConfigChange} />
            <MappingForm token={token} pending={pending} run={run} areas={areas} mapping={mapping} onChange={value => { mappingDirty.current = true; setMapping(value); }} onSaved={() => { mappingDirty.current = false; }} />
          </div>
        </>
      )}
    </>
  );
}

type Run = (change: () => Promise<unknown>, success: string, after?: () => void, onSaved?: () => void) => Promise<void>;

function statusText(t: AdminTeacher) {
  if (t.status === 'private') return '非公開';
  if (t.status === 'located') return '表示中';
  if (t.fsm?.phase === 'CANDIDATE') return `確認中（${t.fsm.confirmations}/${t.fsm.required_confirmations}回）`;
  return `位置不明（${reasonLabel(t.reason)}）`;
}

function TeacherTable({ teachers, pending, areaLabel, token, run }: { teachers: AdminTeacher[]; pending: boolean; areaLabel: (id: string | null) => string; token: string; run: Run }) {
  function remove(t: AdminTeacher) {
    if (pending || !window.confirm(`${t.name}を削除しますか？\n現在の測定データも削除されます。`)) return;
    // The deleted row took the focused button with it, so focus returns to the list heading.
    void run(() => adminApi(`/teachers/${encodeURIComponent(t.id)}`, token, 'DELETE'), `${t.name}を削除しました。`,
      () => document.getElementById('admin-teachers-title')?.focus());
  }
  return (
    <section className="section">
      <div className="section-head">
        <h2 id="admin-teachers-title" tabIndex={-1}>先生の一覧</h2>
        <button type="button" className="button" aria-disabled={pending || undefined}
          onClick={() => void run(() => adminApi('/demo-refresh', token, 'POST'), '模擬測定値を更新しました。')}>
          <Icon name="refresh" size={16} />模擬データを更新
        </button>
      </div>
      <p className="help">「模擬データを更新」は、非公開以外の先生に新しい模擬測定を作ります。学校のネットワークには接続しません。</p>
      {teachers.length ? (
        <div className="table-scroll">
          <table className="data">
            <thead>
              <tr><th scope="col">先生</th><th scope="col">実験端末ID</th><th scope="col">表示状態</th><th scope="col">推定エリア</th><th scope="col">操作</th></tr>
            </thead>
            <tbody>
              {teachers.map(t => (
                <tr key={t.id}>
                  <td><span className="cell-main">{t.name}</span><span className="cell-sub">{[t.kana, t.subject].filter(Boolean).join('・')}</span></td>
                  <td><code>{t.device_id}</code></td>
                  <td>{statusText(t)}</td>
                  <td>{t.status === 'located' ? areaLabel(t.area) : '—'}</td>
                  <td className="actions">
                    <button type="button" className="button-text" aria-disabled={pending || undefined}
                      aria-label={`${t.name}を${t.private ? '公開' : '非公開'}にする`}
                      onClick={() => void run(() => adminApi(`/teachers/${encodeURIComponent(t.id)}`, token, 'PATCH', { private: !t.private }),
                        `${t.name}を${t.private ? '公開' : '非公開'}にしました。`)}>
                      {t.private ? '公開にする' : '非公開にする'}
                    </button>
                    <button type="button" className="button-text is-danger" aria-disabled={pending || undefined}
                      aria-label={`${t.name}を削除`} onClick={() => remove(t)}>削除</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="empty">登録されている先生がいません。</p>}
    </section>
  );
}

function RegisterForm({ token, pending, run }: { token: string; pending: boolean; run: Run }) {
  const [name, setName] = useState('');
  const [kana, setKana] = useState('');
  const [subject, setSubject] = useState('');
  const [device, setDevice] = useState('');
  function submit(event: FormEvent) {
    event.preventDefault();
    void run(() => adminApi('/teachers', token, 'POST', { name: name.trim(), kana: kana.trim(), subject: subject.trim(), device_id: device.trim() }),
      '架空の先生を登録しました。', undefined, () => { setName(''); setKana(''); setSubject(''); setDevice(''); });
  }
  return (
    <form className="panel" onSubmit={submit}>
      <h2>架空の先生を登録</h2>
      <div className="field"><label htmlFor="new-name">名前</label>
        <input id="new-name" readOnly={pending} required maxLength={60} placeholder="例：星野 あかり" value={name} onChange={e => setName(e.target.value)} /></div>
      <div className="field"><label htmlFor="new-kana">よみがな（任意）</label>
        <input id="new-kana" readOnly={pending} maxLength={60} placeholder="例：ほしの あかり" value={kana} onChange={e => setKana(e.target.value)} />
        <p className="help">ひらがなかカタカナ。よみがなでも検索でき、一覧は五十音順になります。</p></div>
      <div className="field-row">
        <div className="field"><label htmlFor="new-subject">教科</label>
          <input id="new-subject" readOnly={pending} required maxLength={30} placeholder="例：情報" value={subject} onChange={e => setSubject(e.target.value)} /></div>
        <div className="field"><label htmlFor="new-device">実験端末ID</label>
          <input id="new-device" readOnly={pending} required maxLength={80} placeholder="例：demo-pc-07" value={device} onChange={e => setDevice(e.target.value)} /></div>
      </div>
      <p className="help">実験端末IDは生徒向けの画面とAPIには出しません。</p>
      <button className="button button-primary" aria-disabled={pending || undefined}>登録する</button>
    </form>
  );
}

function MeasurementForm({ token, pending, run, teachers }: { token: string; pending: boolean; run: Run; teachers: AdminTeacher[] }) {
  const [teacherId, setTeacherId] = useState('');
  const [readings, setReadings] = useState<Record<string, string>>({ AP_A: '-48', AP_B: '-68', AP_C: '-78', AP_D: '-84' });
  const [connectedAp, setConnectedAp] = useState('AP_A');
  const [timestamp, setTimestamp] = useState('');
  const [inputError, setInputError] = useState('');
  const selectable = teachers.filter(t => !t.private);
  const selected = selectable.some(t => t.id === teacherId) ? teacherId : selectable[0]?.id ?? '';

  function submit(event: FormEvent) {
    event.preventDefault();
    const values = Object.fromEntries(Object.entries(readings).filter(([, v]) => v.trim() !== '').map(([ap, v]) => [ap, Number(v)]));
    if (!Object.keys(values).length) { setInputError('RSSIを1つ以上入力してください。'); return; }
    setInputError('');
    void run(() => adminApi('/observations', token, 'POST', {
      teacher_id: selected,
      readings: values,
      ...(connectedAp ? { connected_ap: connectedAp } : {}),
      ...(timestamp ? { timestamp: new Date(timestamp).toISOString() } : {}),
    }), '模擬測定値を送り、推定結果を更新しました。');
  }
  return (
    <form className="panel" onSubmit={submit}>
      <h2>模擬測定を送る</h2>
      <div className="field"><label htmlFor="measure-teacher">先生</label>
        <select id="measure-teacher" required value={selected} onChange={e => setTeacherId(e.target.value)}>
          {!selectable.length && <option value="">公開中の先生がいません</option>}
          {selectable.map(t => <option key={t.id} value={t.id}>{t.name}（{t.subject}）</option>)}
        </select></div>
      <fieldset className="rssi">
        <legend>RSSI（dBm）</legend>
        {APS.map(ap => (
          <div className="field" key={ap}><label htmlFor={`rssi-${ap}`}>{ap}</label>
            <input id={`rssi-${ap}`} aria-label={`${ap}のRSSI`} type="number" inputMode="decimal" min={-120} max={0} step="0.1"
              value={readings[ap]} onChange={e => setReadings({ ...readings, [ap]: e.target.value })} /></div>
        ))}
      </fieldset>
      <p className="help">−120〜0の範囲で入力します。空欄のAPは「受信なし」として送ります。</p>
      {inputError && <p className="field-error" role="alert">{inputError}</p>}
      <div className="field-row">
        <div className="field"><label htmlFor="measure-ap">接続AP</label>
          <select id="measure-ap" value={connectedAp} onChange={e => setConnectedAp(e.target.value)}>
            <option value="">不明</option>
            {APS.map(ap => <option key={ap} value={ap}>{ap}</option>)}
          </select></div>
        <div className="field"><label htmlFor="measure-time">測定日時（空欄なら現在）</label>
          <input id="measure-time" type="datetime-local" value={timestamp} onChange={e => setTimestamp(e.target.value)} /></div>
      </div>
      <button className="button button-primary" aria-disabled={pending || undefined} disabled={!selected}>送信して推定</button>
    </form>
  );
}

function AlgorithmForm({ token, pending, run, config, onConfigChange }: { token: string; pending: boolean; run: Run; config: Config; onConfigChange: (config: Config) => void }) {
  const [algorithm, setAlgorithm] = useState(config.algorithm);
  useEffect(() => setAlgorithm(config.algorithm), [config.algorithm]);
  function submit(event: FormEvent) {
    event.preventDefault();
    void run(() => adminApi('/config', token, 'PUT', { algorithm }), '推定方式を変更しました。',
      undefined, () => onConfigChange({ ...config, algorithm }));
  }
  return (
    <form className="panel" onSubmit={submit}>
      <h2>推定方式</h2>
      {config.fsm?.enabled && <p className="help">表示前に新しい観測で同じ候補を{config.fsm.confirmations}回確認します。
        必要なAPは{config.fsm.min_aps}台、候補のスコア差は{config.fsm.min_margin}以上です。</p>}
      <div className="field"><label htmlFor="algorithm">使う方式</label>
        <select id="algorithm" value={algorithm} onChange={e => setAlgorithm(e.target.value)}>
          {config.algorithms.map(a => <option key={a.id} value={a.id}>{a.label}</option>)}
        </select>
        <p className="help">信頼できる結果にならない測定は「位置不明」になります。</p></div>
      <button className="button button-primary" aria-disabled={pending || undefined} disabled={!config.algorithms.length}>この方式にする</button>
    </form>
  );
}

function MappingForm({ token, pending, run, areas, mapping, onChange, onSaved }: { token: string; pending: boolean; run: Run; areas: Area[]; mapping: Record<string, string>; onChange: (mapping: Record<string, string>) => void; onSaved: () => void }) {
  function submit(event: FormEvent) {
    event.preventDefault();
    void run(() => adminApi('/ap-areas', token, 'PUT', { ap_areas: mapping }), 'APとエリアの対応を保存しました。', undefined, onSaved);
  }
  return (
    <form className="panel" onSubmit={submit}>
      <h2>APとエリアの対応</h2>
      <div className="mapping">
        {Object.entries(mapping).map(([ap, area]) => (
          <div className="field field-inline" key={ap}><label htmlFor={`map-${ap}`}>{ap}</label>
            <select id={`map-${ap}`} aria-label={`${ap}の対応エリア`} disabled={pending} value={area} onChange={e => onChange({ ...mapping, [ap]: e.target.value })}>
              {areas.map(a => <option key={a.id} value={a.id}>{a.label}</option>)}
            </select></div>
        ))}
      </div>
      <p className="help">「接続先AP」「最強AP」方式で使う対応表です。実際の学校のAP配置は未確認です。</p>
      <button className="button button-primary" aria-disabled={pending || undefined} disabled={!Object.keys(mapping).length}>対応表を保存</button>
    </form>
  );
}
