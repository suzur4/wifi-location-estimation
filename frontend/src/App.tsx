import { useCallback, useEffect, useRef, useState } from 'react';
import { api, type Area, type Config, type Teacher } from './api';
import { withFreshness } from './lib/teachers';
import { AdminView } from './views/AdminView';
import { DirectoryView } from './views/DirectoryView';
import { ResearchView } from './views/ResearchView';

type View = 'students' | 'display' | 'research' | 'admin';

const mainViews: { id: View; label: string }[] = [
  { id: 'students', label: '先生をさがす' },
  { id: 'display', label: '掲示用一覧' },
];
const toolViews: { id: View; label: string }[] = [
  { id: 'research', label: '実験データ' },
  { id: 'admin', label: '管理（開発用）' },
];
const POLL_MS = 30_000;
const TICK_MS = 5_000;
const NARROW = '(max-width: 720px)';

function readView(): View {
  const value = window.location.hash.slice(1);
  return [...mainViews, ...toolViews].some(v => v.id === value) ? value as View : 'students';
}

/** On phones the research/admin links move to the footer, keeping the header to two rows. */
function useNarrowScreen() {
  const [narrow, setNarrow] = useState(() => window.matchMedia?.(NARROW).matches ?? false);
  useEffect(() => {
    const media = window.matchMedia?.(NARROW);
    if (!media) return;
    const change = () => setNarrow(media.matches);
    media.addEventListener('change', change);
    return () => media.removeEventListener('change', change);
  }, []);
  return narrow;
}

export default function App() {
  const [view, setView] = useState<View>(readView);
  const [teachers, setTeachers] = useState<Teacher[]>([]);
  const [areas, setAreas] = useState<Area[]>([]);
  const [config, setConfig] = useState<Config>({ algorithm: 'knn', algorithms: [], demo: true });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [metadataErrors, setMetadataErrors] = useState({ areas: '', config: '' });
  const [lastFetch, setLastFetch] = useState<number | null>(null);
  const [now, setNow] = useState(Date.now);
  // The admin token lives only in memory, so switching views keeps it but a reload forgets it.
  const [adminToken, setAdminToken] = useState('');
  const requestSequence = useRef(0);
  const configRevision = useRef(0);
  const previousView = useRef(view);
  const narrow = useNarrowScreen();

  const loadTeachers = useCallback(async (reportFailure = false) => {
    // A slow older request must never replace a newer privacy or area response.
    const sequence = ++requestSequence.current;
    const revision = configRevision.current;
    const current = () => sequence === requestSequence.current;
    const failures: Error[] = [];
    // Each response can recover independently. In particular, a successful teacher
    // request must not hide a failed settings request or discard usable area names.
    await Promise.allSettled([
      api<{ teachers: Teacher[] }>('/teachers').then(result => {
        if (!current()) return;
        setTeachers(result.teachers);
        setNow(Date.now());
        setLastFetch(Date.now());
        setError('');
      }).catch((e: Error) => { if (current()) { failures.push(e); setError(e.message); } })
        .finally(() => { if (current()) setLoading(false); }),
      api<{ areas: Area[] }>('/areas').then(result => {
        if (!current()) return;
        setAreas(result.areas);
        setMetadataErrors(previous => ({ ...previous, areas: '' }));
      }).catch((e: Error) => {
        if (current()) {
          failures.push(e);
          setMetadataErrors(previous => ({ ...previous, areas: `エリア名を読み込めませんでした。${e.message}` }));
        }
      }),
      api<Config>('/config').then(result => {
        if (!current() || revision !== configRevision.current) return;
        setConfig(result);
        setMetadataErrors(previous => ({ ...previous, config: '' }));
      }).catch((e: Error) => {
        if (current() && revision === configRevision.current) {
          failures.push(e);
          setMetadataErrors(previous => ({ ...previous, config: `推定方式の設定を読み込めませんでした。${e.message}` }));
        }
      }),
    ]);
    // Polling and manual retries handle their errors in the screen. The admin
    // save flow also needs to know whether its follow-up display reload failed.
    if (reportFailure && current() && failures.length) throw new Error(failures.map(e => e.message).join(' '));
  }, []);

  const refreshAfterAdmin = useCallback(() => loadTeachers(true), [loadTeachers]);

  const updateConfig = useCallback((next: Config) => {
    // A GET started before this save must not restore the previous algorithm.
    ++configRevision.current;
    setConfig(next);
    setMetadataErrors(previous => ({ ...previous, config: '' }));
  }, []);

  useEffect(() => {
    void loadTeachers();
    // Polling pauses in a hidden tab and catches up as soon as the tab or network returns.
    const visible = () => document.visibilityState !== 'hidden';
    const poll = window.setInterval(() => { if (visible()) void loadTeachers(); }, POLL_MS);
    const tick = window.setInterval(() => setNow(Date.now()), TICK_MS);
    const wake = () => { if (visible()) { setNow(Date.now()); void loadTeachers(); } };
    const hashChange = () => setView(readView());
    document.addEventListener('visibilitychange', wake);
    window.addEventListener('online', wake);
    window.addEventListener('hashchange', hashChange);
    return () => {
      ++requestSequence.current;
      window.clearInterval(poll);
      window.clearInterval(tick);
      document.removeEventListener('visibilitychange', wake);
      window.removeEventListener('online', wake);
      window.removeEventListener('hashchange', hashChange);
    };
  }, [loadTeachers]);

  // After switching views, move keyboard and screen-reader focus to the new page title.
  useEffect(() => {
    const label = [...mainViews, ...toolViews].find(v => v.id === view)?.label;
    document.title = `${label} | 先生のPCエリア案内 | 市川昴高校`;
    if (previousView.current === view) return;
    previousView.current = view;
    document.getElementById('page-title')?.focus();
  }, [view]);

  const areaLabel = useCallback((id: string | null) => areas.find(a => a.id === id)?.label || id || '位置不明', [areas]);
  const freshTeachers = teachers.map(t => withFreshness(t, now));

  function navLink(item: { id: View; label: string }) {
    return (
      <a key={item.id} href={`#${item.id}`} aria-current={view === item.id ? 'page' : undefined}
        onClick={() => setView(item.id)}>{item.label}</a>
    );
  }

  return (
    <div className={view === 'display' ? 'app is-display' : 'app'}>
      <a className="skip-link" href="#main" onClick={event => { event.preventDefault(); document.getElementById('main')?.focus(); }}>
        本文へ移動
      </a>
      <header className="site-header">
        <div className="container header-row">
          <a className="brand" href="#students" onClick={() => setView('students')}>
            <span className="brand-school">市川昴高校</span>
            <span className="brand-name">先生のPCエリア案内</span>
          </a>
          <nav className="nav-main" aria-label="メインメニュー">{mainViews.map(navLink)}</nav>
          {!narrow && <nav className="nav-tools" aria-label="研究・開発用メニュー">{toolViews.map(navLink)}</nav>}
        </div>
      </header>
      <div className="notice">
        <p className="container"><strong>試作版</strong>先生と測定値はすべて架空のデータです。</p>
      </div>

      <main id="main" className="container" tabIndex={-1}>
        {(metadataErrors.areas || metadataErrors.config) && (
          <div className="alert alert-error" role="alert">
            {metadataErrors.areas && <p>{metadataErrors.areas}</p>}
            {metadataErrors.config && <p>{metadataErrors.config}</p>}
            <button type="button" className="button-text" onClick={() => void loadTeachers()}>設定を再読み込み</button>
          </div>
        )}
        {(view === 'students' || view === 'display') && (
          <DirectoryView mode={view === 'display' ? 'display' : 'search'} teachers={freshTeachers} loading={loading}
            error={error} lastFetch={lastFetch} now={now} onRefresh={() => void loadTeachers()} areaLabel={areaLabel} />
        )}
        {view === 'research' && <ResearchView areaLabel={areaLabel} />}
        {view === 'admin' && (
          <AdminView token={adminToken} onTokenChange={setAdminToken} config={config} onConfigChange={updateConfig}
            areas={areas} onUpdated={refreshAfterAdmin} areaLabel={areaLabel} />
        )}
      </main>

      <footer className="site-footer">
        <div className="container footer-row">
          {narrow && <nav className="nav-tools" aria-label="研究・開発用メニュー">{toolViews.map(navLink)}</nav>}
          <span>市川昴高校 コンピューター部・大学生による共同研究</span>
          <span>学校のネットワークには接続していません</span>
        </div>
      </footer>
    </div>
  );
}
