import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';

const teachers = [
  { id: '1', name: '星野 あかり', kana: 'ほしの あかり', subject: '情報科', status: 'located', area: '2F-east', updated_at: '2026-11-04T09:00:00Z', reason: null },
  { id: '2', name: '青木 そら', kana: 'あおき そら', subject: '数学科', status: 'unknown', area: null, updated_at: null, reason: 'insufficient_data' },
  { id: '3', name: '月野 ひかり', kana: 'つきの ひかり', subject: '国語科', status: 'private', area: 'private-secret-room', updated_at: '2026-11-04T01:23:45Z', reason: null, device_id: 'private-device-secret' },
];
const config = { algorithm: 'knn', algorithms: [{ id: 'knn', label: 'k-NN' }, { id: 'kalman', label: 'テスト方式' }], demo: true };
const research = {
  dataset: 'simulation', datasets: [{ id: 'simulation', label: '模擬データ（学校6エリア）' }, { id: 'uji', label: 'UJIIndoorLoc（大学の建物・階）' }],
  source: 'simulation', experiment_id: 'test-42', counts: [672, 192, 288],
  series: [{ time: '2026-11-04T00:00:00Z', AP_A: -50, AP_B: -70 }, { time: '2026-11-04T00:00:03Z', AP_A: -52, AP_B: null }],
  candidates: [{ area: '2F-east', score: .8 }],
  metrics: [{ id: 'A', algorithm: 'strongest_ap', preprocessing: 'none', accuracy: .5, false_display_rate: .2, unknown_rate: .3, precision: .714, latency_ms: .01 }],
  note: '学校の実環境での性能は未確認です。',
};
const uji = {
  ...research, dataset: 'uji', source: 'ujindoorloc', experiment_id: 'uji-test', series: [], candidates: [],
  metrics: [{ id: null, algorithm: '1nn', preprocessing: 'none', accuracy: .887, false_display_rate: .11, unknown_rate: .004, precision: .89, latency_ms: .25 }],
  citation: 'Torres-Sospedra et al. (2014)', license: 'CC BY 4.0', note: '公開データセットによる独立評価です。',
};

function json(data: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } }));
}
let mockFetch: ReturnType<typeof vi.fn<(url: string, options?: RequestInit) => Promise<Response>>>;
const calls = (path: string, method = 'GET') => mockFetch.mock.calls.filter(([url, options]) => url === path && (options?.method ?? 'GET') === method);

beforeEach(() => {
  window.location.hash = '';
  mockFetch = vi.fn((url: string, options?: RequestInit) => {
    const method = options?.method ?? 'GET';
    if (url === '/api/teachers') return json({ teachers, demo: true });
    if (url === '/api/areas') return json({ areas: [{ id: '2F-east', label: '2階 東側' }, { id: '1F-west', label: '1階 西側' }] });
    if (url === '/api/config') return json(config);
    if (url === '/api/admin/teachers' && method === 'POST') return json(teachers[0], 201);
    if (url === '/api/admin/teachers') return json({ teachers: teachers.map(t => ({ ...t, device_id: `demo-${t.id}`, private: t.status === 'private' })) });
    if (url.startsWith('/api/admin/teachers/') && method === 'DELETE') return Promise.resolve(new Response(null, { status: 204 }));
    if (url === '/api/admin/ap-areas') return json({ ap_areas: { AP_A: '2F-east' } });
    if (url === '/api/research?dataset=uji') return json(uji);
    if (url.startsWith('/api/research')) return json(research);
    return json({ detail: 'not found' }, 404);
  });
  vi.stubGlobal('fetch', mockFetch);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  vi.restoreAllMocks();
  delete (document as { visibilityState?: string }).visibilityState;
});

const row = (name: RegExp) => screen.getByRole('rowheader', { name }).closest('tr')!;
const findRow = async (name: RegExp) => (await screen.findByRole('rowheader', { name })).closest('tr')!;

async function connectAdmin(user: ReturnType<typeof userEvent.setup>, token = 'typed-token') {
  await user.click(screen.getByRole('link', { name: '管理（開発用）' }));
  await user.type(screen.getByLabelText('管理トークン'), token);
  await user.click(screen.getByRole('button', { name: '接続' }));
}

describe('student directory', () => {
  it('searches by name and filters by subject', async () => {
    const user = userEvent.setup();
    render(<App />);
    await findRow(/星野 あかり/);
    await user.type(screen.getByRole('searchbox', { name: '名前・よみがな' }), '星野');
    expect(screen.queryByRole('rowheader', { name: /青木 そら/ })).not.toBeInTheDocument();
    expect(screen.getByText('（全3名）', { exact: false })).toBeInTheDocument();
    await user.clear(screen.getByRole('searchbox'));
    await user.selectOptions(screen.getByRole('combobox', { name: '教科' }), '数学科');
    expect(row(/青木 そら/)).toBeInTheDocument();
    expect(screen.queryByRole('rowheader', { name: /星野 あかり/ })).not.toBeInTheDocument();
  });

  it('finds a teacher by reading in hiragana or katakana', async () => {
    const user = userEvent.setup();
    render(<App />);
    await findRow(/星野 あかり/);
    const search = screen.getByRole('searchbox', { name: '名前・よみがな' });
    await user.type(search, 'あおき');
    expect(row(/青木 そら/)).toBeInTheDocument();
    expect(screen.queryByRole('rowheader', { name: /星野 あかり/ })).not.toBeInTheDocument();
    await user.clear(search);
    await user.type(search, 'ホシノ');
    expect(row(/星野 あかり/)).toBeInTheDocument();
    expect(screen.queryByRole('rowheader', { name: /青木 そら/ })).not.toBeInTheDocument();
  });

  it('hides private area, timestamp and device identifiers and never requests admin data', async () => {
    render(<App />);
    const privateRow = await findRow(/月野 ひかり/);
    expect(within(privateRow).getByText('非公開')).toBeInTheDocument();
    expect(within(privateRow).getByText('公開を停止しています')).toBeInTheDocument();
    expect(privateRow.querySelector('time')).toBeNull();
    expect(screen.queryByText('private-secret-room')).not.toBeInTheDocument();
    expect(screen.queryByText('private-device-secret')).not.toBeInTheDocument();
    expect(mockFetch.mock.calls.some(([url]) => String(url).includes('/admin/'))).toBe(false);
    expect(screen.getByText('測定データが足りません')).toBeInTheDocument();
  });

  it('invalidates a located response whose measurement is already stale', async () => {
    const original = mockFetch.getMockImplementation()!;
    mockFetch.mockImplementation((url: string, options?: RequestInit) => url === '/api/teachers'
      ? json({ teachers: [{ ...teachers[0], updated_at: new Date(Date.now() - 181000).toISOString() }] }) : original(url, options));
    render(<App />);
    const staleRow = await findRow(/星野 あかり/);
    expect(within(staleRow).getByText('位置不明')).toBeInTheDocument();
    expect(within(staleRow).queryByText('2階 東側')).not.toBeInTheDocument();
    expect(within(staleRow).getByText('測定から3分以上たっています')).toBeInTheDocument();
  });

  it('expires a cached area during repeated network failures', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-11-04T09:00:00Z'));
    const original = mockFetch.getMockImplementation()!;
    let requests = 0;
    mockFetch.mockImplementation((url: string, options?: RequestInit) => {
      if (url !== '/api/teachers') return original(url, options);
      requests += 1;
      return requests === 1 ? json({ teachers: [teachers[0]] }) : Promise.reject(new TypeError('Failed to fetch'));
    });
    render(<App />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(screen.getByText('2階 東側')).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(195000); });
    expect(screen.queryByText('2階 東側')).not.toBeInTheDocument();
    expect(screen.getByText('測定から3分以上たっています')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('サーバーに接続できません');
  });

  it('shows a Japanese connection error with a retry button', async () => {
    mockFetch.mockImplementation((url: string) => url === '/api/teachers'
      ? Promise.reject(new TypeError('Failed to fetch')) : url === '/api/areas' ? json({ areas: [] }) : json(config));
    render(<App />);
    expect(await screen.findByRole('alert')).toHaveTextContent('サーバーに接続できません');
    expect(screen.getByRole('alert')).not.toHaveTextContent('Failed to fetch');
    fireEvent.click(screen.getByRole('button', { name: '今すぐ更新' }));
    await waitFor(() => expect(calls('/api/teachers')).toHaveLength(2));
  });

  it('normalizes whitespace, full-width Latin names and the 先生 suffix', async () => {
    const original = mockFetch.getMockImplementation()!;
    const romanName = { ...teachers[1], id: '4', name: 'Ａｏｋｉ　そら', kana: '' };
    mockFetch.mockImplementation((url: string, options?: RequestInit) => url === '/api/teachers'
      ? json({ teachers: [...teachers, romanName] }) : original(url, options));
    const user = userEvent.setup();
    render(<App />);
    await findRow(/星野 あかり/);
    const search = screen.getByRole('searchbox', { name: '名前・よみがな' });
    await user.type(search, '星野　あかり先生');
    expect(row(/星野 あかり/)).toBeInTheDocument();
    expect(screen.queryByRole('rowheader', { name: /青木 そら/ })).not.toBeInTheDocument();
    await user.clear(search);
    await user.type(search, 'aoki そら先生');
    expect(row(/Ａｏｋｉ/)).toBeInTheDocument();
    expect(screen.queryByRole('rowheader', { name: /星野 あかり/ })).not.toBeInTheDocument();
  });

  it('clears a name with Escape and keeps keyboard focus in the search field', async () => {
    const user = userEvent.setup();
    render(<App />);
    await findRow(/星野 あかり/);
    const search = screen.getByRole('searchbox', { name: '名前・よみがな' });
    await user.type(search, '星野');
    expect(screen.queryByRole('rowheader', { name: /青木 そら/ })).not.toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(search).toHaveValue('');
    expect(search).toHaveFocus();
    expect(row(/青木 そら/)).toBeInTheDocument();
  });

  it('resets both search conditions from the no-results state', async () => {
    const user = userEvent.setup();
    render(<App />);
    await findRow(/星野 あかり/);
    const search = screen.getByRole('searchbox', { name: '名前・よみがな' });
    const subject = screen.getByRole('combobox', { name: '教科' });
    await user.type(search, '星野');
    await user.selectOptions(subject, '数学科');
    expect(screen.getByText('条件に合う先生がいません。')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '検索条件をクリア' }));
    expect(search).toHaveValue('');
    expect(subject).toHaveValue('');
    expect(search).toHaveFocus();
    expect(screen.getAllByRole('rowheader')).toHaveLength(3);
  });

  it('shows all teachers in the display view without search controls or diagnostic details', async () => {
    const user = userEvent.setup();
    render(<App />);
    await findRow(/星野 あかり/);
    await user.type(screen.getByRole('searchbox'), '星野');
    await user.click(screen.getByRole('link', { name: '掲示用一覧' }));
    expect(screen.getByRole('heading', { name: '先生のPCエリア一覧', level: 1 })).toHaveFocus();
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: '教科' })).not.toBeInTheDocument();
    expect(screen.getAllByRole('rowheader')).toHaveLength(3);
    expect(screen.queryByText('測定データが足りません')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '掲示用一覧' })).toHaveAttribute('aria-current', 'page');
  });

  it('does not let a delayed older response restore a newer private location', async () => {
    const original = mockFetch.getMockImplementation()!;
    const recentTeacher = { ...teachers[0], updated_at: new Date().toISOString() };
    let completeOld: ((response: Response) => void) | undefined;
    let requests = 0;
    mockFetch.mockImplementation((url: string, options?: RequestInit) => {
      if (url !== '/api/teachers') return original(url, options);
      requests += 1;
      if (requests === 2) return new Promise<Response>(resolve => { completeOld = resolve; });
      return json({ teachers: [{ ...recentTeacher, ...(requests === 3 ? { status: 'private', area: null, updated_at: null } : {}) }] });
    });
    render(<App />);
    const teacherRow = await findRow(/星野 あかり/);
    expect(within(teacherRow).getByText('2階 東側')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '今すぐ更新' }));
    expect(completeOld).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: '今すぐ更新' }));
    expect(await within(teacherRow).findByText('非公開')).toBeInTheDocument();
    await act(async () => { completeOld!(await json({ teachers: [recentTeacher] })); });
    expect(within(teacherRow).getByText('非公開')).toBeInTheDocument();
    expect(within(teacherRow).queryByText('2階 東側')).not.toBeInTheDocument();
    expect(teacherRow.querySelector('time')).toBeNull();
  });

  it('pauses polling in a hidden tab and refreshes when the tab returns', async () => {
    vi.useFakeTimers();
    render(<App />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    const before = calls('/api/teachers').length;
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
    await act(async () => { await vi.advanceTimersByTimeAsync(65000); });
    expect(calls('/api/teachers')).toHaveLength(before);
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' });
    await act(async () => { document.dispatchEvent(new Event('visibilitychange')); await vi.advanceTimersByTimeAsync(0); });
    expect(calls('/api/teachers')).toHaveLength(before + 1);
  });
});

describe('development and research views', () => {
  it('asks for the token first, then registers a teacher with bearer authentication', async () => {
    const user = userEvent.setup();
    render(<App />);
    await findRow(/星野 あかり/);
    await user.click(screen.getByRole('link', { name: '管理（開発用）' }));
    expect(screen.getByLabelText('管理トークン')).toHaveValue('');
    expect(mockFetch.mock.calls.some(([url]) => String(url).includes('/admin/'))).toBe(false);
    // The live region exists before the first message, so the message is announced when it appears.
    expect(screen.getByRole('status')).toBeEmptyDOMElement();
    await user.type(screen.getByLabelText('管理トークン'), 'typed-token');
    await user.click(screen.getByRole('button', { name: '接続' }));
    await screen.findByRole('button', { name: '星野 あかりを非公開にする' });
    await user.type(screen.getByLabelText('名前'), '架空 太郎');
    await user.type(screen.getByLabelText('よみがな（任意）'), 'かくう たろう');
    await user.type(screen.getByLabelText('教科'), '英語科');
    await user.type(screen.getByLabelText('実験端末ID'), 'demo-new');
    await user.click(screen.getByRole('button', { name: '登録する' }));
    expect(await screen.findByText('架空の先生を登録しました。')).toBeInTheDocument();
    const [, options] = calls('/api/admin/teachers', 'POST')[0];
    expect(options?.headers).toMatchObject({ Authorization: 'Bearer typed-token' });
    expect(JSON.parse(options?.body as string)).toEqual({ name: '架空 太郎', kana: 'かくう たろう', subject: '英語科', device_id: 'demo-new' });
    expect(window.sessionStorage.length + window.localStorage.length).toBe(0);
  });

  it('keeps the token while switching views and forgets it on disconnect', async () => {
    const user = userEvent.setup();
    render(<App />);
    await connectAdmin(user);
    await screen.findByRole('button', { name: '星野 あかりを非公開にする' });
    await user.click(screen.getByRole('link', { name: '先生をさがす' }));
    await user.click(screen.getByRole('link', { name: '管理（開発用）' }));
    expect(await screen.findByRole('button', { name: '星野 あかりを非公開にする' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '接続を解除' }));
    expect(screen.getByLabelText('管理トークン')).toHaveValue('');
  });

  it('shows a clear message when the token is rejected', async () => {
    const original = mockFetch.getMockImplementation()!;
    mockFetch.mockImplementation((url: string, options?: RequestInit) => String(url).includes('/admin/')
      ? json({ detail: '管理トークンが正しくありません' }, 401) : original(url, options));
    const user = userEvent.setup();
    render(<App />);
    await connectAdmin(user, 'wrong-token');
    expect(await screen.findByRole('alert')).toHaveTextContent('ターミナルに表示されたトークン');
    expect(screen.getByLabelText('管理トークン')).toBeInTheDocument();
  });

  it('deletes a teacher only after confirmation', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
    const user = userEvent.setup();
    render(<App />);
    await connectAdmin(user);
    await user.click(await screen.findByRole('button', { name: '青木 そらを削除' }));
    expect(mockFetch.mock.calls.some(([, options]) => options?.method === 'DELETE')).toBe(false);
    await user.click(screen.getByRole('button', { name: '青木 そらを削除' }));
    expect(await screen.findByText('青木 そらを削除しました。')).toBeInTheDocument();
    expect(calls('/api/admin/teachers/2', 'DELETE')).toHaveLength(1);
    expect(confirm).toHaveBeenCalledTimes(2);
  });

  it('explains a completed registration followed by failed refresh without resubmitting it', async () => {
    const original = mockFetch.getMockImplementation()!;
    let saved = false;
    mockFetch.mockImplementation((url: string, options?: RequestInit) => {
      if (url === '/api/admin/teachers' && options?.method === 'POST') {
        saved = true;
        return json(teachers[0], 201);
      }
      if (saved && url === '/api/admin/teachers') return Promise.reject(new TypeError('Failed to fetch'));
      return original(url, options);
    });
    const user = userEvent.setup();
    render(<App />);
    await connectAdmin(user);
    await screen.findByRole('button', { name: '星野 あかりを非公開にする' });
    await user.type(screen.getByLabelText('名前'), '架空 太郎');
    await user.type(screen.getByLabelText('教科'), '英語科');
    await user.type(screen.getByLabelText('実験端末ID'), 'demo-new');
    await user.click(screen.getByRole('button', { name: '登録する' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('操作は完了しましたが、表示の再取得に失敗しました。');
    expect(screen.getByRole('status')).toHaveTextContent('架空の先生を登録しました。');
    expect(screen.getByLabelText('名前')).toHaveValue('');
    expect(screen.getByLabelText('実験端末ID')).toHaveValue('');
    expect(calls('/api/admin/teachers', 'POST')).toHaveLength(1);
  });

  it('renders experiment metrics and labels scores as non-probabilities', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('link', { name: '実験データ' }));
    expect(await screen.findByText('50.0%')).toBeInTheDocument();
    expect(screen.getByText('test-42')).toBeInTheDocument();
    expect(screen.getByText(/正解する確率ではありません/)).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /模擬RSSI時系列/ })).toBeInTheDocument();
    expect(screen.getByText('1/2回')).toBeInTheDocument();
  });

  it('switches between the simulation and the public dataset', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('link', { name: '実験データ' }));
    await screen.findByText('test-42');
    await user.click(screen.getByRole('radio', { name: 'UJIIndoorLoc（大学の建物・階）' }));
    expect(await screen.findByText('uji-test')).toBeInTheDocument();
    expect(screen.getByText('88.7%')).toBeInTheDocument();
    expect(screen.getByText(/CC BY 4.0/)).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: /模擬RSSI時系列/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: '実験' })).not.toBeInTheDocument();
  });

  it('keeps the research view and focuses main when using the skip link', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('link', { name: '実験データ' }));
    await screen.findByRole('heading', { name: '実験データ', level: 1 });
    expect(window.location.hash).toBe('#research');
    await user.click(screen.getByRole('link', { name: '本文へ移動' }));
    expect(screen.getByRole('main')).toHaveFocus();
    expect(window.location.hash).toBe('#research');
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
  });
});

describe('review follow-ups', () => {
  const never = (options?: RequestInit) => new Promise<Response>((_, reject) =>
    options?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))));

  it('shows a Japanese timeout message when the server stops answering', async () => {
    vi.useFakeTimers();
    const original = mockFetch.getMockImplementation()!;
    mockFetch.mockImplementation((url: string, options?: RequestInit) => url === '/api/teachers' ? never(options) : original(url, options));
    render(<App />);
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(screen.getByRole('alert')).toHaveTextContent('サーバーから応答がありません');
  });

  it('turns a body that stalls past the timeout into the same message', async () => {
    vi.useFakeTimers();
    const original = mockFetch.getMockImplementation()!;
    mockFetch.mockImplementation((url: string, options?: RequestInit) => url === '/api/teachers'
      ? Promise.resolve({ ok: true, status: 200, json: () => never(options) } as unknown as Response) : original(url, options));
    render(<App />);
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(screen.getByRole('alert')).toHaveTextContent('サーバーから応答がありません');
    expect(screen.getByRole('alert')).not.toHaveTextContent('abort');
  });

  it('describes an error without details in Japanese, and does not claim old data was shown', async () => {
    const original = mockFetch.getMockImplementation()!;
    mockFetch.mockImplementation((url: string, options?: RequestInit) => url === '/api/teachers' ? json({}, 500) : original(url, options));
    render(<App />);
    expect(await screen.findByRole('alert')).toHaveTextContent('通信に失敗しました（エラー 500）');
    expect(screen.getByRole('alert')).toHaveTextContent('先生の情報を読み込めませんでした');
    expect(screen.queryByText(/前回取得した情報/)).not.toBeInTheDocument();
    expect(screen.queryByText('登録されている先生がいません。')).not.toBeInTheDocument();
  });

  it('refreshes as soon as the network comes back', async () => {
    render(<App />);
    await findRow(/星野 あかり/);
    const before = calls('/api/teachers').length;
    act(() => { window.dispatchEvent(new Event('online')); });
    await waitFor(() => expect(calls('/api/teachers')).toHaveLength(before + 1));
  });

  it('shows readings next to names and in the admin list', async () => {
    const user = userEvent.setup();
    render(<App />);
    expect(within(await findRow(/星野 あかり/)).getByText('ほしの あかり')).toBeInTheDocument();
    await connectAdmin(user);
    expect(await screen.findByText('ほしの あかり・情報科')).toBeInTheDocument();
  });

  it('moves the research and admin links to the footer on narrow screens', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    render(<App />);
    await findRow(/星野 あかり/);
    expect(within(screen.getByRole('contentinfo')).getByRole('link', { name: '実験データ' })).toBeInTheDocument();
    expect(within(screen.getByRole('banner')).queryByRole('link', { name: '実験データ' })).not.toBeInTheDocument();
    expect(within(screen.getByRole('banner')).getByRole('link', { name: '先生をさがす' })).toBeInTheDocument();
  });

  it('names each view in the document title', async () => {
    const user = userEvent.setup();
    render(<App />);
    expect(document.title).toBe('先生をさがす | 先生のPCエリア案内 | 市川昴高校');
    await user.click(screen.getByRole('link', { name: '実験データ' }));
    expect(document.title).toBe('実験データ | 先生のPCエリア案内 | 市川昴高校');
  });

  it('shows the date, time and a fullscreen toggle on the display view', async () => {
    Object.defineProperty(document, 'fullscreenEnabled', { configurable: true, value: true });
    Object.defineProperty(document, 'fullscreenElement', { configurable: true, writable: true, value: null });
    document.documentElement.requestFullscreen = vi.fn(async () => {
      (document as { fullscreenElement: Element | null }).fullscreenElement = document.documentElement;
      document.dispatchEvent(new Event('fullscreenchange'));
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('link', { name: '掲示用一覧' }));
    expect(screen.getByText(/^\d{1,2}月\d{1,2}日\(.\)$/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '全画面表示' }));
    expect(screen.getByRole('button', { name: '全画面を終了' })).toBeInTheDocument();
    delete (document as { fullscreenEnabled?: boolean }).fullscreenEnabled;
    delete (document as { fullscreenElement?: Element | null }).fullscreenElement;
  });

  it('labels k, AP selection and a missing experiment so rows stay distinguishable', async () => {
    const original = mockFetch.getMockImplementation()!;
    const metric = { false_display_rate: .1, unknown_rate: .1, precision: .9, latency_ms: .02, accuracy: .8 };
    mockFetch.mockImplementation((url: string, options?: RequestInit) => url.startsWith('/api/research') ? json({
      ...research, experiment_id: 'not-run', metrics: [
        { ...metric, id: 'B', algorithm: 'knn', preprocessing: 'none', k: 5, selection: 'all' },
        { ...metric, id: 'N', algorithm: 'knn', preprocessing: 'none', k: 3, selection: 'all' },
        { ...metric, id: 'G', algorithm: 'knn', preprocessing: 'median', k: 5, selection: 'discriminative', selected_aps: ['AP_A', 'AP_B', 'AP_C'] },
      ],
    }) : original(url, options));
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('link', { name: '実験データ' }));
    expect(await screen.findByText('k-NN（k=3）')).toBeInTheDocument();
    expect(screen.getAllByText('k-NN（k=5）')).toHaveLength(2);
    expect(screen.getByText('中央値＋AP選択（3台）')).toBeInTheDocument();
    expect(screen.getByText('未実行')).toBeInTheDocument();
  });

  it('ignores a late response for a dataset that is no longer selected', async () => {
    const original = mockFetch.getMockImplementation()!;
    let finishUji: (() => void) | undefined;
    mockFetch.mockImplementation((url: string, options?: RequestInit) => url === '/api/research?dataset=uji'
      ? new Promise<Response>(resolve => { finishUji = () => resolve(new Response(JSON.stringify(uji), { status: 200 })); })
      : original(url, options));
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('link', { name: '実験データ' }));
    await screen.findByText('test-42');
    await user.click(screen.getByRole('radio', { name: 'UJIIndoorLoc（大学の建物・階）' }));
    // While the new dataset loads, the previous dataset's numbers are not shown under the new choice.
    expect(screen.queryByText('test-42')).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('読み込んでいます');
    await user.click(screen.getByRole('radio', { name: '模擬データ（学校6エリア）' }));
    expect(await screen.findByText('test-42')).toBeInTheDocument();
    await act(async () => { finishUji!(); });
    expect(screen.getByText('test-42')).toBeInTheDocument();
    expect(screen.queryByText('uji-test')).not.toBeInTheDocument();
  });

  it('draws a single time label for a one-point series', async () => {
    const original = mockFetch.getMockImplementation()!;
    mockFetch.mockImplementation((url: string, options?: RequestInit) => url.startsWith('/api/research')
      ? json({ ...research, series: [{ time: '2026-11-04T00:00:00Z', AP_A: -50, AP_B: -60 }] }) : original(url, options));
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('link', { name: '実験データ' }));
    const chart = await screen.findByRole('img', { name: /模擬RSSI時系列/ });
    expect(within(chart).getAllByText('00:00:00')).toHaveLength(1);
  });

  it('refuses a token with full-width characters before sending it', async () => {
    const user = userEvent.setup();
    render(<App />);
    await connectAdmin(user, 'トークン１２３');
    expect(await screen.findByRole('alert')).toHaveTextContent('管理トークンに使えない文字が含まれています');
    expect(mockFetch.mock.calls.some(([url]) => String(url).includes('/admin/'))).toBe(false);
  });

  it('keeps buttons focusable while busy and ignores a second press', async () => {
    const original = mockFetch.getMockImplementation()!;
    let finish: (() => void) | undefined;
    mockFetch.mockImplementation((url: string, options?: RequestInit) => url === '/api/admin/demo-refresh'
      ? new Promise<Response>(resolve => { finish = () => resolve(new Response('{}', { status: 200 })); })
      : original(url, options));
    const user = userEvent.setup();
    render(<App />);
    await connectAdmin(user);
    const button = await screen.findByRole('button', { name: '模擬データを更新' });
    await user.click(button);
    expect(button).toHaveAttribute('aria-disabled', 'true');
    expect(button).not.toBeDisabled();
    expect(button).toHaveFocus();
    await user.click(button);
    expect(calls('/api/admin/demo-refresh', 'POST')).toHaveLength(1);
    await act(async () => { finish!(); });
    expect(await screen.findByText('模擬測定値を更新しました。')).toBeInTheDocument();
  });

  it('does not bring back messages from a request that finishes after disconnecting', async () => {
    const original = mockFetch.getMockImplementation()!;
    let finish: (() => void) | undefined;
    mockFetch.mockImplementation((url: string, options?: RequestInit) => url === '/api/admin/demo-refresh'
      ? new Promise<Response>(resolve => { finish = () => resolve(new Response('{}', { status: 200 })); })
      : original(url, options));
    const user = userEvent.setup();
    render(<App />);
    await connectAdmin(user);
    await user.click(await screen.findByRole('button', { name: '模擬データを更新' }));
    await user.click(screen.getByRole('button', { name: '接続を解除' }));
    await act(async () => { finish!(); });
    expect(screen.getByRole('status')).toHaveTextContent('接続を解除しました。');
    expect(screen.queryByText('模擬測定値を更新しました。')).not.toBeInTheDocument();
    expect(screen.getByLabelText('管理トークン')).toBeInTheDocument();
  });

  it('returns focus to the list heading after deleting a teacher', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const user = userEvent.setup();
    render(<App />);
    await connectAdmin(user);
    await user.click(await screen.findByRole('button', { name: '青木 そらを削除' }));
    expect(await screen.findByText('青木 そらを削除しました。')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '先生の一覧' })).toHaveFocus();
  });

  it('gives RSSI inputs and mapping selects distinct names', async () => {
    const user = userEvent.setup();
    render(<App />);
    await connectAdmin(user);
    await screen.findByRole('button', { name: '星野 あかりを非公開にする' });
    expect(screen.getByRole('spinbutton', { name: 'AP_AのRSSI' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'AP_Aの対応エリア' })).toBeInTheDocument();
  });
});

describe('connection generations and independent recovery', () => {
  it('does not apply the old reload after disconnecting and connecting with a new token', async () => {
    const original = mockFetch.getMockImplementation()!;
    let refreshing = false;
    let finishOldReload: (() => void) | undefined;
    const newTeachers = [{ ...teachers[1], name: '新しい接続の先生', device_id: 'new-device', private: false }];
    mockFetch.mockImplementation((url: string, options?: RequestInit) => {
      const auth = (options?.headers as Record<string, string>)?.Authorization;
      if (url === '/api/admin/demo-refresh') { refreshing = true; return json({}); }
      if (url === '/api/admin/teachers' && options?.method === 'GET') {
        if (auth === 'Bearer new-token') return json({ teachers: newTeachers });
        if (refreshing) return new Promise<Response>(resolve => {
          finishOldReload = () => resolve(new Response(JSON.stringify({ teachers: [{ ...teachers[0], name: '古い接続の先生', private: false }] }), { status: 200 }));
        });
      }
      if (url === '/api/admin/ap-areas' && auth === 'Bearer new-token') return json({ ap_areas: { AP_A: '1F-west' } });
      return original(url, options);
    });
    const user = userEvent.setup();
    render(<App />);
    await connectAdmin(user);
    await user.click(await screen.findByRole('button', { name: '模擬データを更新' }));
    await waitFor(() => expect(finishOldReload).toBeDefined());
    await user.click(screen.getByRole('button', { name: '接続を解除' }));
    await user.type(screen.getByLabelText('管理トークン'), 'new-token');
    await user.click(screen.getByRole('button', { name: '接続' }));
    await screen.findByText('新しい接続の先生');
    await act(async () => { finishOldReload!(); });
    expect(screen.getByText('新しい接続の先生')).toBeInTheDocument();
    expect(screen.queryByText('古い接続の先生')).not.toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'AP_Aの対応エリア' })).toHaveValue('1F-west');
    expect(screen.getByRole('status')).toHaveTextContent('管理画面に接続しました。');
    expect(screen.queryByText('模擬測定値を更新しました。')).not.toBeInTheDocument();
  });

  it('does not finish connecting after the user leaves the admin screen', async () => {
    const original = mockFetch.getMockImplementation()!;
    let finishConnect: (() => void) | undefined;
    mockFetch.mockImplementation((url: string, options?: RequestInit) => url === '/api/admin/teachers'
      ? new Promise<Response>(resolve => { finishConnect = () => resolve(new Response(JSON.stringify({ teachers: [] }), { status: 200 })); })
      : original(url, options));
    const user = userEvent.setup();
    render(<App />);
    await connectAdmin(user);
    await waitFor(() => expect(finishConnect).toBeDefined());
    await user.click(screen.getByRole('link', { name: '先生をさがす' }));
    await act(async () => { finishConnect!(); });
    await user.click(screen.getByRole('link', { name: '管理（開発用）' }));
    expect(screen.getByLabelText('管理トークン')).toHaveValue('');
    expect(calls('/api/admin/teachers')).toHaveLength(1);
  });

  it('does not reload an unmounted admin view when an old mutation completes', async () => {
    const original = mockFetch.getMockImplementation()!;
    let finishChange: (() => void) | undefined;
    mockFetch.mockImplementation((url: string, options?: RequestInit) => url === '/api/admin/demo-refresh'
      ? new Promise<Response>(resolve => { finishChange = () => resolve(new Response('{}', { status: 200 })); })
      : original(url, options));
    const user = userEvent.setup();
    render(<App />);
    await connectAdmin(user);
    await user.click(await screen.findByRole('button', { name: '模擬データを更新' }));
    const before = calls('/api/admin/teachers').length;
    await user.click(screen.getByRole('link', { name: '先生をさがす' }));
    await act(async () => { finishChange!(); });
    expect(calls('/api/admin/teachers')).toHaveLength(before);
    expect(screen.getByRole('heading', { name: '先生をさがす', level: 1 })).toBeInTheDocument();
  });

  it('keeps a metadata failure visible despite teacher success and recovers it with retry', async () => {
    const original = mockFetch.getMockImplementation()!;
    let areasReady = false;
    mockFetch.mockImplementation((url: string, options?: RequestInit) => url === '/api/areas' && !areasReady
      ? json({ detail: '一時的に利用できません' }, 503) : original(url, options));
    const user = userEvent.setup();
    render(<App />);
    await findRow(/星野 あかり/);
    expect(await screen.findByRole('alert')).toHaveTextContent('エリア名を読み込めませんでした');
    await connectAdmin(user);
    expect(screen.getByRole('combobox', { name: '使う方式' })).toHaveValue('knn');
    expect(within(screen.getByRole('combobox', { name: '使う方式' })).getAllByRole('option')).toHaveLength(2);
    areasReady = true;
    await user.click(screen.getByRole('button', { name: '設定を再読み込み' }));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(within(screen.getByRole('combobox', { name: 'AP_Aの対応エリア' })).getByRole('option', { name: '2階 東側' })).toBeInTheDocument();
    expect(calls('/api/areas')).toHaveLength(2);
  });

  it('recovers failed configuration on network return without discarding usable area names', async () => {
    const original = mockFetch.getMockImplementation()!;
    let configReady = false;
    mockFetch.mockImplementation((url: string, options?: RequestInit) => {
      if (url === '/api/config' && !configReady) return json({ detail: '設定を取得できません' }, 503);
      if (url === '/api/teachers') return json({ teachers: [{ ...teachers[0], updated_at: new Date().toISOString() }] });
      return original(url, options);
    });
    render(<App />);
    expect(await screen.findByText('2階 東側')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('推定方式の設定を読み込めませんでした');
    configReady = true;
    act(() => { window.dispatchEvent(new Event('online')); });
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(calls('/api/config')).toHaveLength(2);
    expect(screen.getByText('2階 東側')).toBeInTheDocument();
  });

  it('does not restore an old GET configuration after an algorithm was saved', async () => {
    const original = mockFetch.getMockImplementation()!;
    let configReads = 0;
    let saved = false;
    let finishOldConfig: (() => void) | undefined;
    let finishSavedReload: (() => void) | undefined;
    mockFetch.mockImplementation((url: string, options?: RequestInit) => {
      if (url === '/api/config') {
        configReads += 1;
        if (configReads === 2) return new Promise<Response>(resolve => {
          finishOldConfig = () => resolve(new Response(JSON.stringify(config), { status: 200 }));
        });
        return json({ ...config, algorithm: saved ? 'kalman' : 'knn' });
      }
      if (url === '/api/admin/config' && options?.method === 'PUT') { saved = true; return json({ ...config, algorithm: 'kalman' }); }
      if (url === '/api/admin/teachers' && saved) return new Promise<Response>(resolve => {
        finishSavedReload = () => resolve(new Response(JSON.stringify({ teachers: [] }), { status: 200 }));
      });
      return original(url, options);
    });
    const user = userEvent.setup();
    render(<App />);
    await connectAdmin(user);
    await screen.findByRole('button', { name: '星野 あかりを非公開にする' });
    act(() => { window.dispatchEvent(new Event('online')); });
    await waitFor(() => expect(finishOldConfig).toBeDefined());
    await user.selectOptions(screen.getByRole('combobox', { name: '使う方式' }), 'kalman');
    await user.click(screen.getByRole('button', { name: 'この方式にする' }));
    await waitFor(() => expect(finishSavedReload).toBeDefined());
    await act(async () => { finishOldConfig!(); });
    expect(screen.getByRole('combobox', { name: '使う方式' })).toHaveValue('kalman');
    await act(async () => { finishSavedReload!(); });
    expect(await screen.findByText('推定方式を変更しました。')).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: '使う方式' })).toHaveValue('kalman');
  });

  it('keeps registration inputs read-only until the saved response clears them', async () => {
    const original = mockFetch.getMockImplementation()!;
    let finishSave: (() => void) | undefined;
    mockFetch.mockImplementation((url: string, options?: RequestInit) => url === '/api/admin/teachers' && options?.method === 'POST'
      ? new Promise<Response>(resolve => { finishSave = () => resolve(new Response('{}', { status: 201 })); })
      : original(url, options));
    const user = userEvent.setup();
    render(<App />);
    await connectAdmin(user);
    await screen.findByRole('button', { name: '星野 あかりを非公開にする' });
    await user.type(screen.getByLabelText('名前'), '架空 太郎');
    await user.type(screen.getByLabelText('教科'), '英語科');
    await user.type(screen.getByLabelText('実験端末ID'), 'demo-new');
    await user.click(screen.getByRole('button', { name: '登録する' }));
    const name = screen.getByLabelText('名前');
    expect(name).toHaveAttribute('readonly');
    expect(screen.getByLabelText('よみがな（任意）')).toHaveAttribute('readonly');
    expect(screen.getByLabelText('教科')).toHaveAttribute('readonly');
    expect(screen.getByLabelText('実験端末ID')).toHaveAttribute('readonly');
    await user.type(name, '次の入力');
    expect(name).toHaveValue('架空 太郎');
    await act(async () => { finishSave!(); });
    expect(await screen.findByText('架空の先生を登録しました。')).toBeInTheDocument();
    expect(name).toHaveValue('');
    expect(name).not.toHaveAttribute('readonly');
  });

  it('preserves an unsaved AP mapping while another operation reloads the lists', async () => {
    const original = mockFetch.getMockImplementation()!;
    let serverArea = '2F-east';
    mockFetch.mockImplementation((url: string, options?: RequestInit) => {
      if (url === '/api/admin/demo-refresh') return json({});
      if (url === '/api/admin/ap-areas') {
        if (options?.method === 'PUT') serverArea = JSON.parse(options.body as string).ap_areas.AP_A;
        return json({ ap_areas: { AP_A: serverArea } });
      }
      return original(url, options);
    });
    const user = userEvent.setup();
    render(<App />);
    await connectAdmin(user);
    const mapping = await screen.findByRole('combobox', { name: 'AP_Aの対応エリア' });
    await user.selectOptions(mapping, '1F-west');
    await user.click(screen.getByRole('button', { name: '模擬データを更新' }));
    expect(await screen.findByText('模擬測定値を更新しました。')).toBeInTheDocument();
    expect(mapping).toHaveValue('1F-west');
    await user.click(screen.getByRole('button', { name: '対応表を保存' }));
    expect(await screen.findByText('APとエリアの対応を保存しました。')).toBeInTheDocument();
    expect(JSON.parse(calls('/api/admin/ap-areas', 'PUT')[0][1]?.body as string)).toEqual({ ap_areas: { AP_A: '1F-west' } });
    expect(mapping).toHaveValue('1F-west');
  });

  it('retries a temporarily unreadable research report without reloading the app', async () => {
    const original = mockFetch.getMockImplementation()!;
    let reportReady = false;
    mockFetch.mockImplementation((url: string, options?: RequestInit) => url.startsWith('/api/research') && !reportReady
      ? json({ detail: '実験結果を読み込めません。再実行後にお試しください。' }, 503) : original(url, options));
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('link', { name: '実験データ' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('実験結果を読み込めません');
    reportReady = true;
    await user.click(screen.getByRole('button', { name: '再試行' }));
    expect(await screen.findByText('test-42')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(calls('/api/research?dataset=simulation')).toHaveLength(2);
  });
});

describe('saved changes and student reload errors', () => {
  it('explains that a change is saved when only the student directory reload fails', async () => {
    const original = mockFetch.getMockImplementation()!;
    let saved = false;
    mockFetch.mockImplementation((url: string, options?: RequestInit) => {
      if (url === '/api/admin/demo-refresh') { saved = true; return json({}); }
      if (saved && url === '/api/teachers') return json({ detail: '生徒向け一覧を取得できません' }, 503);
      return original(url, options);
    });
    const user = userEvent.setup();
    render(<App />);
    await connectAdmin(user);
    await user.click(await screen.findByRole('button', { name: '模擬データを更新' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('操作は完了しましたが、表示の再取得に失敗しました。');
    expect(screen.getByRole('alert')).toHaveTextContent('生徒向け一覧を取得できません');
    expect(screen.getByRole('status')).toHaveTextContent('模擬測定値を更新しました。');
    expect(calls('/api/admin/demo-refresh', 'POST')).toHaveLength(1);
    await user.click(screen.getByRole('link', { name: '先生をさがす' }));
    expect(screen.getByRole('alert')).toHaveTextContent('情報を更新できませんでした');
  });
});
