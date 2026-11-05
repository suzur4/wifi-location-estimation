import { useEffect, useMemo, useRef, useState } from 'react';
import type { Teacher } from '../api';
import { Icon } from '../components/Icon';
import { clockLabel, fullDateTime, relativeTime } from '../lib/format';
import { matchesName } from '../lib/search';
import { reasonLabel } from '../lib/teachers';

type Props = {
  mode: 'search' | 'display';
  teachers: Teacher[];
  loading: boolean;
  error: string;
  lastFetch: number | null;
  now: number;
  onRefresh: () => void;
  areaLabel: (id: string | null) => string;
};

export function DirectoryView({ mode, teachers, loading, error, lastFetch, now, onRefresh, areaLabel }: Props) {
  const [query, setQuery] = useState('');
  const [subject, setSubject] = useState('');
  const searchInput = useRef<HTMLInputElement>(null);
  const subjects = useMemo(() => [...new Set(teachers.map(t => t.subject))].sort((a, b) => a.localeCompare(b, 'ja')), [teachers]);
  const display = mode === 'display';
  const filtering = !display && (query.trim() !== '' || subject !== '');
  const shown = display ? teachers : teachers.filter(t => matchesName(t, query) && (!subject || t.subject === subject));

  function clearSearch() {
    setQuery('');
    setSubject('');
    searchInput.current?.focus();
  }

  return (
    <>
      <div className={display ? 'page-head display-head' : 'page-head'}>
        <div>
          <h1 id="page-title" tabIndex={-1}>{display ? '先生のPCエリア一覧' : '先生をさがす'}</h1>
          <p className="lead">先生が使っているPCのおおよその場所です。先生本人がその場所にいるとは限りません。</p>
        </div>
        {display && <DisplayClock now={now} />}
      </div>

      {!display && (
        <form className="search" role="search" onSubmit={event => event.preventDefault()}>
          <div className="field">
            <label htmlFor="search-name">名前・よみがな</label>
            <div className="search-box">
              <Icon name="search" />
              <input id="search-name" ref={searchInput} type="search" value={query} placeholder="例：たかはし、高橋"
                autoComplete="off" enterKeyHint="search" maxLength={100}
                onChange={event => setQuery(event.target.value)}
                onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); setQuery(''); } }} />
              {query && (
                <button type="button" className="search-clear" aria-label="名前の入力を消す"
                  onClick={() => { setQuery(''); searchInput.current?.focus(); }}>
                  <Icon name="close" size={16} />
                </button>
              )}
            </div>
          </div>
          <div className="field field-subject">
            <label htmlFor="search-subject">教科</label>
            <select id="search-subject" value={subject} onChange={event => setSubject(event.target.value)}>
              <option value="">すべて</option>
              {subjects.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
        </form>
      )}

      <div className="list-bar">
        <p className="list-count" aria-live="polite">
          {loading ? '' : filtering ? <><strong>{shown.length}名</strong>（全{teachers.length}名）</> : <strong>{teachers.length}名</strong>}
        </p>
        <p className="list-update">
          <span>{lastFetch ? `最終更新 ${clockLabel(lastFetch, now)}` : '読み込み中'}</span>
          <span className="muted">30秒ごとに自動更新</span>
        </p>
        {display
          ? <FullscreenButton />
          : <button type="button" className="button-text" onClick={onRefresh}><Icon name="refresh" size={16} />今すぐ更新</button>}
      </div>

      {error && (
        <div className="alert alert-error" role="alert">
          {lastFetch ? (
            <>
              <p><strong>情報を更新できませんでした。</strong>{error}</p>
              <p>前回取得した情報を表示しています。測定から3分を過ぎると「位置不明」に変わります。</p>
            </>
          ) : <p><strong>先生の情報を読み込めませんでした。</strong>{error}</p>}
        </div>
      )}

      {loading ? (
        <p className="empty" role="status">読み込んでいます…</p>
      ) : shown.length ? (
        <table className="directory">
          <caption className="visually-hidden">先生のPCの場所（推定）</caption>
          <thead>
            <tr><th scope="col">名前</th><th scope="col">教科</th><th scope="col">PCの場所（推定）</th><th scope="col">測定時刻</th></tr>
          </thead>
          <tbody>
            {shown.map(t => <TeacherRow key={t.id} teacher={t} now={now} areaLabel={areaLabel} brief={display} />)}
          </tbody>
        </table>
      ) : teachers.length ? (
        <div className="empty">
          <p><strong>条件に合う先生がいません。</strong>名前や教科を変えてお試しください。</p>
          <button type="button" className="button" onClick={clearSearch}>検索条件をクリア</button>
        </div>
      ) : lastFetch ? (
        <p className="empty">登録されている先生がいません。</p>
      ) : null}

      {!display && (
        <p className="note">
          「位置不明」は、測定から3分以上たったときや、場所を1つに絞れないときに表示します。先生が見つからないときは、職員室でたずねてください。
        </p>
      )}
    </>
  );
}

function TeacherRow({ teacher: t, now, areaLabel, brief }: { teacher: Teacher; now: number; areaLabel: (id: string | null) => string; brief: boolean }) {
  const area = t.status === 'located' ? areaLabel(t.area) : t.status === 'private' ? '非公開' : '位置不明';
  // The hallway display shows only the area; details stay on personal screens.
  const detail = brief || t.status === 'located' ? '' : t.status === 'private' ? '公開を停止しています' : reasonLabel(t.reason);
  const measured = t.status !== 'private' && t.updated_at;
  return (
    <tr className={`row is-${t.status}`}>
      <th scope="row" className="cell-name">
        <span className="name">{t.name}</span>
        {t.kana && <span className="kana">{t.kana}</span>}
      </th>
      <td className="cell-subject">{t.subject}</td>
      <td className="cell-area">
        <span className="area">{area}</span>
        {detail && <span className="area-detail">{detail}</span>}
      </td>
      <td className="cell-time">
        {measured ? (
          <>
            <span className="mobile-label" aria-hidden="true">測定</span>
            <time dateTime={t.updated_at!} title={fullDateTime(t.updated_at)}>{clockLabel(t.updated_at, now)}</time>
            <span className="ago">{relativeTime(t.updated_at, now)}</span>
          </>
        ) : <span className="muted"><span aria-hidden="true">—</span><span className="visually-hidden">なし</span></span>}
      </td>
    </tr>
  );
}

function DisplayClock({ now }: { now: number }) {
  const date = new Date(now);
  return (
    <p className="display-clock">
      <span>{date.toLocaleDateString('ja-JP', { month: 'long', day: 'numeric', weekday: 'short' })}</span>
      <strong>{date.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' })}</strong>
    </p>
  );
}

function FullscreenButton() {
  const [active, setActive] = useState(() => Boolean(document.fullscreenElement));
  useEffect(() => {
    const change = () => setActive(Boolean(document.fullscreenElement));
    document.addEventListener('fullscreenchange', change);
    return () => document.removeEventListener('fullscreenchange', change);
  }, []);
  if (!document.fullscreenEnabled) return null;
  const toggle = () => {
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined);
    else void document.documentElement.requestFullscreen().catch(() => undefined);
  };
  return (
    <button type="button" className="button-text" onClick={toggle}>
      <Icon name="expand" size={16} />{active ? '全画面を終了' : '全画面表示'}
    </button>
  );
}
