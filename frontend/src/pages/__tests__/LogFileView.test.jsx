import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from '@testing-library/react';
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
  Select: ({ label, value, onChange, data }) => (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      {data.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
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
    // useBrowserStorage persists between cases, so the interval leaks otherwise.
    localStorage.clear();
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
    ['text', 'error', 'warn', 'login/auth', 'plugin'].forEach((label) =>
      expect(screen.getByText(label)).toBeInTheDocument()
    );
  });

  it('colours severity on the level token and category on the message', async () => {
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
    // Severity colours the level token, never the message text.
    expect(screen.getByText('ERROR')).toHaveStyle({ color: '#ff6b6b' });
    expect(screen.getByText(/boom failure/)).not.toHaveStyle({
      color: '#ff6b6b',
    });
    screen
      .getAllByText('WARNING')
      .forEach((token) => expect(token).toHaveStyle({ color: '#ffd43b' }));
    expect(screen.getByText(/cache miss/)).not.toHaveStyle({
      color: '#ffd43b',
    });
    // Category colours the message: plugin blue, auth green.
    expect(screen.getByText(/sweep done/)).toHaveStyle({ color: '#74c0fc' });
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

  it('renders continuations inside their record block behind the level bar', async () => {
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
    // The CRITICAL token wears red and the block's bar marks the whole record.
    expect(screen.getByText('CRITICAL')).toHaveStyle({ color: '#ff6b6b' });
    expect(screen.getByText('CRITICAL').closest('div')).toHaveStyle({
      borderLeft: '3px solid #ff6b6b',
    });
    // Both continuation lines stay one joined text node inside the block.
    expect(screen.getByText(/Retry limit exceeded/).textContent).toContain(
      'must be restarted'
    );
    // The next record is its own block and does not inherit the bar.
    expect(screen.getByText(/back to normal/).closest('div')).not.toHaveStyle({
      borderLeft: '3px solid #ff6b6b',
    });
  });

  it('shows severity and category together on a plugin error', async () => {
    API.getLogFile.mockResolvedValue({
      content: '2026-07-15 10:00:06,000 ERROR plugins.iptv_checker sweep died',
      truncated: false,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/sweep died/)).toBeInTheDocument();
    });
    expect(screen.getByText('ERROR')).toHaveStyle({ color: '#ff6b6b' });
    expect(screen.getByText(/sweep died/)).toHaveStyle({ color: '#74c0fc' });
  });

  it('displays the module token with the raw source on hover', async () => {
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-08-21 10:00:00,000 INFO apps.epg.tasks Processed 3133 channels',
        '2026-08-21 10:00:01,000 INFO plugins.event_channel_managarr Scheduled scan completed',
        '2026-08-21 10:00:02,000 INFO nginx.access 192.0.2.7 - - "GET / HTTP/1.1" 200',
        '2026-08-21 10:00:03,000 INFO postgres [312] LOG:  checkpoint complete',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await screen.findByText(/Processed 3133/);
    expect(screen.getByTitle('apps.epg.tasks')).toHaveTextContent('epg');
    expect(
      screen.getByTitle('plugins.event_channel_managarr')
    ).toHaveTextContent('event_channel_managarr');
    expect(screen.getByTitle('nginx.access')).toHaveTextContent('nginx');
    expect(screen.getByTitle('postgres')).toHaveTextContent('postgres');
    // The raw dotted name is display-only metadata now, not rendered text.
    expect(screen.queryByText('apps.epg.tasks')).not.toBeInTheDocument();
    // The stamp recedes to grey.
    expect(screen.getByText('2026-08-21 10:00:00,000')).toHaveStyle({
      color: '#71717a',
    });
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

  it('drops routine token-refresh/notification 401 polling to default text, keeps other 401s green', async () => {
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
    // Benign polling 401s fall through to default text — severity already shows on the WARNING token.
    expect(screen.getByText(/token\/refresh/)).not.toHaveStyle({
      color: '#51cf66',
    });
    expect(screen.getByText(/notifications/)).not.toHaveStyle({
      color: '#51cf66',
    });
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
      {
        tag: 'INFO',
        logger: 'core.tasks',
        msg: 'routine tick, nothing to report this cycle',
      },
      {
        tag: 'WARNING',
        logger: 'core.utils',
        msg: 'cache miss while resolving stream metadata lookup',
      },
      {
        tag: 'ERROR',
        logger: 'apps.epg',
        msg: 'boom failure refreshing programme guide data source',
      },
      {
        tag: 'INFO',
        logger: 'apps.accounts.api_views',
        msg: 'Login success: user=demo ip=192.0.2.7 session=abcdef',
      },
      {
        tag: 'INFO',
        logger: 'plugins.iptv_checker',
        msg: 'sweep tick probing configured channel groups',
      },
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
    expect(
      screen.getByText(/Showing the last [\d,]+ lines/)
    ).toBeInTheDocument();
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
      fireEvent.change(screen.getByLabelText('Auto Refresh'), {
        target: { value: '5' },
      });
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

  it('renders newest first by default and flips to newest last', async () => {
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-07-15 10:00:00,000 INFO core.tasks alpha',
        '2026-07-15 10:00:01,000 INFO core.tasks omega',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await screen.findByText(/alpha/);
    const before = document.body.textContent;
    expect(before.indexOf('omega')).toBeLessThan(before.indexOf('alpha'));

    fireEvent.change(screen.getByLabelText('Order'), {
      target: { value: 'oldest' },
    });
    const after = document.body.textContent;
    expect(after.indexOf('alpha')).toBeLessThan(after.indexOf('omega'));
  });

  it('does not poll while the interval is zero', async () => {
    vi.useFakeTimers();
    try {
      renderPage();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(API.getLogFile).toHaveBeenCalledTimes(1);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(60000);
      });
      expect(API.getLogFile).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('falls back to Manual when the stored interval is not an option', async () => {
    vi.useFakeTimers();
    localStorage.setItem('log-viewer-refresh-interval', '7');
    try {
      renderPage();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(screen.getByLabelText('Auto Refresh')).toHaveValue('0');
      await act(async () => {
        await vi.advanceTimersByTimeAsync(60000);
      });
      expect(API.getLogFile).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('polls at the chosen interval', async () => {
    vi.useFakeTimers();
    try {
      renderPage();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      fireEvent.change(screen.getByLabelText('Auto Refresh'), {
        target: { value: '10' },
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(9000);
      });
      expect(API.getLogFile).toHaveBeenCalledTimes(1);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1500);
      });
      expect(API.getLogFile).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('filters records below the chosen level with their continuations', async () => {
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-07-15 10:00:00,000 DEBUG core.tasks noisy tick',
        '    noisy continuation detail',
        '2026-07-15 10:00:01,000 INFO core.tasks routine note',
        '2026-07-15 10:00:02,000 ERROR apps.epg boom failure',
        '2026-07-15 10:00:03,000 NOTE core.tasks unknown level survives',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await screen.findByText(/noisy tick/);

    fireEvent.change(screen.getByLabelText('Level'), {
      target: { value: '30' },
    });
    expect(screen.queryByText(/noisy tick/)).not.toBeInTheDocument();
    expect(screen.queryByText(/noisy continuation/)).not.toBeInTheDocument();
    expect(screen.queryByText(/routine note/)).not.toBeInTheDocument();
    expect(screen.getByText(/boom failure/)).toBeInTheDocument();
    // A record with an unrecognised level token is never hidden.
    expect(screen.getByText(/unknown level survives/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Level'), {
      target: { value: '0' },
    });
    expect(screen.getByText(/noisy tick/)).toBeInTheDocument();
  });

  it('keeps a whole traceback when filtering, and reports an empty result', async () => {
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-07-15 10:00:00,000 ERROR apps.epg refresh failed',
        'Traceback (most recent call last):',
        '  File "/app/x.py", line 1, in run',
        'ValueError: bad m3u',
        '2026-07-15 10:00:01,000 DEBUG core.tasks quiet',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await screen.findByText(/refresh failed/);

    fireEvent.change(screen.getByLabelText('Level'), {
      target: { value: '40' },
    });
    // The tail line is unstamped, so it stays with the ERROR it belongs to.
    expect(screen.getByText(/ValueError: bad m3u/)).toBeInTheDocument();
    expect(screen.queryByText(/quiet/)).not.toBeInTheDocument();

    API.getLogFile.mockResolvedValue({
      content: '2026-07-15 10:00:01,000 DEBUG core.tasks quiet\n',
      truncated: false,
    });
    fireEvent.click(screen.getByText('Refresh'));
    await waitFor(() => {
      expect(
        screen.getByText('(no records match the filters)')
      ).toBeInTheDocument();
    });
  });

  it('filters records by module with their continuations', async () => {
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-08-21 10:00:00,000 INFO apps.epg.tasks epg tick',
        '2026-08-21 10:00:01,000 ERROR core.tasks core boom',
        'core continuation detail',
        '2026-08-21 10:00:02,000 INFO apps.m3u.tasks m3u tick',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await screen.findByText(/epg tick/);

    fireEvent.change(screen.getByLabelText('Module'), {
      target: { value: 'core' },
    });
    expect(screen.getByText(/core boom/)).toBeInTheDocument();
    // The unstamped continuation stays with its record.
    expect(screen.getByText(/core continuation detail/)).toBeInTheDocument();
    expect(screen.queryByText(/epg tick/)).not.toBeInTheDocument();
    expect(screen.queryByText(/m3u tick/)).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Module'), {
      target: { value: 'all' },
    });
    expect(screen.getByText(/epg tick/)).toBeInTheDocument();
  });

  it('falls back to all modules when the stored module is absent from the file', async () => {
    localStorage.setItem('log-viewer-module', '"ghost"');
    API.getLogFile.mockResolvedValue({
      content: '2026-08-21 10:00:00,000 INFO core.tasks alive\n',
      truncated: false,
    });
    renderPage();
    await screen.findByText(/alive/);
    expect(screen.getByLabelText('Module')).toHaveValue('all');
  });

  it('keeps a multi-line record intact when reversed', async () => {
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-07-15 10:00:00,000 ERROR apps.epg first failure',
        'continuation of the first record',
        '2026-07-15 10:00:01,000 ERROR apps.epg second failure',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await screen.findByText(/second failure/);
    const text = document.body.textContent;
    expect(text.indexOf('second failure')).toBeLessThan(
      text.indexOf('first failure')
    );
    expect(text.indexOf('first failure')).toBeLessThan(
      text.indexOf('continuation of the first record')
    );
  });
});
