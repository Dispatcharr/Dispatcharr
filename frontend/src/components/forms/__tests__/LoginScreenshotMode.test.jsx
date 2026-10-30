import { MantineProvider } from '@mantine/core';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import LoginForm from '../LoginForm';
import { SensitiveTextInput } from '../../SensitiveFields.jsx';
import useAuthStore from '../../../store/auth';
import useSettingsStore from '../../../store/settings';
import useScreenshotMode from '../../../store/useScreenshotMode.js';

vi.mock('../../../store/auth', async () => {
  const { create } = await import('zustand');
  return { default: create(() => ({ isAuthenticated: false })) };
});
vi.mock('../../../store/settings', () => ({ default: vi.fn() }));
vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

const renderLogin = () =>
  render(
    <MantineProvider env="test">
      <MemoryRouter initialEntries={['/login']}>
        <Routes>
          <Route path="/login" element={<LoginForm />} />
          <Route
            path="/channels"
            element={
              <SensitiveTextInput
                label="Provider URL"
                value="https://provider.invalid/playlist"
                readOnly
              />
            }
          />
        </Routes>
      </MemoryRouter>
    </MantineProvider>
  );

describe('login screenshot-mode boundary', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    localStorage.clear();
    useScreenshotMode.setState({ enabled: false });
    useAuthStore.setState({
      isAuthenticated: false,
      login: vi.fn(async () => {
        useAuthStore.setState({ isAuthenticated: true });
      }),
      logout: vi.fn(),
      initData: vi.fn().mockResolvedValue(undefined),
    });
    const settings = { fetchVersion: vi.fn(), version: {} };
    vi.mocked(useSettingsStore).mockImplementation((select) =>
      select(settings)
    );
  });

  it.each([false, true])(
    'keeps login fields normal and preserves screenshot mode after signing in (enabled=%s)',
    async (enabled) => {
      useScreenshotMode.setState({ enabled });
      const savedPreference = sessionStorage.getItem(
        'dispatcharr-screenshot-mode'
      );
      renderLogin();

      const username = screen.getByLabelText(/^Username/);
      const password = screen.getByLabelText('Password');
      expect(username.type).toBe('text');
      expect(password).toHaveAttribute('type', 'password');
      expect(username).not.toHaveAttribute('autocomplete', 'off');
      expect(password).not.toHaveAttribute('autocomplete', 'off');
      fireEvent.change(username, { target: { value: 'example-user' } });
      fireEvent.change(password, { target: { value: 'example-password' } });
      fireEvent.click(
        screen.getByRole('button', { name: 'Login', exact: true })
      );

      const providerUrl = await screen.findByLabelText('Provider URL');
      expect(useAuthStore.getState().login).toHaveBeenCalledWith({
        username: 'example-user',
        password: 'example-password',
      });
      await waitFor(() =>
        expect(useAuthStore.getState().initData).toHaveBeenCalledOnce()
      );
      expect(providerUrl.type).toBe(enabled ? 'password' : 'text');
      expect(useScreenshotMode.getState().enabled).toBe(enabled);
      expect(sessionStorage.getItem('dispatcharr-screenshot-mode')).toBe(
        savedPreference
      );
    }
  );

  it('shows the remembered username without changing the saved screenshot preference', () => {
    useScreenshotMode.setState({ enabled: true });
    localStorage.setItem('dispatcharr_remembered_username', 'remembered-user');
    renderLogin();

    expect(screen.getByLabelText(/^Username/)).toHaveValue('remembered-user');
    expect(screen.getByLabelText(/^Username/).type).toBe('text');
    expect(useScreenshotMode.getState().enabled).toBe(true);
    expect(
      JSON.parse(sessionStorage.getItem('dispatcharr-screenshot-mode')).state
    ).toEqual({ enabled: true });
  });
});
