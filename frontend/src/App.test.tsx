import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import App from './App';
const teachers = [
  { id: '1', name: '星野 あかり', subject: '情報科', status: 'located', area: '2F-east', updated_at: '2026-11-04T09:00:00Z', reason: null },
  { id: '2', name: '青木 そら', subject: '数学科', status: 'unknown', area: null, updated_at: null, reason: 'insufficient_data' },
  { id: '3', name: '月野 ひかり', subject: '国語科', status: 'private', area: 'private-secret-room', updated_at: '2026-11-04T01:23:45Z', reason: null, device_id: 'private-device-secret' },
];
const config = { algorithm: 'knn', algorithms: [{ id: 'knn', label: 'k-NN' }, { id: 'kalman', label: 'テスト方式' }], demo: true };
function json(data: unknown, status = 200) { return Promise.resolve(new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })); }
let mockFetch: ReturnType<typeof vi.fn<(url: string, options?: RequestInit) => Promise<Response>>>;
beforeEach(() => {
  window.location.hash = '';
  mockFetch = vi.fn((url: string, options?: RequestInit) => {
    if (url === '/api/teachers') return json({ teachers, demo: true });
    if (url === '/api/areas') return json({ areas: [{ id: '2F-east', label: '2階 東側' }] });
    if (url === '/api/config') return json(config);
    if (url === '/api/admin/teachers' && options?.method === 'POST') return json(teachers[0]);
    if (url === '/api/admin/teachers') return json({ teachers: teachers.map(t => ({ ...t, device_id: `demo-${t.id}`, private: t.status === 'private' })) });
    if (url === '/api/admin/ap-areas') return json({ ap_areas: { AP_A: '2F-east' } });
    if (url === '/api/research') return json({ source: 'simulation', experiment_id: 'test-42', series: [{ time: '2026-11-04T00:00:00Z', AP_A: -50 }], candidates: [{ area: '2F-east', score: .8 }], metrics: [{ id: 'A', algorithm: 'strongest_ap', preprocessing: 'none', accuracy: .5, false_display_rate: .2, unknown_rate: .3, precision: .714, latency_ms: .01 }], note: '学校の実環境での性能は未確認です。' });
    return json({ detail: 'not found' }, 404);
  });
  vi.stubGlobal('fetch', mockFetch);
});
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
describe('student directory', () => {
  it('searches by name and filters by subject', async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('heading', { name: /星野 あかり/ });
    await user.type(screen.getByRole('searchbox', { name: '先生の名前で検索' }), '星野');
    expect(screen.queryByRole('heading', { name: /青木 そら/ })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /星野 あかり/ })).toBeInTheDocument();
    await user.clear(screen.getByRole('searchbox'));
    await user.selectOptions(screen.getByRole('combobox', { name: '教科で絞り込み' }), '数学科');
    expect(screen.getByRole('heading', { name: /青木 そら/ })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /星野 あかり/ })).not.toBeInTheDocument();
  });
  it('hides private area, timestamp and device identifiers and never requests admin data', async () => {
    render(<App />);
    const heading = await screen.findByRole('heading', { name: /月野 ひかり/ });
    const card = heading.closest('tr')!;
    expect(within(card).getByText('所在情報は公開されていません')).toBeInTheDocument();
    expect(card.querySelector('time')).toBeNull();
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
    const heading = await screen.findByRole('heading', { name: /星野 あかり/ });
    const card = heading.closest('tr')!;
    expect(within(card).getByText('位置不明')).toBeInTheDocument();
    expect(within(card).queryByText('2階 東側')).not.toBeInTheDocument();
    expect(within(card).getByText('測定情報が古くなっています')).toBeInTheDocument();
  });
  it('expires a cached area during repeated network failures', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-11-04T09:00:00Z'));
    const original = mockFetch.getMockImplementation()!;
    let requests = 0;
    mockFetch.mockImplementation((url: string, options?: RequestInit) => {
      if (url !== '/api/teachers') return original(url, options);
      requests += 1;
      return requests === 1 ? json({ teachers: [teachers[0]] }) : Promise.reject(new Error('offline'));
    });
    render(<App />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(screen.getByText('2階 東側')).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(195000); });
    expect(screen.queryByText('2階 東側')).not.toBeInTheDocument();
    expect(screen.getByText('測定情報が古くなっています')).toBeInTheDocument();
  });
  it('shows connection failure with a retry button', async () => {
    mockFetch.mockImplementation((url: string) => url === '/api/teachers' ? Promise.reject(new Error('バックエンドに接続できません')) : url === '/api/areas' ? json({ areas: [] }) : json(config));
    render(<App />);
    expect(await screen.findByRole('alert')).toHaveTextContent('バックエンドに接続できません');
    fireEvent.click(screen.getByRole('button', { name: '最新の情報に更新' }));
    await waitFor(() => expect(mockFetch.mock.calls.filter(([url]) => url === '/api/teachers').length).toBe(2));
  });
  it('normalizes whitespace, full-width Latin names and the 先生 suffix', async () => {
    const original = mockFetch.getMockImplementation()!;
    const romanName = { ...teachers[1], id: '4', name: 'Ａｏｋｉ　そら' };
    mockFetch.mockImplementation((url: string, options?: RequestInit) => url === '/api/teachers'
      ? json({ teachers: [...teachers, romanName] }) : original(url, options));
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('heading', { name: /星野 あかり/ });
    const search = screen.getByRole('searchbox', { name: '先生の名前で検索' });
    await user.type(search, '星野　あかり先生');
    expect(screen.getByRole('heading', { name: /星野 あかり/ })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /青木 そら/ })).not.toBeInTheDocument();
    await user.clear(search);
    await user.type(search, 'aoki そら先生');
    expect(screen.getByRole('heading', { name: /Ａｏｋｉ/ })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /星野 あかり/ })).not.toBeInTheDocument();
  });
  it('clears a name with Escape and keeps keyboard focus in the search field', async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('heading', { name: /星野 あかり/ });
    const search = screen.getByRole('searchbox', { name: '先生の名前で検索' });
    await user.type(search, '星野');
    expect(screen.queryByRole('heading', { name: /青木 そら/ })).not.toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(search).toHaveValue('');
    expect(search).toHaveFocus();
    expect(screen.getByRole('heading', { name: /青木 そら/ })).toBeInTheDocument();
  });
  it('resets both search conditions from the no-results state', async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('heading', { name: /星野 あかり/ });
    const search = screen.getByRole('searchbox', { name: '先生の名前で検索' });
    const subject = screen.getByRole('combobox', { name: '教科で絞り込み' });
    await user.type(search, '星野');
    await user.selectOptions(subject, '数学科');
    expect(screen.getByRole('heading', { name: '条件に合う先生が見つかりません' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '検索条件をクリア' }));
    expect(search).toHaveValue('');
    expect(subject).toHaveValue('');
    expect(search).toHaveFocus();
    expect(screen.getByRole('heading', { name: /星野 あかり/ })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /青木 そら/ })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /月野 ひかり/ })).toBeInTheDocument();
  });
  it('shows all teachers in display mode independently of the preceding search', async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('heading', { name: /星野 あかり/ });
    await user.type(screen.getByRole('searchbox'), '星野');
    await user.selectOptions(screen.getByRole('combobox', { name: '教科で絞り込み' }), '情報科');
    expect(screen.queryByRole('heading', { name: /青木 そら/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '一覧ディスプレイ' }));
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: '教科で絞り込み' })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /星野 あかり/ })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /青木 そら/ })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /月野 ひかり/ })).toBeInTheDocument();
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
    const heading = await screen.findByRole('heading', { name: /星野 あかり/ });
    const row = heading.closest('tr')!;
    expect(within(row).getByText('2階 東側')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '最新の情報に更新' }));
    expect(completeOld).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: '最新の情報に更新' }));
    expect(await within(row).findByText('非公開')).toBeInTheDocument();
    await act(async () => { completeOld!(await json({ teachers: [recentTeacher] })); });
    expect(within(row).getByText('非公開')).toBeInTheDocument();
    expect(within(row).queryByText('2階 東側')).not.toBeInTheDocument();
    expect(row.querySelector('time')).toBeNull();
  });
});
describe('development and research views', () => {
  it('registers a fictitious teacher with bearer authentication', async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('heading', { name: /星野 あかり/ });
    await user.click(screen.getByRole('button', { name: '開発用管理' }));
    await screen.findByRole('button', { name: '星野 あかりを非公開にする' });
    await user.type(screen.getByLabelText('表示名'), '架空 太郎');
    await user.type(screen.getByLabelText('教科', { selector: 'input' }), '英語科');
    await user.type(screen.getByLabelText('実験端末ID'), 'demo-new');
    await user.click(screen.getByRole('button', { name: /先生を登録する/ }));
    expect(await screen.findByText('架空の先生を登録しました。')).toBeInTheDocument();
    const call = mockFetch.mock.calls.find(([url, options]) => url === '/api/admin/teachers' && options?.method === 'POST');
    expect(call).toBeDefined();
    expect(call?.[1]?.headers).toMatchObject({ Authorization: 'Bearer dev-demo-token' });
    expect(JSON.parse(call?.[1]?.body as string)).toEqual({ name: '架空 太郎', subject: '英語科', device_id: 'demo-new' });
  });
  it('shows server authentication errors in admin', async () => {
    const original = mockFetch.getMockImplementation()!;
    mockFetch.mockImplementation((url: string, options?: RequestInit) => String(url).includes('/admin/') ? json({ detail: '開発用トークンが無効です' }, 401) : original(url, options));
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: '開発用管理' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('開発用トークンが無効です');
  });
  it('renders experiment metrics and labels scores as non-probabilities', async () => {
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: '実験データ' }));
    expect(await screen.findByText('50.0%')).toBeInTheDocument();
    expect(screen.getByText('test-42')).toBeInTheDocument();
    expect(screen.getByText(/正解する確率ではありません/)).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /模擬RSSI時系列/ })).toBeInTheDocument();
  });
  it('keeps the research view and focuses main when using the skip link', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('button', { name: '実験データ' }));
    await screen.findByRole('heading', { name: '実験データ', level: 1 });
    expect(window.location.hash).toBe('#research');
    await user.click(screen.getByRole('link', { name: '本文へ移動' }));
    expect(screen.getByRole('main')).toHaveFocus();
    expect(window.location.hash).toBe('#research');
    expect(screen.getByRole('heading', { name: '実験データ', level: 1 })).toBeInTheDocument();
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
  });
  it('explains a completed registration followed by failed refresh without resubmitting it', async () => {
    const original = mockFetch.getMockImplementation()!;
    let saved = false;
    mockFetch.mockImplementation((url: string, options?: RequestInit) => {
      if (url === '/api/admin/teachers' && options?.method === 'POST') {
        saved = true;
        return json(teachers[0], 201);
      }
      if (saved && url === '/api/admin/teachers') return Promise.reject(new Error('管理一覧の接続が切れました'));
      return original(url, options);
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('button', { name: '開発用管理' }));
    await screen.findByRole('button', { name: '星野 あかりを非公開にする' });
    await user.type(screen.getByLabelText('表示名'), '架空 太郎');
    await user.type(screen.getByLabelText('教科', { selector: 'input' }), '英語科');
    await user.type(screen.getByLabelText('実験端末ID'), 'demo-new');
    await user.click(screen.getByRole('button', { name: '先生を登録する' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('操作は完了しましたが、表示の再取得に失敗しました。');
    expect(screen.getByRole('status')).toHaveTextContent('架空の先生を登録しました。');
    expect(screen.getByLabelText('表示名')).toHaveValue('');
    expect(screen.getByLabelText('実験端末ID')).toHaveValue('');
    await user.click(screen.getByRole('button', { name: '接続を確認' }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('管理一覧の接続が切れました'));
    expect(mockFetch.mock.calls.filter(([url, options]) => url === '/api/admin/teachers' && options?.method === 'POST')).toHaveLength(1);
  });
});
