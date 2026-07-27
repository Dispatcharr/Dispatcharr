import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import LogFileViewPage from '../LogFileView';
import API from '../../api';

vi.mock('../../api', () => ({
  default: {
    getLogFile: vi.fn(),
    downloadLogFile: vi.fn(),
  },
}));

vi.mock('@mantine/notifications', () => ({
  notifications: { show: vi.fn() },
}));

vi.mock('@mantine/core', () => ({
  Anchor: ({ children, to }) => <a href={to || '#'}>{children}</a>,
  Box: ({ children }) => <div>{children}</div>,
  Button: ({ children, onClick }) => (
    <button onClick={onClick}>{children}</button>
  ),
  Group: ({ children }) => <div>{children}</div>,
  Loader: () => <div data-testid="loader" />,
  Paper: ({ children }) => <div>{children}</div>,
  Switch: ({ label, checked, onChange }) => (
    <label>
      <input type="checkbox" checked={checked} onChange={onChange} />
      {label}
    </label>
  ),
  Text: ({ children }) => <span>{children}</span>,
  Title: ({ children }) => <h4>{children}</h4>,
}));

const renderPage = (name = 'dispatcharr.log') =>
  render(
    <MemoryRouter initialEntries={[`/logs/${name}`]}>
      <Routes>
        <Route path="/logs/:name" element={<LogFileViewPage />} />
      </Routes>
    </MemoryRouter>
  );

describe('LogFileViewPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    API.getLogFile.mockResolvedValue({
      content: 'Info|DiskScanService|Scanning disk\n',
      truncated: false,
    });
  });

  it('fetches and renders the raw log content', async () => {
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByText(/DiskScanService\|Scanning disk/)
      ).toBeInTheDocument();
    });
    expect(API.getLogFile).toHaveBeenCalledWith('dispatcharr.log', {
      silent: false,
    });
    expect(screen.getByText('dispatcharr.log')).toBeInTheDocument();
  });

  it('shows the truncation notice for large files', async () => {
    API.getLogFile.mockResolvedValue({ content: 'tail', truncated: true });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/showing the last 5 MB/i)).toBeInTheDocument();
    });
  });

  it('downloads the file from the toolbar', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('Download')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('Download'));
    expect(API.downloadLogFile).toHaveBeenCalledWith('dispatcharr.log');
  });

  it('re-fetches when Refresh is clicked', async () => {
    renderPage();
    await waitFor(() => expect(API.getLogFile).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByText('Refresh'));
    await waitFor(() => expect(API.getLogFile).toHaveBeenCalledTimes(2));
  });

  it('renders the colour key', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('login/auth')).toBeInTheDocument();
    });
    ['text', 'error', 'warn', 'login/auth', 'plugin'].forEach(
      (label) => expect(screen.getByText(label)).toBeInTheDocument()
    );
  });

  it('colours lines by category', async () => {
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-07-15 10:00:00,000 INFO core.tasks routine tick',
        '2026-07-15 10:00:01,000 ERROR apps.epg boom failure',
        '2026-07-15 10:00:02,000 WARNING core.utils cache miss',
        '2026-07-15 10:00:03,000 INFO plugins.iptv_checker sweep done',
        '2026-07-15 10:00:04,000 INFO apps.proxy.ts_proxy client connected',
        '2026-07-15 10:00:05,000 WARNING django.request Unauthorized: /api/x/',
        '2026-07-15 10:00:06,000 INFO apps.plugins.tasks Refreshed plugin repo hub',
        '2026-07-15 10:00:07,000 INFO apps.accounts.api_views Login success: user=demo ip=192.0.2.7',
        '2026-07-15 10:00:08,000 INFO apps.m3u.tasks account credentials rotated for auth refresh',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/boom failure/)).toBeInTheDocument();
    });
    expect(screen.getByText(/boom failure/)).toHaveStyle({ color: '#ff6b6b' });
    expect(screen.getByText(/cache miss/)).toHaveStyle({ color: '#ffd43b' });
    expect(screen.getByText(/sweep done/)).toHaveStyle({ color: '#74c0fc' });
    // Auth events are green now (login lines + 401/403), outranking warn.
    expect(screen.getByText(/Unauthorized/)).toHaveStyle({ color: '#51cf66' });
    expect(screen.getByText(/Login success/)).toHaveStyle({ color: '#51cf66' });
    expect(screen.getByText(/routine tick/)).not.toHaveStyle({
      color: '#ff6b6b',
    });
    // System infrastructure mentioning "plugin" is not a plugin event.
    expect(screen.getByText(/Refreshed plugin repo hub/)).not.toHaveStyle({
      color: '#74c0fc',
    });
    // The dropped client/player rule: a proxy/stream line is now plain text.
    expect(screen.getByText(/client connected/)).not.toHaveStyle({
      color: '#51cf66',
    });
    // ...and a line merely mentioning auth/credential words is not auth.
    expect(screen.getByText(/credentials rotated/)).not.toHaveStyle({
      color: '#51cf66',
    });
  });

  it('continuation lines inherit the record colour', async () => {
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-07-15 10:00:07,000 CRITICAL celery.backends.asynchronous ',
        'Retry limit exceeded while reconnecting to the result store',
        'The Celery application must be restarted',
        '2026-07-15 10:00:08,000 INFO core.tasks back to normal',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/Retry limit exceeded/)).toBeInTheDocument();
    });
    // CRITICAL header and both continuation lines render in one red span.
    expect(screen.getByText(/Retry limit exceeded/)).toHaveStyle({
      color: '#ff6b6b',
    });
    expect(screen.getByText(/Retry limit exceeded/).textContent).toContain(
      'must be restarted'
    );
    expect(screen.getByText(/back to normal/)).not.toHaveStyle({
      color: '#ff6b6b',
    });
  });

  it('colours error levels ahead of category keywords', async () => {
    API.getLogFile.mockResolvedValue({
      content: '2026-07-15 10:00:06,000 ERROR plugins.iptv_checker sweep died',
      truncated: false,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/sweep died/)).toBeInTheDocument();
    });
    expect(screen.getByText(/sweep died/)).toHaveStyle({ color: '#ff6b6b' });
  });

  it('does not redden an INFO line whose message body mentions ERROR', async () => {
    // Only the level field reddens: "state to ERROR in Redis" is message text on an INFO line.
    API.getLogFile.mockResolvedValue({
      content:
        '2026-07-19 22:52:20,931 INFO live_proxy.manager Updated channel abc state to ERROR in Redis after stream failure',
      truncated: false,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/state to ERROR in Redis/)).toBeInTheDocument();
    });
    expect(screen.getByText(/state to ERROR in Redis/)).not.toHaveStyle({
      color: '#ff6b6b',
    });
  });

  it('colours WebSocket JWT auth rejections green', async () => {
    API.getLogFile.mockResolvedValue({
      content:
        '2026-07-20 16:45:17,317 WARNING dispatcharr.jwt_ws_auth Invalid token: given token not valid for any token type',
      truncated: false,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/Invalid token/)).toBeInTheDocument();
    });
    expect(screen.getByText(/Invalid token/)).toHaveStyle({ color: '#51cf66' });
  });

  it('drops routine token-refresh/notification 401 polling to warn, keeps other 401s green', async () => {
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-07-20 00:50:00,000 WARNING django.request Unauthorized: /api/accounts/token/refresh/',
        '2026-07-20 00:50:01,000 WARNING django.request Unauthorized: /api/core/notifications/',
        '2026-07-20 00:50:02,000 WARNING django.request Unauthorized: /api/channels/1/',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/token\/refresh/)).toBeInTheDocument();
    });
    // Benign polling 401s fall through to warn (yellow), not green.
    expect(screen.getByText(/token\/refresh/)).toHaveStyle({ color: '#ffd43b' });
    expect(screen.getByText(/notifications/)).toHaveStyle({ color: '#ffd43b' });
    // A non-routine 401 stays green — a real unauthorized access is notable.
    expect(screen.getByText(/channels\/1/)).toHaveStyle({ color: '#51cf66' });
  });

  it('shows a load error with Retry and recovers when Retry succeeds', async () => {
    // getLogFile resolves undefined on failure (see api.js catch path).
    API.getLogFile.mockResolvedValue(undefined);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/Failed to load/)).toBeInTheDocument();
    });
    expect(screen.getByText('Retry')).toBeInTheDocument();
    // The empty-file placeholder must not show while in the error state.
    expect(screen.queryByText('(empty)')).not.toBeInTheDocument();

    API.getLogFile.mockResolvedValue({
      content: 'recovered log line\n',
      truncated: false,
    });
    fireEvent.click(screen.getByText('Retry'));
    await waitFor(() => {
      expect(screen.getByText(/recovered log line/)).toBeInTheDocument();
    });
    expect(screen.queryByText(/Failed to load/)).not.toBeInTheDocument();
  });

  it('renders a near-ceiling log (~50k lines / ~5MB, many colour switches) without hanging', async () => {
    // Deterministic synthetic log near the 5 MB truncation ceiling, interleaving every category to exercise colorizeLines's worst case (frequent colour switches).
    const LEVELS = [
      { tag: 'INFO', logger: 'core.tasks', msg: 'routine tick, nothing to report this cycle' },
      { tag: 'WARNING', logger: 'core.utils', msg: 'cache miss while resolving stream metadata lookup' },
      { tag: 'ERROR', logger: 'apps.epg', msg: 'boom failure refreshing programme guide data source' },
      { tag: 'INFO', logger: 'apps.accounts.api_views', msg: 'Login success: user=demo ip=192.0.2.7 session=abcdef' },
      { tag: 'INFO', logger: 'plugins.iptv_checker', msg: 'sweep tick probing configured channel groups' },
    ];
    const RECORD_COUNT = 45000;
    const lines = [];
    for (let i = 0; i < RECORD_COUNT; i += 1) {
      const level = LEVELS[i % LEVELS.length];
      const hh = String(Math.floor(i / 3600) % 24).padStart(2, '0');
      const mm = String(Math.floor(i / 60) % 60).padStart(2, '0');
      const ss = String(i % 60).padStart(2, '0');
      lines.push(
        `2026-07-15 ${hh}:${mm}:${ss},000 ${level.tag} ${level.logger} ${level.msg} record-${i}`
      );
      // Every 6th record gets a continuation line, exercising colorizeLines's continuation-inherits-colour path too.
      if (i % 6 === 0) {
        lines.push(
          `    caused by: nested detail for record ${i} with additional padding text to widen the payload`
        );
      }
    }
    lines.push(
      '2026-07-15 23:59:59,000 INFO core.tasks END-OF-SYNTHETIC-LOG-MARKER'
    );
    const content = lines.join('\n');
    // Sanity-check the synthetic payload is genuinely close to the 5 MB
    // ceiling the app truncates at, not just "big enough to be plausible".
    expect(content.length).toBeGreaterThan(4 * 1024 * 1024);

    API.getLogFile.mockResolvedValue({ content, truncated: true });

    const start = performance.now();
    renderPage();
    await waitFor(
      () => {
        expect(
          screen.getByText(/END-OF-SYNTHETIC-LOG-MARKER/)
        ).toBeInTheDocument();
      },
      { timeout: 15000 }
    );
    const elapsed = performance.now() - start;

    // Generous ceiling — this is a smoke/perf-ceiling guard proving the
    // native <pre> render doesn't hang at max size, not a strict benchmark.
    expect(elapsed).toBeLessThan(15000);
    expect(screen.queryByTestId('loader')).not.toBeInTheDocument();
    expect(screen.queryByText('(empty)')).not.toBeInTheDocument();
    // F3: only the tail renders — the cap notice shows and the first record is dropped from the DOM.
    expect(screen.getByText(/Showing the last [\d,]+ lines/)).toBeInTheDocument();
    expect(screen.queryByText(/record-0\b/)).not.toBeInTheDocument();
  }, 20000);

  it('does not poll while the tab is hidden', async () => {
    vi.useFakeTimers();
    let hidden = true;
    Object.defineProperty(document, 'hidden', {
      configurable: true,
      get: () => hidden,
    });
    try {
      renderPage();
      // Flush the initial (non-poll) load.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(API.getLogFile).toHaveBeenCalledTimes(1);

      // Enable auto-refresh, then let two intervals elapse while hidden.
      fireEvent.click(screen.getByRole('checkbox'));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(11000);
      });
      expect(API.getLogFile).toHaveBeenCalledTimes(1);

      // Once the tab is visible again, the next tick polls.
      hidden = false;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000);
      });
      expect(API.getLogFile).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
      delete document.hidden;
    }
  });
});
