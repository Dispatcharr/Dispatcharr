import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import M3UTable from '../M3UsTable';
import usePlaylistsStore from '../../../store/playlists';
import useWarningsStore from '../../../store/warnings';
import * as actions from '../../../utils/tables/M3UsTableUtils.js';

vi.mock('../../../store/playlists', () => ({ default: vi.fn() }));
vi.mock('../../../store/warnings', () => ({ default: vi.fn() }));
vi.mock('../../../utils/dateTimeUtils.js', () => ({
  useDateTimeFormat: () => ({
    fullDateFormat: 'YYYY-MM-DD',
    fullDateTimeFormat: 'YYYY-MM-DD HH:mm',
  }),
  format: (value) => 'formatted:' + value,
  diff: () => 30,
  getNow: () => '2026-10-14T12:00:00Z',
  formatDuration: (value) => String(value) + 's',
}));
vi.mock('../../../utils/tables/M3UsTableUtils.js', async (importOriginal) => ({
  ...(await importOriginal()),
  deletePlaylist: vi.fn().mockResolvedValue(undefined),
  getPlaylistAutoCreatedChannelsCount: vi
    .fn()
    .mockResolvedValue({ count: 0, sample_names: [] }),
  refreshLivePlaylist: vi.fn().mockResolvedValue(undefined),
  refreshVODContent: vi.fn().mockResolvedValue(undefined),
  updatePlaylist: vi.fn().mockResolvedValue(undefined),
}));
vi.mock('../../forms/M3U', () => ({
  default: ({ isOpen, m3uAccount, onClose, onSaved, playlistCreated }) =>
    isOpen ? (
      <div role="dialog" aria-label="Account editor">
        <span>{m3uAccount?.name || 'New account'}</span>
        <span>{playlistCreated ? 'Initial setup' : 'Edit setup'}</span>
        <button onClick={() => onClose(null)}>Close editor</button>
        <button onClick={() => onClose({ id: 99, name: 'Created account' })}>
          Create account
        </button>
        <button
          onClick={() => onSaved({ ...m3uAccount, name: 'Edited account' })}
        >
          Save account
        </button>
        <button
          onClick={() =>
            onSaved({
              ...m3uAccount,
              account_type: 'STD',
              setup_step: 'categories',
            })
          }
        >
          Save as Standard
        </button>
      </div>
    ) : null,
}));
vi.mock('../../ServerGroupsManagerModal', () => ({
  default: ({ isOpen, onClose }) =>
    isOpen ? (
      <div role="dialog" aria-label="Server groups">
        <button onClick={onClose}>Close server groups</button>
      </div>
    ) : null,
}));
vi.mock('../../forms/M3USetup.jsx', () => ({
  default: ({ account, onClose }) => (
    <div role="dialog" aria-label="Account setup">
      <span>{account.name}</span>
      <span>Step: {account.setup_step}</span>
      <button onClick={onClose}>Close setup</button>
    </div>
  ),
}));
vi.mock('../../../components/ConfirmationDialog', () => ({
  default: ({
    opened,
    message,
    onClose,
    onConfirm,
    loading,
    onSuppressChange,
  }) =>
    opened ? (
      <div role="dialog" aria-label="Delete account">
        {message}
        <button onClick={onClose} disabled={loading}>
          Cancel deletion
        </button>
        <button onClick={onConfirm} disabled={loading}>
          Confirm deletion
        </button>
        <button onClick={() => onSuppressChange('delete-m3u', true)}>
          Suppress warning
        </button>
      </div>
    ) : null,
}));

const account = (values = {}) => ({
  id: 1,
  name: 'Provider One',
  account_type: 'XC',
  server_url: 'https://example.invalid',
  status: 'success',
  last_message: 'Loaded streams',
  max_streams: 2,
  profiles: [],
  is_active: true,
  locked: false,
  enable_vod: true,
  updated_at: '2026-10-14T12:00:00Z',
  earliest_expiration: null,
  custom_properties: {},
  ...values,
});

const setup = (values = {}) => {
  const state = {
    playlists: [account()],
    refreshProgress: {},
    editPlaylistId: null,
    setRefreshProgress: vi.fn(),
    setEditPlaylistId: vi.fn(),
    ...values,
  };
  usePlaylistsStore.mockImplementation((selector) => selector(state));
  const warnings = {
    isWarningSuppressed: vi.fn(() => false),
    suppressWarning: vi.fn(),
  };
  useWarningsStore.mockImplementation((selector) => selector(warnings));
  return { state, warnings };
};
const show = () =>
  render(
    <MantineProvider>
      <M3UTable />
    </MantineProvider>
  );
const card = (name = 'Provider One') =>
  within(screen.getByRole('article', { name: 'M3U account ' + name }));
describe('M3U account cards', () => {
  it.each(['URL', 'File'])(
    'uses Streams for %s counts, refresh history and actions',
    async (source) => {
      setup({
        playlists: [
          account({
            account_type: 'STD',
            enable_vod: false,
            server_url:
              source === 'URL' ? 'https://example.invalid/playlist.m3u' : '',
            file_path: source === 'File' ? '/data/playlist.m3u' : '',
            custom_properties: {
              live_catalog_counts: { provider_total: 100, selected_total: 20 },
              refresh_timings: {
                live_completed_at: 'live-date',
                live_seconds: 5.5,
              },
            },
          }),
        ],
      });
      show();
      expect(card().getByText('Streams: 100 / 20')).toBeInTheDocument();
      expect(
        card().getByText('Streams: formatted:live-date · 5.5s')
      ).toBeInTheDocument();
      expect(
        card().queryByText(/Live TV|Movies:|Series:|VOD:/)
      ).not.toBeInTheDocument();
      const refresh = card().getByRole('button', {
        name: 'Refresh Streams for Provider One',
      });
      fireEvent.mouseEnter(refresh);
      expect(await screen.findByRole('tooltip')).toHaveTextContent(
        'Refresh Streams'
      );
      fireEvent.mouseLeave(refresh);
      fireEvent.click(refresh);
      await waitFor(() =>
        expect(actions.refreshLivePlaylist).toHaveBeenCalledExactlyOnceWith(1)
      );
      expect(actions.refreshVODContent).not.toHaveBeenCalled();
    }
  );

  it('labels standard playlist progress as Streams without changing refresh state', () => {
    const { state } = setup({
      playlists: [account({ account_type: 'STD', enable_vod: false })],
      refreshProgress: { 1: { action: 'parsing', progress: 40 } },
    });
    show();
    expect(card().getByText('Refreshing Streams…')).toBeInTheDocument();
    expect(card().queryByText(/Live TV/)).not.toBeInTheDocument();
    expect(state.setRefreshProgress).not.toHaveBeenCalled();
    expect(actions.refreshLivePlaylist).not.toHaveBeenCalled();
  });
  it.each([true, 1, '1'])(
    'shows Trial from the default profile (%s)',
    (is_trial) => {
      setup({
        playlists: [
          account({
            profiles: [
              {
                is_default: true,
                custom_properties: { user_info: { is_trial } },
              },
            ],
          }),
        ],
      });
      show();
      expect(card().getByText('Trial')).toBeInTheDocument();
    }
  );

  it('does not mark the account as a trial because an additional connection is a trial', () => {
    setup({
      playlists: [
        account({
          profiles: [
            {
              is_default: true,
              custom_properties: { user_info: { is_trial: '0' } },
            },
            {
              is_default: false,
              custom_properties: { user_info: { is_trial: '1' } },
            },
          ],
        }),
      ],
    });
    show();
    expect(card().queryByText('Trial')).not.toBeInTheDocument();
  });
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    sessionStorage.clear();
    actions.deletePlaylist.mockResolvedValue(undefined);
    actions.refreshLivePlaylist.mockResolvedValue(undefined);
    actions.refreshVODContent.mockResolvedValue(undefined);
    actions.updatePlaylist.mockResolvedValue(undefined);
    actions.getPlaylistAutoCreatedChannelsCount.mockResolvedValue({
      count: 0,
      sample_names: [],
    });
    setup();
  });

  it('uses an account card instead of a horizontally scrolling table', () => {
    show();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(card().getByText('Provider One')).toBeInTheDocument();
    expect(card().getByText('XC')).toBeInTheDocument();
    expect(card().getByText('Success')).toBeInTheDocument();
    expect(card().getByText('https://example.invalid')).toBeInTheDocument();
  });

  it('keeps enabled and actions in matching control blocks', () => {
    show();
    const enabled = card().getByRole('group', {
      name: 'Enabled state for Provider One',
    });
    const actionsBlock = card().getByRole('group', {
      name: 'Actions for Provider One',
    });
    expect(enabled.className).toBe(actionsBlock.className);
    expect(within(enabled).getByRole('switch')).toBeChecked();
    expect(enabled.textContent.trim()).toBe('');
    expect(within(actionsBlock).getAllByRole('button')).toHaveLength(4);
    const edit = within(actionsBlock).getByRole('button', {
      name: 'Edit Provider One',
    });
    expect(edit.querySelector('.lucide-square-pen')).not.toBeNull();
    expect(edit.getAttribute('style')).toContain('yellow');
  });

  it('excludes locked system accounts', () => {
    setup({ playlists: [account({ locked: true })] });
    show();
    expect(screen.queryByRole('article')).not.toBeInTheDocument();
    expect(screen.getByText('No M3U accounts yet.')).toBeInTheDocument();
  });

  it('shows active accounts first and sorts names case-insensitively', () => {
    setup({
      playlists: [
        account({ id: 2, name: 'Alpha', is_active: false }),
        account({ id: 3, name: 'zulu' }),
        account({ name: 'Bravo' }),
      ],
    });
    show();
    expect(
      screen
        .getAllByRole('article')
        .map((node) => node.getAttribute('aria-label'))
    ).toEqual(['M3U account Bravo', 'M3U account zulu', 'M3U account Alpha']);
  });

  it('does not add search or sort controls', () => {
    show();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  });

  it('retains M3U/XC type filters', async () => {
    setup({
      playlists: [
        account(),
        account({ id: 2, name: 'File account', account_type: 'STD' }),
      ],
    });
    show();
    fireEvent.click(
      screen.getByRole('button', { name: 'Filter account types' })
    );
    fireEvent.click(await screen.findByRole('menuitem', { name: 'XC' }));
    expect(screen.getAllByRole('article')).toHaveLength(1);
    expect(card('File account').getByText('M3U')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Reset'));
    expect(screen.getAllByRole('article')).toHaveLength(2);
  });

  it('opens create, edit and server group dialogs', () => {
    show();
    fireEvent.click(screen.getByRole('button', { name: 'Add M3U' }));
    expect(
      screen.getByRole('dialog', { name: 'Account editor' })
    ).toHaveTextContent('New account');
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }));
    expect(
      screen.getByRole('dialog', { name: 'Account setup' })
    ).toHaveTextContent('Created account');
    fireEvent.click(screen.getByRole('button', { name: 'Close setup' }));
    fireEvent.click(card().getByRole('button', { name: 'Edit Provider One' }));
    expect(
      screen.getByRole('dialog', { name: 'Account editor' })
    ).toHaveTextContent('Provider One');
    fireEvent.click(screen.getByRole('button', { name: 'Close editor' }));
    fireEvent.click(screen.getByRole('button', { name: 'Server Groups' }));
    expect(
      screen.getByRole('dialog', { name: 'Server groups' })
    ).toBeInTheDocument();
  });

  it('still opens account editors requested by notifications', () => {
    const { state } = setup({ editPlaylistId: 1 });
    show();
    expect(
      screen.getByRole('dialog', { name: 'Account editor' })
    ).toHaveTextContent('Provider One');
    expect(state.setEditPlaylistId).toHaveBeenCalledWith(null);
  });

  it('resumes unfinished setup without reopening account creation', () => {
    setup({ playlists: [account({ setup_step: 'categories' })] });
    show();
    expect(
      screen.queryByRole('button', { name: 'Resume setup' })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Edit Provider One' })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Refresh Live TV for Provider One' })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Refresh VOD for Provider One' })
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', { name: 'Continue setup for Provider One' })
    );
    expect(
      screen.getByRole('dialog', { name: 'Account setup' })
    ).toHaveTextContent('Provider One');
    expect(
      screen.queryByRole('dialog', { name: 'Account editor' })
    ).not.toBeInTheDocument();
  });

  it.each(['account', 'content', 'epg', 'categories'])(
    'resumes persisted %s setup through Continue setup, including after closing',
    (setup_step) => {
      setup({ playlists: [account({ setup_step })] });
      show();
      fireEvent.click(
        screen.getByRole('button', { name: 'Continue setup for Provider One' })
      );
      fireEvent.click(screen.getByRole('button', { name: 'Close setup' }));
      fireEvent.click(
        screen.getByRole('button', { name: 'Continue setup for Provider One' })
      );
      expect(
        screen.getByRole('dialog', { name: 'Account setup' })
      ).toHaveTextContent('Provider One');
      expect(
        screen.getByRole('dialog', { name: 'Account setup' })
      ).toHaveTextContent(`Step: ${setup_step}`);
      expect(
        screen.queryByRole('dialog', { name: 'Account editor' })
      ).not.toBeInTheDocument();
    }
  );

  it('does not start setup after saving a completed account', () => {
    show();
    fireEvent.click(card().getByRole('button', { name: 'Edit Provider One' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save account' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('reactivates disabled accounts using a toggle-only patch', async () => {
    const disabled = account({ is_active: false });
    setup({ playlists: [disabled] });
    show();
    expect(screen.getByRole('article')).toHaveStyle({ opacity: '0.65' });
    fireEvent.click(
      card().getByRole('switch', { name: 'Enable Provider One' })
    );
    await waitFor(() =>
      expect(actions.updatePlaylist).toHaveBeenCalledWith(
        { is_active: true },
        disabled,
        true
      )
    );
  });

  it('keeps Live TV and VOD refresh actions independent', async () => {
    const { state } = setup();
    show();
    fireEvent.click(
      card().getByRole('button', { name: 'Refresh Live TV for Provider One' })
    );
    await waitFor(() =>
      expect(actions.refreshLivePlaylist).toHaveBeenCalledWith(1)
    );
    expect(state.setRefreshProgress).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ action: 'initializing', progress: 0 })
    );
    fireEvent.click(
      card().getByRole('button', { name: 'Refresh VOD for Provider One' })
    );
    await waitFor(() =>
      expect(actions.refreshVODContent).toHaveBeenCalledWith(1)
    );
    expect(state.setRefreshProgress).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ action: 'vod_refresh' })
    );
  });

  it('does not refresh disabled accounts or disabled VOD imports', () => {
    setup({ playlists: [account({ is_active: false })] });
    const view = show();
    expect(
      card().getByRole('button', { name: 'Refresh Live TV for Provider One' })
    ).toBeDisabled();
    expect(
      card().getByRole('button', { name: 'Refresh VOD for Provider One' })
    ).toBeDisabled();
    view.unmount();
    setup({ playlists: [account({ enable_vod: false })] });
    show();
    expect(
      card().getByRole('button', { name: 'Refresh Live TV for Provider One' })
    ).toBeEnabled();
    expect(
      card().getByRole('button', { name: 'Refresh VOD for Provider One' })
    ).toBeDisabled();
  });

  it('does not offer VOD refresh for standard M3U accounts', () => {
    setup({
      playlists: [
        account({
          account_type: 'STD',
          file_path: '/data/test.m3u',
          server_url: null,
        }),
      ],
    });
    show();
    expect(card().getByText('/data/test.m3u')).toBeInTheDocument();
    expect(
      card().queryByRole('button', { name: /Refresh VOD/ })
    ).not.toBeInTheDocument();
  });

  it.each(['live', 'vod'])(
    'shows a failed %s refresh request in account progress',
    async (kind) => {
      const { state } = setup();
      const action =
        kind === 'live'
          ? actions.refreshLivePlaylist
          : actions.refreshVODContent;
      action.mockRejectedValueOnce(new Error('Unavailable'));
      show();
      fireEvent.click(
        card().getByRole('button', {
          name:
            kind === 'live'
              ? 'Refresh Live TV for Provider One'
              : 'Refresh VOD for Provider One',
        })
      );
      await waitFor(() =>
        expect(state.setRefreshProgress).toHaveBeenLastCalledWith(
          1,
          expect.objectContaining({
            action: kind === 'vod' ? 'vod_refresh' : 'error',
            status: 'error',
          })
        )
      );
    }
  );

  it('preserves separate counts, durations and completion timestamps', () => {
    setup({
      playlists: [
        account({
          custom_properties: {
            live_catalog_counts: { provider_total: 100, selected_total: 20 },
            vod_catalog_counts: {
              movies: { provider_total: 300, selected_total: 50 },
              series: { provider_total: 200, selected_total: 30 },
            },
            refresh_timings: {
              live_seconds: 5.5,
              vod_seconds: 81,
              live_completed_at: 'live-date',
              vod_completed_at: 'vod-date',
            },
          },
        }),
      ],
    });
    show();
    for (const line of [
      'Live TV: 100 / 20',
      'Movies: 300 / 50',
      'Series: 200 / 30',
      'Live TV: formatted:live-date · 5.5s',
      'VOD: formatted:vod-date · 1m 21s',
    ]) {
      expect(card().getByText(line)).toBeInTheDocument();
    }
  });

  it('keeps the last VOD refresh visible after scanning is disabled', () => {
    setup({
      playlists: [
        account({
          enable_vod: false,
          custom_properties: {
            refresh_timings: { vod_seconds: 60, vod_completed_at: 'last-vod' },
          },
        }),
      ],
    });
    show();
    expect(
      card().getByText('VOD: formatted:last-vod · 1m 0s')
    ).toBeInTheDocument();
  });

  it.each([
    [null, '—'],
    [-1, '—'],
    ['bad', '—'],
    [0, '0s'],
    [3601, '1h 0m'],
  ])('formats refresh duration %s as %s', (seconds, expected) => {
    setup({
      playlists: [
        account({
          custom_properties: { refresh_timings: { live_seconds: seconds } },
        }),
      ],
    });
    show();
    expect(
      card().getByText(
        seconds == null
          ? 'Live TV: formatted:2026-10-14T12:00:00Z'
          : 'Live TV: formatted:2026-10-14T12:00:00Z · ' + expected
      )
    ).toBeInTheDocument();
  });

  it.each(['downloading', 'vod_refresh'])(
    'replaces only the refreshing kind’s completed summary (%s)',
    (action) => {
      setup({
        refreshProgress: {
          1: { action, progress: 50, speed: 1024 },
        },
      });
      show();
      const vod = action === 'vod_refresh';
      expect(
        card().getByText(vod ? 'Refreshing VOD…' : 'Refreshing Live TV…')
      ).toBeInTheDocument();
      expect(
        card().queryByText(
          vod ? 'VOD: Never' : 'Live TV: formatted:2026-10-14T12:00:00Z'
        )
      ).not.toBeInTheDocument();
      expect(
        card().getByText(
          vod ? 'Live TV: formatted:2026-10-14T12:00:00Z' : 'VOD: Never'
        )
      ).toBeInTheDocument();
      expect(card().queryByText('50%')).not.toBeInTheDocument();
    }
  );

  it('keeps upstream errors by the status and auto-sync warning details in its tooltip', async () => {
    setup({
      playlists: [
        account({
          status: 'error',
          last_message: 'Provider unavailable',
          custom_properties: {
            live_auto_sync_result: {
              status: 'error',
              error: 'Sync unavailable',
            },
          },
        }),
      ],
    });
    show();
    expect(card().getByText('Provider unavailable')).toBeInTheDocument();
    const status = card().getByRole('group', { name: 'Error status' });
    expect(status).toHaveTextContent('Provider unavailable');
    expect(
      card().getByText('Last refresh').parentElement
    ).not.toHaveTextContent('Provider unavailable');
    expect(
      card().queryByText('Auto-sync failed: Sync unavailable')
    ).not.toBeInTheDocument();
    fireEvent.mouseEnter(status);
    expect(await screen.findByRole('tooltip')).toHaveTextContent(
      'Auto-sync failed: Sync unavailable'
    );
  });

  it('shows a compact warning by the successful status without expanding Last refresh', async () => {
    setup({
      playlists: [
        account({
          custom_properties: { live_auto_sync_result: { channels_failed: 3 } },
        }),
      ],
    });
    show();
    const status = card().getByRole('group', { name: 'Success status' });
    expect(status).toHaveTextContent('Auto-sync');
    expect(
      card().getByText('Last refresh').parentElement
    ).not.toHaveTextContent('Auto-sync');
    fireEvent.mouseEnter(status);
    expect(await screen.findByRole('tooltip')).toHaveTextContent(
      '3 channel(s) failed'
    );
  });

  it('still shows Live refresh running when only its download phase is complete', () => {
    setup({ refreshProgress: { 1: { action: 'downloading', progress: 100 } } });
    show();
    expect(card().getByText('Refreshing Live TV…')).toBeInTheDocument();
    expect(
      card().queryByText('Live TV: formatted:2026-10-14T12:00:00Z')
    ).not.toBeInTheDocument();
  });

  it('shows refresh-start failures by the status even before account data is reloaded', () => {
    setup({
      refreshProgress: {
        1: {
          action: 'error',
          progress: 0,
          status: 'error',
          error: 'Failed to start refresh task',
        },
      },
    });
    show();
    expect(
      card().getByRole('group', { name: 'Error status' })
    ).toHaveTextContent('Failed to start refresh task');
    expect(
      card().getByText('Last refresh').parentElement
    ).not.toHaveTextContent('Failed to start refresh task');
  });

  it('shows capacity across active profiles and expiry', () => {
    setup({
      playlists: [
        account({
          earliest_expiration: '2026-11-01',
          profiles: [
            { name: 'A', is_active: true, max_streams: 2 },
            { name: 'B', is_active: true, max_streams: 3 },
            { name: 'C', is_active: false, max_streams: 100 },
          ],
        }),
      ],
    });
    show();
    expect(card().getByText('5')).toBeInTheDocument();
    expect(card().getByText('30d left')).toBeInTheDocument();
    expect(card().getByText('5').closest('.mantine-Badge-root')).not.toBeNull();
    expect(
      card().getByText('30d left').closest('.mantine-Badge-root')
    ).not.toBeNull();
  });

  it('warns about auto-created channels before deleting an account', async () => {
    actions.getPlaylistAutoCreatedChannelsCount.mockResolvedValueOnce({
      count: 3,
      sample_names: [],
    });
    show();
    fireEvent.click(
      card().getByRole('button', { name: 'Delete Provider One' })
    );
    const dialog = await screen.findByRole('dialog', {
      name: 'Delete account',
    });
    expect(dialog).toHaveTextContent('3 auto-synced channels');
    expect(actions.deletePlaylist).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm deletion' }));
    await waitFor(() => expect(actions.deletePlaylist).toHaveBeenCalledWith(1));
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    );
  });

  it('warns when the channel count cannot be retrieved and supports cancellation', async () => {
    actions.getPlaylistAutoCreatedChannelsCount.mockRejectedValueOnce(
      new Error('Unavailable')
    );
    show();
    fireEvent.click(
      card().getByRole('button', { name: 'Delete Provider One' })
    );
    const dialog = await screen.findByRole('dialog', {
      name: 'Delete account',
    });
    expect(dialog).toHaveTextContent('count is unavailable');
    fireEvent.click(screen.getByRole('button', { name: 'Cancel deletion' }));
    expect(actions.deletePlaylist).not.toHaveBeenCalled();
  });

  it('only skips suppressed deletion warnings when there are no auto-created channels', async () => {
    const { warnings } = setup();
    warnings.isWarningSuppressed.mockReturnValue(true);
    show();
    fireEvent.click(
      card().getByRole('button', { name: 'Delete Provider One' })
    );
    await waitFor(() => expect(actions.deletePlaylist).toHaveBeenCalledWith(1));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
