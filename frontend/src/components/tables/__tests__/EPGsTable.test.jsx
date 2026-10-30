import { MantineProvider } from '@mantine/core';
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
  act,
} from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import EPGsTable from '../EPGsTable';
import useEPGsStore from '../../../store/epgs';
import useWarningsStore from '../../../store/warnings';
import * as actions from '../../../utils/tables/EPGsTableUtils';
import { showNotification } from '../../../utils/notificationUtils';
import useScreenshotMode from '../../../store/useScreenshotMode.js';

vi.mock('../../../store/epgs', () => ({ default: vi.fn() }));
vi.mock('../../../store/warnings', () => ({ default: vi.fn() }));
vi.mock('../../../utils/dateTimeUtils', () => ({
  format: (value) => `formatted:${value}`,
  useDateTimeFormat: () => ({ fullDateTimeFormat: 'YYYY-MM-DD HH:mm' }),
}));
vi.mock('../../../utils/notificationUtils', () => ({
  showNotification: vi.fn(),
}));
vi.mock('../../../utils/tables/EPGsTableUtils', async (original) => ({
  ...(await original()),
  updateEpg: vi.fn().mockResolvedValue(undefined),
  refreshEpg: vi.fn().mockResolvedValue(undefined),
  deleteEpg: vi.fn().mockResolvedValue(undefined),
}));
vi.mock('../../forms/EPG', () => ({
  default: ({ isOpen, epg, onClose }) =>
    isOpen ? (
      <div role="dialog" aria-label="EPG editor">
        {epg?.name || 'New standard EPG'}
        <button onClick={onClose}>Close editor</button>
      </div>
    ) : null,
}));
vi.mock('../../forms/DummyEPG', () => ({
  default: ({ isOpen, epg, onClose }) =>
    isOpen ? (
      <div role="dialog" aria-label="Dummy editor">
        {epg?.name || 'New dummy EPG'}
        <button onClick={onClose}>Close editor</button>
      </div>
    ) : null,
}));
vi.mock('../../ConfirmationDialog', () => ({
  default: ({
    opened,
    title,
    message,
    onConfirm,
    onClose,
    confirmLabel,
    loading,
  }) =>
    opened ? (
      <div role="dialog" aria-label={title}>
        {message}
        <button disabled={loading} onClick={onConfirm}>
          {confirmLabel}
        </button>
        <button onClick={onClose}>Cancel</button>
      </div>
    ) : null,
}));

const source = (overrides = {}) => ({
  id: 1,
  name: 'Guide One',
  source_type: 'xmltv',
  url: 'https://example.invalid/guide.xml',
  is_active: true,
  status: 'success',
  updated_at: null,
  last_message: 'Guide imported',
  ...overrides,
});
let state;
let warnings;
const setup = (sources = [source()], progress = {}) => {
  state = {
    epgs: Object.fromEntries(sources.map((epg) => [epg.id, epg])),
    refreshProgress: progress,
  };
  useEPGsStore.mockImplementation((selector) => selector(state));
};
const show = () =>
  render(
    <MantineProvider>
      <EPGsTable />
    </MantineProvider>
  );
const card = (name = 'Guide One') =>
  within(screen.getByRole('article', { name: `EPG source ${name}` }));

describe('EPG source cards', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    sessionStorage.clear();
    useScreenshotMode.setState({ enabled: false });
    setup();
    warnings = {
      isWarningSuppressed: vi.fn(() => false),
      suppressWarning: vi.fn(),
    };
    useWarningsStore.mockImplementation((selector) => selector(warnings));
  });
  it('places the URL under the name and dims Never like the other subtitles', () => {
    show();
    const name = card().getByText('Guide One');
    const url = card().getByText('https://example.invalid/guide.xml');
    expect(name.parentElement.parentElement).toContainElement(url);
    expect(url).toHaveStyle({ color: 'var(--mantine-color-dimmed)' });
    expect(card().getByText('Never')).toHaveStyle({
      color: 'var(--mantine-color-dimmed)',
    });
    act(() => useScreenshotMode.getState().toggle());
    expect(
      card().queryByText('https://example.invalid/guide.xml')
    ).not.toBeInTheDocument();
    expect(card().getByText('••••••••')).toBeInTheDocument();
  });
  it.each(['idle', 'error'])(
    'does not repeat the missing-source message below Last refresh (%s)',
    (status) => {
      setup([
        source({
          status,
          url: '',
          file_path: '',
          last_message: 'No URL provided and no valid local file exists',
        }),
      ]);
      show();
      expect(
        card().getByText('No URL or local file configured')
      ).toBeInTheDocument();
      expect(
        card().queryByText('No URL provided and no valid local file exists')
      ).not.toBeInTheDocument();
      expect(card().getByText('Never')).toBeInTheDocument();
    }
  );
  it('keeps missing-file errors when the source still has a configured path', () => {
    setup([
      source({
        status: 'error',
        url: '',
        file_path: '/data/missing.xml',
        last_message: 'No URL provided and no valid local file exists',
      }),
    ]);
    show();
    expect(card().getByText('/data/missing.xml')).toBeInTheDocument();
    expect(
      card().getByText('No URL provided and no valid local file exists')
    ).toBeInTheDocument();
  });

  it('places compact errors by the status and keeps full details out of Last refresh', async () => {
    const message =
      'EPG download failed: 403 Client Error: Forbidden for url: https://example.invalid/guide.xml?password=secret';
    setup([source({ status: 'error', last_message: message })], {
      1: { action: 'downloading', progress: 42, status: 'error' },
    });
    show();
    const status = card().getByRole('group', { name: 'Error status' });
    expect(status).toHaveTextContent('EPG download failed');
    expect(
      card().getByText('Last refresh').parentElement
    ).not.toHaveTextContent('EPG download failed');
    expect(card().queryByText(/42%/)).not.toBeInTheDocument();
    fireEvent.mouseEnter(status);
    expect(await screen.findByRole('tooltip')).toHaveTextContent(message);
    act(() => useScreenshotMode.getState().toggle());
    expect(screen.getByRole('tooltip')).not.toHaveTextContent(
      'password=secret'
    );
  });

  it('uses the navigation label for the source overview', () => {
    show();
    expect(screen.getByText('EPG Sources')).toBeInTheDocument();
    expect(screen.queryByText('EPGs')).not.toBeInTheDocument();
  });

  it.each([0, 1234, undefined])(
    'shows saved EPG channels without confusing missing data with zero (%s)',
    (count) => {
      setup([source({ epg_data_count: count })]);
      show();
      expect(card().getByText('EPG channels').parentElement).toHaveTextContent(
        count === undefined ? '—' : String(count)
      );
      expect(actions.refreshEpg).not.toHaveBeenCalled();
    }
  );
  it('uses matching cards and control blocks without a table', () => {
    show();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(card().getByText('XMLTV')).toBeInTheDocument();
    expect(card().getByText('Success')).toBeInTheDocument();
    expect(
      card().getByRole('group', { name: 'Enabled state for Guide One' })
        .className
    ).toBe(
      card().getByRole('group', { name: 'Actions for Guide One' }).className
    );
    expect(
      card()
        .getAllByRole('button')
        .map((button) => button.getAttribute('aria-label'))
    ).toEqual(['Refresh Guide One', 'Edit Guide One', 'Delete Guide One']);
    expect(
      card()
        .getByRole('group', { name: 'Enabled state for Guide One' })
        .textContent.trim()
    ).toBe('');
    const edit = card().getByRole('button', { name: 'Edit Guide One' });
    expect(edit.querySelector('.lucide-square-pen')).not.toBeNull();
    expect(edit.getAttribute('style')).toContain('yellow');
  });
  it('puts disabled sources last, dims them, and sorts names case-insensitively', () => {
    setup([
      source({ name: 'zulu' }),
      source({ id: 2, name: 'Alpha', is_active: false }),
      source({ id: 3, name: 'Bravo' }),
    ]);
    show();
    expect(
      screen
        .getAllByRole('article')
        .map((node) => node.getAttribute('aria-label'))
    ).toEqual(['EPG source Bravo', 'EPG source zulu', 'EPG source Alpha']);
    expect(
      screen.getByRole('article', { name: 'EPG source Alpha' })
    ).toHaveStyle({ opacity: '0.65', filter: 'grayscale(0.75)' });
  });
  it('shows an empty state without search or sorting fields', () => {
    setup([]);
    show();
    expect(screen.getByText('No EPG sources yet.')).toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  });
  it.each(['Standard EPG Source', 'Dummy EPG Source'])(
    'creates %s using its existing editor',
    async (label) => {
      show();
      fireEvent.click(screen.getByRole('button', { name: 'Add EPG' }));
      fireEvent.click(await screen.findByRole('menuitem', { name: label }));
      expect(screen.getByRole('dialog')).toHaveTextContent(
        label.startsWith('Dummy') ? 'New dummy EPG' : 'New standard EPG'
      );
      fireEvent.click(screen.getByRole('button', { name: 'Close editor' }));
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    }
  );
  it.each(['xmltv', 'schedules_direct', 'dummy'])(
    'opens the appropriate editor for %s',
    (source_type) => {
      setup([source({ source_type })]);
      show();
      fireEvent.click(card().getByRole('button', { name: 'Edit Guide One' }));
      expect(
        screen.getByRole('dialog', {
          name: source_type === 'dummy' ? 'Dummy editor' : 'EPG editor',
        })
      ).toHaveTextContent('Guide One');
    }
  );
  it('confirms deletion and preserves cancellation', async () => {
    show();
    fireEvent.click(card().getByRole('button', { name: 'Delete Guide One' }));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(actions.deleteEpg).not.toHaveBeenCalled();
    fireEvent.click(card().getByRole('button', { name: 'Delete Guide One' }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(actions.deleteEpg).toHaveBeenCalledWith(1));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
  it('also masks a Schedules Direct username in its deletion confirmation', () => {
    setup([
      source({ source_type: 'schedules_direct', username: 'ExampleUser' }),
    ]);
    show();
    act(() => useScreenshotMode.getState().toggle());
    fireEvent.click(card().getByRole('button', { name: 'Delete Guide One' }));
    const dialog = within(screen.getByRole('dialog'));
    expect(dialog.queryByText('ExampleUser')).not.toBeInTheDocument();
    expect(dialog.getByText('••••••••')).toBeInTheDocument();
    expect(dialog.getByText(/Username:/)).toBeInTheDocument();
  });
  it('respects a suppressed deletion warning', async () => {
    warnings.isWarningSuppressed.mockReturnValue(true);
    show();
    fireEvent.click(card().getByRole('button', { name: 'Delete Guide One' }));
    await waitFor(() => expect(actions.deleteEpg).toHaveBeenCalledWith(1));
  });
  it('refreshes an enabled source and keeps its initiation message', async () => {
    show();
    fireEvent.click(card().getByRole('button', { name: 'Refresh Guide One' }));
    await waitFor(() =>
      expect(actions.refreshEpg).toHaveBeenCalledWith(1, false)
    );
    expect(showNotification).toHaveBeenCalledWith({
      title: 'EPG refresh initiated',
    });
  });
  it.each([{ is_active: false }, { source_type: 'dummy' }])(
    'preserves refresh restrictions for %j',
    (overrides) => {
      setup([source(overrides)]);
      show();
      expect(
        card().getByRole('button', { name: 'Refresh Guide One' })
      ).toBeDisabled();
    }
  );
  it('toggles only the enabled state', async () => {
    show();
    fireEvent.click(card().getByRole('switch', { name: 'Enable Guide One' }));
    await waitFor(() =>
      expect(actions.updateEpg).toHaveBeenCalledWith(
        { is_active: false },
        source(),
        true
      )
    );
  });
  it('keeps dummy source enable state read-only and its status idle', () => {
    setup([source({ source_type: 'dummy', status: 'error' })]);
    show();
    expect(card().getByRole('switch')).toBeDisabled();
    expect(card().getByText('Idle')).toBeInTheDocument();
    expect(card().queryByText('Guide imported')).not.toBeInTheDocument();
  });
  it.each([null, '2026-10-14T12:00:00Z'])(
    'shows the last refresh date %s',
    (updated_at) => {
      setup([source({ updated_at })]);
      show();
      expect(
        card().getByText(updated_at ? `formatted:${updated_at}` : 'Never')
      ).toBeInTheDocument();
    }
  );
  it.each([
    ['error', 'Upstream failed'],
    ['idle', 'Waiting'],
    ['success', 'Import finished'],
    ['success', null],
  ])('preserves the %s status message %s', (status, last_message) => {
    setup([source({ status, last_message })]);
    show();
    expect(
      card().getByText(last_message || 'EPG data refreshed successfully')
    ).toBeInTheDocument();
  });
  it.each([
    'downloading',
    'extracting',
    'parsing_channels',
    'parsing_programs',
  ])('shows %s progress and counts', (action) => {
    setup([source()], {
      1: { action, progress: 42, speed: 512, processed: 2000, total: 5000 },
    });
    show();
    expect(card().getByText(/42%/)).toBeInTheDocument();
    expect(card().getByText('Speed: 512 KB/s')).toBeInTheDocument();
    expect(card().getByText('2,000 / 5,000')).toBeInTheDocument();
  });
  it('does not render an unknown progress action', () => {
    setup([source()], { 1: { action: 'unknown', progress: 10 } });
    show();
    expect(card().queryByText(/10%/)).not.toBeInTheDocument();
  });
  it('uses the file path without exposing a password fallback', () => {
    setup([
      source({
        url: '',
        file_path: '/data/guide.xml',
        password: 'hidden-secret',
      }),
    ]);
    show();
    expect(card().getByText('/data/guide.xml')).toBeInTheDocument();
    expect(screen.queryByText('hidden-secret')).not.toBeInTheDocument();
  });
  it.each(['tester', ''])(
    'shows Schedules Direct credentials safely (%s)',
    (username) => {
      setup([
        source({
          source_type: 'schedules_direct',
          username,
          password: 'hidden-secret',
        }),
      ]);
      show();
      expect(
        card().getByText(username ? `User: ${username}` : '(credentials set)')
      ).toBeInTheDocument();
      act(() => useScreenshotMode.getState().toggle());
      expect(
        card().getByText(username ? '••••••••' : '(credentials set)')
      ).toBeInTheDocument();
      if (username)
        expect(card().queryByText(`User: ${username}`)).not.toBeInTheDocument();
      expect(screen.queryByText('hidden-secret')).not.toBeInTheDocument();
    }
  );
  it('requires confirmation for an early Schedules Direct refresh', async () => {
    setup([
      source({
        source_type: 'schedules_direct',
        updated_at: new Date().toISOString(),
      }),
    ]);
    show();
    fireEvent.click(card().getByRole('button', { name: 'Refresh Guide One' }));
    expect(actions.refreshEpg).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(actions.refreshEpg).not.toHaveBeenCalled();
    fireEvent.click(card().getByRole('button', { name: 'Refresh Guide One' }));
    fireEvent.click(screen.getByRole('button', { name: 'Refresh Anyway' }));
    await waitFor(() =>
      expect(actions.refreshEpg).toHaveBeenCalledWith(1, true)
    );
  });
  it.each([null, new Date(Date.now() - 3 * 3600000).toISOString()])(
    'allows an ordinary Schedules Direct refresh (%s)',
    async (updated_at) => {
      setup([source({ source_type: 'schedules_direct', updated_at })]);
      show();
      fireEvent.click(
        card().getByRole('button', { name: 'Refresh Guide One' })
      );
      await waitFor(() =>
        expect(actions.refreshEpg).toHaveBeenCalledWith(1, false)
      );
    }
  );
  it('retains and persists source type filters', async () => {
    setup([source(), source({ id: 2, name: 'Dummy', source_type: 'dummy' })]);
    show();
    fireEvent.click(screen.getByRole('button', { name: 'Filter EPG types' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: 'XMLTV' }));
    expect(screen.getAllByRole('article')).toHaveLength(1);
    expect(JSON.parse(sessionStorage.getItem('epg-table-type-filter'))).toEqual(
      ['schedules_direct', 'dummy']
    );
  });
  it('resets a saved source type filter', async () => {
    sessionStorage.setItem('epg-table-type-filter', JSON.stringify(['dummy']));
    setup([source(), source({ id: 2, name: 'Dummy', source_type: 'dummy' })]);
    show();
    expect(screen.getAllByRole('article')).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Filter EPG types' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: 'Reset' }));
    expect(screen.getAllByRole('article')).toHaveLength(2);
  });
});
