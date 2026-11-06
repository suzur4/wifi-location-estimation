// @vitest-environment-options {"url":"http://192.168.1.20:8080/"}
import { render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import App from './App';
import { adminApi } from './api';

afterEach(() => vi.unstubAllGlobals());

it.each(['admin', 'research'])('opens the directory for a LAN link to #%s', async hash => {
  window.location.hash = hash;
  const get = vi.fn<(path: string) => Promise<Response>>(async () => Response.json({ teachers: [], areas: [] }));
  vi.stubGlobal('fetch', get);
  render(<App />);
  await screen.findByText('登録されている先生がいません。');
  expect(screen.getByRole('heading', { name: '先生をさがす' })).toBeVisible();
  expect(screen.queryByRole('navigation', { name: '研究・開発用メニュー' })).toBeNull();
  expect(screen.queryByLabelText('管理トークン')).toBeNull();
  expect(get.mock.calls.map(call => call[0])).toEqual(['/api/teachers', '/api/areas', '/api/config']);
});

it('refuses to send an admin token over LAN HTTP', async () => {
  const get = vi.fn();
  vi.stubGlobal('fetch', get);
  await expect(adminApi('/teachers', 'test-token')).rejects.toThrow('SSHトンネル');
  expect(get).not.toHaveBeenCalled();
});
