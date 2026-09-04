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
  // ref/onScroll pass through: the viewer pins itself to the live edge.
  Box: ({ children, style, onScroll, ref }) => (
    <div style={style} ref={ref} onScroll={onScroll}>
      {children}
    </div>
  ),
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
        <option
          key={option.value}
          value={option.value}
          disabled={option.disabled}
        >
          {option.label}
        </option>
      ))}
    </select>
  ),
  Text: ({ children, c }) => <span data-colour={c}>{children}</span>,
  TextInput: ({ label, value, onChange, placeholder }) => (
    <input
      aria-label={label}
      placeholder={placeholder}
      value={value}
      onChange={onChange}
    />
  ),
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
      cursor: null,
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

  it('colours a record by severity alone, level token and message together', async () => {
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-07-15 10:00:00,000 INFO core.tasks routine tick',
        '2026-07-15 10:00:01,000 ERROR apps.epg boom failure',
        '2026-07-15 10:00:02,000 WARNING core.utils cache miss',
        '2026-07-15 10:00:03,000 INFO plugins.iptv_checker sweep done',
        '2026-07-15 10:00:04,000 ERROR plugins.iptv_checker sweep died',
        '2026-07-15 10:00:05,000 WARNING django.request Unauthorized: /api/x/',
        '2026-07-15 10:00:06,000 INFO apps.accounts.api_views Login success: user=demo ip=192.0.2.7',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/boom failure/)).toBeInTheDocument();
    });
    screen
      .getAllByText('ERROR')
      .forEach((token) => expect(token).toHaveStyle({ color: '#ff6b6b' }));
    expect(screen.getByText(/boom failure/)).toHaveStyle({ color: '#ff6b6b' });
    screen
      .getAllByText('WARN')
      .forEach((token) => expect(token).toHaveStyle({ color: '#ffd43b' }));
    expect(screen.getByText(/cache miss/)).toHaveStyle({ color: '#ffd43b' });
    expect(screen.getByText(/Unauthorized/)).toHaveStyle({ color: '#ffd43b' });
    expect(screen.getByText(/routine tick/)).not.toHaveStyle({
      color: '#ff6b6b',
    });
    expect(screen.getByText(/sweep done/)).not.toHaveStyle({
      color: '#74c0fc',
    });
    expect(screen.getByText(/sweep died/)).toHaveStyle({ color: '#ff6b6b' });
    expect(screen.getByText(/Login success/)).not.toHaveStyle({
      color: '#51cf66',
    });
  });

  it('renders a traceback inside its record block behind the level bar', async () => {
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-07-15 10:00:07,000 ERROR apps.epg refresh failed',
        'Traceback (most recent call last):',
        '  File "/app/x.py", line 214, in refresh',
        'ValueError: bad feed',
        '2026-07-15 10:00:08,000 INFO core.tasks back to normal',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/refresh failed/)).toBeInTheDocument();
    });
    expect(screen.getByText('ERROR')).toHaveStyle({ color: '#ff6b6b' });
    expect(screen.getByText('ERROR').closest('div')).toHaveStyle({
      borderLeft: '2px solid #ff6b6b',
    });
    // The traceback, its column-0 tail included, is one joined text node.
    expect(screen.getByText(/Traceback/).textContent).toContain(
      'ValueError: bad feed'
    );
    expect(screen.getByText(/back to normal/).closest('div')).not.toHaveStyle({
      borderLeft: '2px solid #ff6b6b',
    });
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
    expect(screen.queryByText('apps.epg.tasks')).not.toBeInTheDocument();
    expect(screen.getByText('2026-08-21 10:00:00,000')).toHaveStyle({
      color: '#a1a1aa',
    });
  });

  it('spells the numeric offset out as a UTC label', async () => {
    // The file keeps "+1200" for external tooling; only the display changes.
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-08-21 21:35:01,472 +1200 INFO core.tasks southern hemisphere',
        '2026-08-21 09:35:01,472 -0330 INFO core.tasks half hour zone',
        '2026-08-21 09:35:01,472 INFO core.tasks no offset at all',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await screen.findByText(/southern hemisphere/);
    expect(
      screen.getByText('2026-08-21 21:35:01,472 [UTC+12]')
    ).toBeInTheDocument();
    expect(
      screen.getByText('2026-08-21 09:35:01,472 [UTC-3:30]')
    ).toBeInTheDocument();
    // Offset-less stamps come from the pre-collector boot window.
    expect(screen.getByText('2026-08-21 09:35:01,472')).toBeInTheDocument();
    expect(screen.queryByText(/\+1200/)).not.toBeInTheDocument();
  });

  it('does not redden an INFO line whose message body mentions ERROR', async () => {
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

  it('shows a load error with Retry and recovers when Retry succeeds', async () => {
    // A non-silent failure rejects once errorNotification has toasted.
    API.getLogFile.mockRejectedValue(new Error('HTTP error! Status: 500'));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/Failed to load/)).toBeInTheDocument();
    });
    expect(screen.getByText('Retry')).toBeInTheDocument();
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
    // Interleaves every level so the colour changes on most rows.
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
      // Continuations exercise the inherited-colour path.
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
    // The payload must genuinely approach the 5 MB truncation ceiling.
    expect(content.length).toBeGreaterThan(4 * 1024 * 1024);

    API.getLogFile.mockResolvedValue({ content, truncated: true });

    renderPage();
    // No wall-clock assertion: slowness must not fail this, but a hang still will.
    await screen.findByText(
      /END-OF-SYNTHETIC-LOG-MARKER/,
      {},
      { timeout: 30000 }
    );
    expect(screen.queryByTestId('loader')).not.toBeInTheDocument();
    expect(screen.queryByText('(empty)')).not.toBeInTheDocument();
    expect(
      screen.getByText(/Showing the last [\d,]+ lines/)
    ).toBeInTheDocument();
    expect(screen.queryByText(/record-0\b/)).not.toBeInTheDocument();
  }, 60000);

  it('does not poll while the tab is hidden', async () => {
    vi.useFakeTimers();
    let hidden = true;
    Object.defineProperty(document, 'hidden', {
      configurable: true,
      get: () => hidden,
    });
    try {
      renderPage();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(API.getLogFile).toHaveBeenCalledTimes(1);

      fireEvent.change(screen.getByLabelText('Auto Refresh'), {
        target: { value: '5' },
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(11000);
      });
      expect(API.getLogFile).toHaveBeenCalledTimes(1);

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

  it('renders newest last by default and flips to newest first', async () => {
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-07-15 10:00:00,000 INFO core.tasks alpha',
        '2026-07-15 10:00:01,000 INFO core.tasks omega',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await screen.findByText(/alpha/);
    // File order by default, so boot banners and tracebacks read top-down.
    const before = document.body.textContent;
    expect(before.indexOf('alpha')).toBeLessThan(before.indexOf('omega'));

    fireEvent.change(screen.getByLabelText('Order'), {
      target: { value: 'newest' },
    });
    const after = document.body.textContent;
    expect(after.indexOf('omega')).toBeLessThan(after.indexOf('alpha'));
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

  it('pauses after three failed polls without touching the stored interval', async () => {
    vi.useFakeTimers();
    try {
      renderPage();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      fireEvent.change(screen.getByLabelText('Auto Refresh'), {
        target: { value: '5' },
      });
      API.getLogFile.mockResolvedValue(undefined);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(16000);
      });
      expect(API.getLogFile).toHaveBeenCalledTimes(4);
      expect(localStorage.getItem('log-viewer-refresh-interval')).toBe('5');
      expect(screen.getByLabelText('Auto Refresh')).toHaveValue('0');
    } finally {
      vi.useRealTimers();
    }
  });

  it('defaults the level floor to Info', async () => {
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-08-21 10:00:00,000 DEBUG core.tasks chatter',
        '2026-08-21 10:00:01,000 INFO core.tasks visible line',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await screen.findByText(/visible line/);
    expect(screen.getByLabelText('Level')).toHaveValue('20');
    expect(screen.queryByText(/chatter/)).not.toBeInTheDocument();
  });

  it('filters records below the chosen level with their continuations', async () => {
    // Start from the Debug floor so the DEBUG fixture is visible before filtering.
    localStorage.setItem('log-viewer-min-level', '10');
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
    expect(screen.getByText(/unknown level survives/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Level'), {
      target: { value: '10' },
    });
    expect(screen.getByText(/noisy tick/)).toBeInTheDocument();
  });

  it('bundles TRACE into DEBUG for display and filtering', async () => {
    localStorage.setItem('log-viewer-min-level', '10');
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-08-21 10:00:00,000 TRACE core.utils Redis persistence disabled',
        '2026-08-21 10:00:01,000 INFO core.tasks routine tick',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await screen.findByText(/routine tick/);
    expect(screen.getByText(/Redis persistence disabled/)).toBeInTheDocument();
    expect(screen.getByText('DEBUG')).toHaveAttribute('title', 'TRACE');
    fireEvent.change(screen.getByLabelText('Level'), {
      target: { value: '20' },
    });
    expect(
      screen.queryByText(/Redis persistence disabled/)
    ).not.toBeInTheDocument();
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

  it('keeps the columns out of the wrap and the hanging indent', async () => {
    API.getLogFile.mockResolvedValue({
      content:
        '2026-08-21 10:00:00,000 WARNING plugins.event_channel_managarr scan slow',
      truncated: false,
    });
    renderPage();
    await screen.findByText(/scan slow/);
    // Without both, the token wraps in its box or draws off the left edge.
    const opts = { whiteSpace: 'nowrap', textIndent: '0px' };
    expect(screen.getByText('2026-08-21 10:00:00,000')).toHaveStyle(opts);
    expect(screen.getByText('WARN')).toHaveStyle(opts);
    expect(screen.getByTitle('plugins.event_channel_managarr')).toHaveStyle(
      opts
    );
    expect(screen.getByText(/scan slow/)).not.toHaveStyle({
      whiteSpace: 'nowrap',
    });
  });

  it('wraps a long line under the message column instead of scrolling', async () => {
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-08-21 10:00:00,000 ERROR postgres [312] STATEMENT:  ' +
          'x'.repeat(4000),
        '  continuation tail',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    const message = await screen.findByText(/STATEMENT/);
    const pane = message.closest('div').parentElement;
    expect(pane).toHaveStyle({
      whiteSpace: 'pre-wrap',
      overflowWrap: 'anywhere',
    });
    // 39ch = stamp 23 + level 5 + module 8 + 3 gaps.
    const block = message.closest('div');
    expect(block).toHaveStyle({
      paddingLeft: 'calc(8px + 39ch)',
      textIndent: '-39ch',
    });
    // Continuations already sit at that column, so they cancel the hang.
    expect(screen.getByText(/continuation tail/).parentElement).toHaveStyle({
      textIndent: '0px',
    });
  });

  it('scrolls the records inside the panel, not the page', async () => {
    renderPage();
    await screen.findByText(/Scanning disk/);
    // control group -> header row -> the panel header itself.
    const header = screen.getByLabelText('Level').closest('div')
      .parentElement.parentElement;
    let scroller = screen.getByText(/Scanning disk/).parentElement;
    while (scroller && getComputedStyle(scroller).overflow !== 'auto') {
      scroller = scroller.parentElement;
    }
    expect(scroller).not.toBeNull();
    expect(scroller.contains(header)).toBe(false);
    expect(header.parentElement).toBe(scroller.parentElement);
    expect(scroller).toHaveStyle({ flex: '1 1 auto', minHeight: '0px' });
  });

  it('holds the message column still while the filters change', async () => {
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-08-21 10:00:00,000 INFO plugins.event_channel_managarr scan done',
        '2026-08-21 10:00:01,000 INFO core.tasks tick',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await screen.findByText(/scan done/);
    // 23 stamp + 5 level + 12 module (capped) + 3 separators.
    const indent = { paddingLeft: 'calc(8px + 43ch)', textIndent: '-43ch' };
    expect(screen.getByText(/tick/).closest('div')).toHaveStyle(indent);
    // Filtering the long module out of view must not re-measure the columns.
    fireEvent.change(screen.getByLabelText('Search'), {
      target: { value: 'tick' },
    });
    await waitFor(() =>
      expect(screen.queryByText(/scan done/)).not.toBeInTheDocument()
    );
    expect(screen.getByText(/tick/).closest('div')).toHaveStyle(indent);
  });

  it('dims the lines no record owns', async () => {
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-08-21 10:00:00,000 ERROR apps.vod batch failed',
        'raw daemon chatter nothing stamped',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await screen.findByText(/batch failed/);
    expect(screen.getByText(/raw daemon chatter/)).toHaveStyle({
      color: '#a1a1aa',
    });
    expect(screen.getByText(/batch failed/)).toHaveStyle({ color: '#ff6b6b' });
  });

  it('drops the severity bar once every visible row would wear one', async () => {
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-08-21 10:00:00,000 INFO core.tasks tick',
        '2026-08-21 10:00:01,000 WARNING core.utils cache miss',
        '2026-08-21 10:00:02,000 ERROR apps.epg boom',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await screen.findByText(/boom/);
    const bar = (text) => screen.getByText(text).closest('div');
    expect(bar(/cache miss/)).toHaveStyle({ borderLeft: '2px solid #ffd43b' });
    expect(bar(/boom/)).toHaveStyle({ borderLeft: '2px solid #ff6b6b' });
    fireEvent.change(screen.getByLabelText('Level'), {
      target: { value: '30' },
    });
    expect(bar(/cache miss/)).not.toHaveStyle({
      borderLeft: '2px solid #ffd43b',
    });
    expect(bar(/boom/)).toHaveStyle({ borderLeft: '2px solid #ff6b6b' });
    fireEvent.change(screen.getByLabelText('Level'), {
      target: { value: '40' },
    });
    expect(bar(/boom/)).not.toHaveStyle({ borderLeft: '2px solid #ff6b6b' });
    expect(screen.getByText(/boom/)).toHaveStyle({ color: '#ff6b6b' });
  });

  it('states an empty result in the app voice, not the log font', async () => {
    API.getLogFile.mockResolvedValue({
      content: '2026-08-21 10:00:00,000 INFO core.tasks tick',
      truncated: false,
    });
    renderPage();
    await screen.findByText(/tick/);
    fireEvent.change(screen.getByLabelText('Search'), {
      target: { value: 'nothing matches this' },
    });
    expect(
      await screen.findByText('(no records match the filters)')
    ).toHaveAttribute('data-colour', 'dimmed');
  });

  it('aligns tokens in equal-width columns', async () => {
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-08-21 10:00:00,000 INFO core.tasks short module line',
        '2026-08-21 10:00:01,000 ERROR plugins.event_channel_managarr long module line',
        '    trailing continuation detail',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await screen.findByText(/short module line/);
    // The module column caps at 12ch however long the module is.
    expect(screen.getByTitle('core.tasks')).toHaveStyle({ width: '12ch' });
    expect(screen.getByTitle('plugins.event_channel_managarr')).toHaveStyle({
      width: '12ch',
    });
    expect(screen.getByText(/long module line/).closest('div')).toHaveStyle({
      paddingLeft: 'calc(8px + 43ch)',
      textIndent: '-43ch',
    });
    expect(
      screen.getByText(/trailing continuation detail/).parentElement
    ).toHaveStyle({ textIndent: '0px' });
  });

  it('compresses level display names without touching their rank', async () => {
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-08-21 10:00:00,000 CRITICAL core.tasks meltdown',
        '2026-08-21 10:00:01,000 WARNING core.utils toasty',
        '2026-08-21 10:00:02,000 DEBUG core.utils chatter',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await screen.findByText(/meltdown/);
    expect(screen.getByText('ERROR')).toHaveAttribute('title', 'CRITICAL');
    expect(screen.getByText('WARN')).toHaveAttribute('title', 'WARNING');
    fireEvent.change(screen.getByLabelText('Level'), {
      target: { value: '40' },
    });
    expect(screen.getByText(/meltdown/)).toBeInTheDocument();
    expect(screen.queryByText(/toasty/)).not.toBeInTheDocument();
  });

  it('keeps a plugin submodule under its plugin key', async () => {
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-08-21 10:00:00,000 INFO plugins.iptv_checker sweep started',
        '2026-08-21 10:00:01,000 INFO plugins.iptv_checker.scheduled nightly run',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await screen.findByText(/sweep started/);
    expect(
      screen.getByTitle('plugins.iptv_checker.scheduled').textContent
    ).toBe('iptv_checker');
    expect(screen.getByTitle('plugins.iptv_checker').textContent).toBe(
      'iptv_checker'
    );
  });

  it('claims the column-0 tail of an unstamped traceback', async () => {
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-08-21 10:00:00,000 INFO stdout unhandled error in worker',
        'Traceback (most recent call last):',
        '  File "/app/x.py", line 12, in run',
        'ValueError: bad feed',
        'During handling of the above exception, another exception occurred:',
        '2026-08-21 10:00:01,000 INFO core.tasks back to normal',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await screen.findByText(/back to normal/);
    const tail = screen.getByText(/ValueError: bad feed/);
    expect(tail.textContent).toContain(
      'During handling of the above exception'
    );
    expect(tail.parentElement).toHaveStyle({ textIndent: '0px' });
    fireEvent.change(screen.getByLabelText('Category'), {
      target: { value: 'app' },
    });
    expect(screen.queryByText(/ValueError: bad feed/)).not.toBeInTheDocument();
    expect(screen.getByText(/back to normal/)).toBeInTheDocument();
  });

  it('gates a record whose level the collector invented like any other', async () => {
    // The floor exemption belongs to the sinks; a filtered view is reversible.
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-08-21 10:00:00,000 ERROR core.tasks Traceback (most recent call last):',
        '  File "/app/x.py", line 3, in run',
        '2026-08-21 10:00:00,001 INFO stdout Setting up PostgreSQL...',
        '2026-08-21 10:00:01,000 INFO core.tasks routine tick',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await screen.findByText(/routine tick/);
    fireEvent.change(screen.getByLabelText('Level'), {
      target: { value: '40' },
    });
    expect(screen.queryByText(/routine tick/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Setting up PostgreSQL/)).not.toBeInTheDocument();
    expect(screen.getByText(/Traceback/)).toBeInTheDocument();
  });

  it('leaves an unowned continuation run unowned when the order flips', async () => {
    // Reversing entries would graft a headless continuation onto another record.
    API.getLogFile.mockResolvedValue({
      content: [
        '  orphaned frame from a record the tail cut off',
        '2026-08-21 10:00:01,000 ERROR apps.epg refresh failed',
      ].join('\n'),
      truncated: true,
    });
    renderPage();
    await screen.findByText(/orphaned frame/);
    const owner = screen.getByText(/refresh failed/).closest('div');
    expect(owner.textContent).not.toContain('orphaned frame');
    fireEvent.change(screen.getByLabelText('Order'), {
      target: { value: 'newest' },
    });
    const afterFlip = screen.getByText(/refresh failed/).closest('div');
    expect(afterFlip.textContent).not.toContain('orphaned frame');
    expect(screen.getByText(/orphaned frame/)).toBeInTheDocument();
  });

  it('keeps the byte of a single blank continuation line', async () => {
    // Joined to '' a lone blank renders no text node and drops from the copy buffer.
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-08-21 10:00:00,000 ERROR core.tasks refresh failed',
        'Traceback (most recent call last):',
        '',
        'ValueError: bad feed',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await screen.findByText(/Traceback/);
    const segments = screen.getByText(/ValueError/).parentElement;
    const blank = segments.children[1];
    expect(blank).toHaveStyle({ lineHeight: '0.35' });
    expect(blank.textContent).toBe('\n');
  });

  it('does not render the newline that ends the body as a blank line', async () => {
    API.getLogFile.mockResolvedValue({
      content: '2026-08-21 10:00:00,000 INFO core.tasks hello there\n',
      truncated: false,
    });
    const { container } = renderPage();
    await screen.findByText(/hello there/);
    expect(
      container.querySelector('div[style*="line-height: 0.35"]')
    ).toBeNull();
  });

  it('never hides the collector pass-through records behind a filter', async () => {
    // A known source shape with an unparseable date reaches the viewer unstamped.
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-08-21 10:00:00,000 DEBUG core.utils quiet tick',
        '345:M 99 Xxx 2026 01:00:07.211 # Memory overcommit must be enabled',
        '2026-08-21 10:00:01,000 ERROR apps.epg boom failure',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await screen.findByText(/boom failure/);
    fireEvent.change(screen.getByLabelText('Level'), {
      target: { value: '30' },
    });
    expect(screen.queryByText(/quiet tick/)).not.toBeInTheDocument();
    expect(screen.getByText(/Memory overcommit/)).toBeInTheDocument();
  });

  it('tokenizes a record whose message carries a bare carriage return', async () => {
    API.getLogFile.mockResolvedValue({
      content:
        '2026-08-21 10:00:00,000 INFO stdout frame=1 fps=0\rframe=30 fps=29',
      truncated: false,
    });
    renderPage();
    await screen.findByText(/frame=1/);
    // JS '.' excludes \r; the [\s\S] body keeps this one record.
    expect(screen.getByTitle('stdout')).toHaveTextContent('stdout');
    expect(screen.getByText(/frame=1/).textContent).toContain('frame=30');
  });

  it('does not read a torn offset as the level', async () => {
    API.getLogFile.mockResolvedValue({
      content: '2026-08-21 10:00:00,000 +1200 INFO',
      truncated: false,
    });
    renderPage();
    expect(await screen.findByText(/\+1200 INFO/)).toBeInTheDocument();
    expect(screen.queryByTitle('+1200')).toBeNull();
  });

  it('does not invent a separator the file lacks', async () => {
    API.getLogFile.mockResolvedValue({
      content: '2026-08-21 10:00:00,000 INFO core.tasks',
      truncated: false,
    });
    renderPage();
    await screen.findByText('INFO');
    expect(screen.getByText('INFO').closest('div').textContent).toBe(
      '2026-08-21 10:00:00,000 INFO core'
    );
  });

  it('filters by category, the only record filter besides level and text', async () => {
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-08-21 10:00:00,000 INFO apps.epg.tasks app line',
        '2026-08-21 10:00:01,000 INFO postgres [312] LOG:  daemon line',
        '2026-08-21 10:00:02,000 INFO celery.beat framework line',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await screen.findByText(/app line/);
    expect(screen.queryByLabelText('Module')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Category'), {
      target: { value: 'services' },
    });
    // Services covers native daemons and third-party Python alike.
    expect(screen.getByText(/daemon line/)).toBeInTheDocument();
    expect(screen.getByText(/framework line/)).toBeInTheDocument();
    expect(screen.queryByText(/app line/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Level'), {
      target: { value: '10' },
    });
    expect(screen.queryByLabelText('Module')).not.toBeInTheDocument();
  });

  it('collects the plugin infrastructure under the Plugins category', async () => {
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-08-21 10:00:00,000 INFO apps.plugins.loader Discovered 5 plugin(s)',
        '2026-08-21 10:00:01,000 INFO plugins.epg_watchdog Sweep done',
        '2026-08-21 10:00:02,000 INFO apps.epg.tasks epg tick',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await screen.findByText(/epg tick/);
    fireEvent.change(screen.getByLabelText('Category'), {
      target: { value: 'plugins' },
    });
    // Plugin infrastructure files with its plugins; the token stays third-party.
    expect(screen.getByText(/Discovered 5 plugin/)).toBeInTheDocument();
    expect(screen.getByText(/Sweep done/)).toBeInTheDocument();
    expect(screen.queryByText(/epg tick/)).not.toBeInTheDocument();
    expect(screen.getByTitle('apps.plugins.loader')).toHaveTextContent(
      'plugin_sys'
    );
  });

  it('maps the loader import name to the plugin key under Plugins', async () => {
    localStorage.setItem('log-viewer-min-level', '10');
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-08-21 10:00:00,000 INFO _dispatcharr_plugin_epg_watchdog.plugin Sweep done',
        '2026-08-21 10:00:01,000 DEBUG django.geventpool DB connection reused',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await screen.findByText(/Sweep done/);
    // getLogger(__name__) inside a plugin wears the loader's import name.
    expect(
      screen.getByTitle('_dispatcharr_plugin_epg_watchdog.plugin')
    ).toHaveTextContent('epg_watchdog');
    // First-party pool code under the django namespace files with App.
    expect(screen.getByTitle('django.geventpool')).toHaveTextContent(
      'geventpool'
    );
    fireEvent.change(screen.getByLabelText('Category'), {
      target: { value: 'app' },
    });
    expect(screen.getByText(/DB connection reused/)).toBeInTheDocument();
    expect(screen.queryByText(/Sweep done/)).not.toBeInTheDocument();
  });

  it('does not re-filter on every keystroke', async () => {
    // A pass rebuilds up to MAX_RENDER_LINES blocks: one filter per word, not letter.
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-08-21 10:00:00,000 INFO core.tasks alpha',
        '2026-08-21 10:00:01,000 INFO core.tasks beta',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await screen.findByText(/alpha/);
    const box = screen.getByLabelText('Search');
    for (const value of ['b', 'be', 'bet', 'beta']) {
      fireEvent.change(box, { target: { value } });
    }
    // Mid-word the list is untouched: no intermediate filter ran.
    expect(screen.getByText(/alpha/)).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByText(/alpha/)).not.toBeInTheDocument()
    );
    expect(screen.getByText(/beta/)).toBeInTheDocument();
  });

  it('filters by free text across whole record blocks', async () => {
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-08-21 10:00:00,000 INFO core.tasks alpha event',
        '2026-08-21 10:00:01,000 ERROR apps.epg refresh failed',
        'Traceback (most recent call last):',
        'ValueError: beta marker',
        '2026-08-21 10:00:02,000 INFO core.tasks gamma event',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await screen.findByText(/alpha event/);
    fireEvent.change(screen.getByLabelText('Search'), {
      target: { value: 'beta' },
    });
    await waitFor(() =>
      expect(screen.queryByText(/alpha event/)).not.toBeInTheDocument()
    );
    expect(screen.getByText(/refresh failed/)).toBeInTheDocument();
    expect(screen.getByText(/Traceback/).textContent).toContain('beta marker');
    expect(screen.queryByText(/gamma event/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Search'), {
      target: { value: '' },
    });
    expect(await screen.findByText(/alpha event/)).toBeInTheDocument();
  });

  it('renders blank continuation runs at reduced height', async () => {
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-08-21 10:00:00,000 ERROR apps.epg boom',
        'Traceback (most recent call last):',
        'ValueError: first',
        '',
        'During handling of the above exception, another exception occurred:',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await screen.findByText(/ValueError: first/);
    const padded = screen.getByText(/ValueError: first/).parentElement;
    // Three segments: text, the compressed blank run, text.
    expect(padded.children).toHaveLength(3);
    expect(padded.children[1]).toHaveStyle({ lineHeight: '0.35' });
    expect(screen.getByText(/During handling/)).toBeInTheDocument();
  });

  it('keeps a multi-line record intact when reversed', async () => {
    API.getLogFile.mockResolvedValue({
      content: [
        '2026-07-15 10:00:00,000 ERROR apps.epg first failure',
        '    continuation of the first record',
        '2026-07-15 10:00:01,000 ERROR apps.epg second failure',
      ].join('\n'),
      truncated: false,
    });
    renderPage();
    await screen.findByText(/second failure/);
    fireEvent.change(screen.getByLabelText('Order'), {
      target: { value: 'newest' },
    });
    const text = document.body.textContent;
    expect(text.indexOf('second failure')).toBeLessThan(
      text.indexOf('first failure')
    );
    expect(text.indexOf('first failure')).toBeLessThan(
      text.indexOf('continuation of the first record')
    );
  });
  it('appends an incremental delta instead of replacing the buffer', async () => {
    API.getLogFile.mockResolvedValue({
      content: 'Info|core.tasks|first line\n',
      truncated: false,
      cursor: '99-30',
      reset: true,
    });
    renderPage();
    await screen.findByText(/first line/);

    // Only the new bytes come back, and the cursor rides along on the next ask.
    API.getLogFile.mockResolvedValue({
      content: 'Info|core.tasks|second line\n',
      truncated: false,
      cursor: '99-61',
      reset: false,
    });
    await act(async () => {
      fireEvent.click(screen.getByText('Refresh'));
    });

    await screen.findByText(/second line/);
    // The first line is still there: the delta was appended, not swapped in.
    expect(screen.getByText(/first line/)).toBeInTheDocument();
    expect(API.getLogFile).toHaveBeenLastCalledWith('dispatcharr.log', {
      silent: false,
      cursor: '99-30',
    });
  });

  it('replaces the buffer when the server reports a reset', async () => {
    API.getLogFile.mockResolvedValue({
      content: 'Info|core.tasks|from the old file\n',
      truncated: false,
      cursor: '99-40',
      reset: true,
    });
    renderPage();
    await screen.findByText(/from the old file/);

    // A rotation: the server resets rather than resuming a meaningless offset.
    API.getLogFile.mockResolvedValue({
      content: 'Info|core.tasks|from the new file\n',
      truncated: false,
      cursor: '100-40',
      reset: true,
    });
    await act(async () => {
      fireEvent.click(screen.getByText('Refresh'));
    });

    await screen.findByText(/from the new file/);
    expect(screen.queryByText(/from the old file/)).not.toBeInTheDocument();
  });

  it('keeps a traceback whole when it straddles two deltas', async () => {
    API.getLogFile.mockResolvedValue({
      content:
        '2026-08-21 10:00:00,000 ERROR apps.epg refresh failed\n' +
        'Traceback (most recent call last):\n' +
        '  File "/app/x.py", line 1, in run\n',
      truncated: false,
      cursor: '99-80',
      reset: true,
    });
    renderPage();
    await screen.findByText(/Traceback \(most recent call last\)/);

    // The unindented exception line lands in the next poll. Classified on its
    // own it reads as a standalone line and detaches from its traceback.
    API.getLogFile.mockResolvedValue({
      content: 'ValueError: bad m3u\n',
      truncated: false,
      cursor: '99-100',
      reset: false,
    });
    await act(async () => {
      fireEvent.click(screen.getByText('Refresh'));
    });
    await screen.findByText(/ValueError: bad m3u/);

    // Structure, not mere presence: the tail must render inside the record's
    // own block, which only happens if the delta resumed inside the traceback.
    const block = screen
      .getByText(/Traceback \(most recent call last\)/)
      .closest('div');
    expect(block.textContent).toContain('ValueError: bad m3u');
  });

  it('does not append the same delta twice when two loads overlap', async () => {
    API.getLogFile.mockResolvedValue({
      content: '2026-08-21 10:00:00,000 INFO core.tasks base line\n',
      truncated: false,
      cursor: '7-50',
      reset: true,
    });
    renderPage();
    await screen.findByText(/base line/);

    // Both polls are issued against cursor 7-50 and return the same delta.
    let release;
    const gate = new Promise((resolve) => {
      release = resolve;
    });
    const delta = {
      content: '2026-08-21 10:00:01,000 INFO core.tasks second line\n',
      truncated: false,
      cursor: '7-100',
      reset: false,
    };
    API.getLogFile.mockImplementation(async () => {
      await gate;
      return delta;
    });

    const refresh = screen.getByText('Refresh');
    await act(async () => {
      fireEvent.click(refresh);
      fireEvent.click(refresh);
      release();
      await Promise.resolve();
    });
    await screen.findByText(/second line/);

    expect(screen.getAllByText(/second line/)).toHaveLength(1);
  });

  // jsdom performs no layout, so the scroll box reports zero for every metric.
  // Stub the geometry and let scrollTop behave like a real settable property.
  const stubViewport = (el, { scrollHeight, clientHeight }) => {
    let top = 0;
    Object.defineProperty(el, 'scrollHeight', {
      configurable: true,
      get: () => scrollHeight,
    });
    Object.defineProperty(el, 'clientHeight', {
      configurable: true,
      get: () => clientHeight,
    });
    Object.defineProperty(el, 'scrollTop', {
      configurable: true,
      get: () => top,
      set: (v) => {
        top = v;
      },
    });
    return el;
  };

  const findViewport = () => {
    let el = screen.getByText(/Scanning disk/).parentElement;
    while (el && getComputedStyle(el).overflow !== 'auto') {
      el = el.parentElement;
    }
    return el;
  };

  it('opens at the live edge instead of the oldest retained line', async () => {
    renderPage();
    await screen.findByText(/Scanning disk/);
    const viewport = stubViewport(findViewport(), {
      scrollHeight: 5000,
      clientHeight: 500,
    });

    API.getLogFile.mockResolvedValue({
      content:
        'Info|DiskScanService|Scanning disk\nInfo|core.tasks|later line\n',
      truncated: false,
    });
    await act(async () => {
      fireEvent.click(screen.getByText('Refresh'));
    });

    expect(viewport.scrollTop).toBe(5000);
  });

  it('keeps following the tail across a refresh', async () => {
    renderPage();
    await screen.findByText(/Scanning disk/);
    const viewport = stubViewport(findViewport(), {
      scrollHeight: 5000,
      clientHeight: 500,
    });
    // The reader is sitting at the bottom, watching.
    viewport.scrollTop = 4500;
    fireEvent.scroll(viewport);

    API.getLogFile.mockResolvedValue({
      content:
        'Info|DiskScanService|Scanning disk\nInfo|core.tasks|fresh line\n',
      truncated: false,
    });
    await act(async () => {
      fireEvent.click(screen.getByText('Refresh'));
    });

    await screen.findByText(/fresh line/);
    expect(viewport.scrollTop).toBe(5000);
  });

  it('leaves a reader who scrolled back where they were', async () => {
    renderPage();
    await screen.findByText(/Scanning disk/);
    const viewport = stubViewport(findViewport(), {
      scrollHeight: 5000,
      clientHeight: 500,
    });
    // Scrolled up to read history: a refresh must not yank them to the bottom.
    viewport.scrollTop = 1200;
    fireEvent.scroll(viewport);

    API.getLogFile.mockResolvedValue({
      content:
        'Info|DiskScanService|Scanning disk\nInfo|core.tasks|fresh line\n',
      truncated: false,
    });
    await act(async () => {
      fireEvent.click(screen.getByText('Refresh'));
    });

    await screen.findByText(/fresh line/);
    expect(viewport.scrollTop).toBe(1200);
  });
});
