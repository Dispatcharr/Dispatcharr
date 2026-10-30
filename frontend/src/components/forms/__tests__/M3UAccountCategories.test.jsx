import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { StrictMode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import M3UAccountCategories from '../M3UAccountCategories.jsx';
import API from '../../../api.js';
import useVODStore from '../../../store/useVODStore';
import { showNotification } from '../../../utils/notificationUtils.js';

const mocks = vi.hoisted(() => ({
  fetchChannelGroups: vi.fn(),
  channelGroups: {},
}));
vi.mock('../../../api.js', () => ({
  default: {
    getPlaylist: vi.fn(),
    getVODCategories: vi.fn(),
  },
}));
vi.mock('../../../store/channels', () => ({
  default: Object.assign((selector) => selector(mocks), {
    getState: () => mocks,
  }),
}));
vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
  hideNotification: vi.fn(),
}));

const account = {
  id: 7,
  account_type: 'XC',
  enable_vod: true,
  channel_groups: [
    { channel_group: 1, enabled: true },
    { channel_group: 2, enabled: false },
  ],
  custom_properties: {
    live_catalog_counts: { provider_total: 20, selected_total: 8 },
    vod_catalog_counts: {
      movies: { provider_total: 40, selected_total: 12 },
      series: { provider_total: 60, selected_total: 16 },
    },
  },
  category_selection_counts: {
    live: { selected: 1, total: 2 },
    movie: { selected: 1, total: 2 },
    series: { selected: 1, total: 1 },
  },
};
const cached = {
  10: {
    id: 10,
    category_type: 'movie',
    m3u_accounts: [
      { m3u_account: 7, enabled: true },
      { m3u_account: 99, enabled: false },
    ],
  },
  11: {
    id: 11,
    category_type: 'movie',
    m3u_accounts: [{ m3u_account: 7, enabled: false }],
  },
  12: {
    id: 12,
    category_type: 'series',
    m3u_accounts: [{ m3u_account: 7, enabled: true }],
  },
};
const show = (props = {}) =>
  render(
    <MantineProvider>
      <M3UAccountCategories account={account} onEdit={vi.fn()} {...props} />
    </MantineProvider>
  );

describe('immediate saved category selection', () => {
  it.each(['URL', 'File'])(
    'labels %s playlist categories as Streams',
    (source) => {
      show({
        account: {
          ...account,
          account_type: 'STD',
          server_url:
            source === 'URL' ? 'https://example.invalid/playlist.m3u' : '',
          file_path: source === 'File' ? '/data/playlist.m3u' : '',
        },
      });
      expect(
        screen.getByRole('article', { name: 'Streams categories' })
      ).toHaveTextContent('Provider / imported streams');
      expect(
        screen.queryByText(/Live TV|Movies|Series/)
      ).not.toBeInTheDocument();
      expect(mocks.fetchChannelGroups).not.toHaveBeenCalled();
      expect(API.getVODCategories).not.toHaveBeenCalled();
    }
  );
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.channelGroups = { 1: { id: 1 }, 2: { id: 2 } };
    mocks.fetchChannelGroups.mockResolvedValue(undefined);
    API.getVODCategories.mockReset();
    useVODStore.setState({
      categories: cached,
      categoriesLoaded: true,
      categoriesLoading: false,
      categoriesError: null,
    });
  });

  it('shows account selection counts synchronously without a catalog request or hint', () => {
    show();
    expect(screen.getAllByText('1 of 2 categories selected')).toHaveLength(2);
    expect(screen.getByText('1 of 1 categories selected')).toBeInTheDocument();
    expect(
      screen.queryByText(/Refresh actions use|Loading category selection/)
    ).toBeNull();
    expect(API.getPlaylist).not.toHaveBeenCalled();
    expect(API.getVODCategories).not.toHaveBeenCalled();
    expect(mocks.fetchChannelGroups).not.toHaveBeenCalled();
  });

  it('shows all counts immediately even when no VOD categories have been loaded', () => {
    useVODStore.setState({ categories: {}, categoriesLoaded: false });
    show();
    expect(screen.getAllByText('1 of 2 categories selected')).toHaveLength(2);
    expect(screen.getByText('1 of 1 categories selected')).toBeInTheDocument();
    expect(screen.queryByText('…')).toBeNull();
    expect(screen.queryByText('0 of 0 categories selected')).toBeNull();
    expect(
      screen.getByRole('button', { name: 'Edit selection' })
    ).toBeEnabled();
    expect(API.getVODCategories).not.toHaveBeenCalled();
    expect(API.getPlaylist).not.toHaveBeenCalled();
    expect(mocks.fetchChannelGroups).not.toHaveBeenCalled();
  });

  it('shows empty saved selections immediately when reopened', () => {
    useVODStore.setState({ categories: {}, categoriesLoaded: false });
    const empty = {
      ...account,
      category_selection_counts: {
        live: { selected: 0, total: 0 },
        movie: { selected: 0, total: 0 },
        series: { selected: 0, total: 0 },
      },
    };
    const first = show({ account: empty });
    expect(screen.getAllByText('0 of 0 categories selected')).toHaveLength(3);
    first.unmount();
    show({ account: empty });
    expect(screen.queryByText('…')).toBeNull();
    expect(API.getVODCategories).not.toHaveBeenCalled();
  });

  it('does not duplicate a VOD request already in progress', () => {
    useVODStore.setState({
      categories: {},
      categoriesLoaded: false,
      categoriesLoading: true,
    });
    show();
    expect(API.getVODCategories).not.toHaveBeenCalled();
    expect(screen.getAllByText('1 of 2 categories selected')).toHaveLength(2);
  });

  it('does not fetch the catalog during Strict Mode effect replay', () => {
    useVODStore.setState({ categories: {}, categoriesLoaded: false });
    render(
      <StrictMode>
        <MantineProvider>
          <M3UAccountCategories account={account} onEdit={vi.fn()} />
        </MantineProvider>
      </StrictMode>
    );
    expect(API.getVODCategories).not.toHaveBeenCalled();
    expect(screen.getByText('1 of 1 categories selected')).toBeInTheDocument();
  });

  it('keeps cached data visible during a background refresh', () => {
    useVODStore.setState({ categoriesLoading: true });
    show();
    expect(screen.getAllByText('1 of 2 categories selected')).toHaveLength(2);
    expect(screen.queryByText('…')).toBeNull();
    expect(API.getVODCategories).not.toHaveBeenCalled();
  });

  it('updates Live and VOD counts from refreshed account data even with a stale category cache', () => {
    const view = show();
    const changed = {
      ...account,
      channel_groups: account.channel_groups.map((row) => ({
        ...row,
        enabled: false,
      })),
      category_selection_counts: {
        ...account.category_selection_counts,
        live: { selected: 0, total: 2 },
        movie: { selected: 0, total: 2 },
      },
    };
    view.rerender(
      <MantineProvider>
        <M3UAccountCategories account={changed} onEdit={vi.fn()} />
      </MantineProvider>
    );
    expect(screen.getAllByText('0 of 2 categories selected')).toHaveLength(2);
    expect(API.getPlaylist).not.toHaveBeenCalled();
    expect(API.getVODCategories).not.toHaveBeenCalled();
  });

  it.each([
    { ...account, account_type: 'STD' },
    { ...account, enable_vod: false },
  ])('only shows Live TV without loading unavailable VOD (%j)', (saved) => {
    useVODStore.setState({ categoriesLoaded: false });
    show({ account: saved });
    expect(screen.getByText('1 of 2 categories selected')).toBeInTheDocument();
    expect(screen.queryByText('Movies')).toBeNull();
    expect(API.getVODCategories).not.toHaveBeenCalled();
  });

  it('loads missing names only when opening the selection editor', async () => {
    mocks.channelGroups = {};
    mocks.fetchChannelGroups.mockImplementation(async () => {
      mocks.channelGroups = { 1: {}, 2: {} };
    });
    const onEdit = vi.fn();
    show({ onEdit });
    expect(mocks.fetchChannelGroups).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Edit selection' }));
    await waitFor(() =>
      expect(onEdit).toHaveBeenCalledExactlyOnceWith(account)
    );
    expect(mocks.fetchChannelGroups).toHaveBeenCalledOnce();
  });

  it('opens the editor immediately with cached names', () => {
    const onEdit = vi.fn();
    show({ onEdit });
    fireEvent.click(screen.getByRole('button', { name: 'Edit selection' }));
    expect(onEdit).toHaveBeenCalledExactlyOnceWith(account);
    expect(mocks.fetchChannelGroups).not.toHaveBeenCalled();
  });

  it('keeps name-loading failures retryable', async () => {
    mocks.channelGroups = {};
    const onEdit = vi.fn();
    show({ onEdit });
    fireEvent.click(screen.getByRole('button', { name: 'Edit selection' }));
    await waitFor(() =>
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({ color: 'red', autoClose: false })
      )
    );
    expect(onEdit).not.toHaveBeenCalled();
    expect(
      screen.getByRole('button', { name: 'Edit selection' })
    ).toBeEnabled();
  });

  it('keeps account counts visible even if the separate VOD catalog is unavailable', () => {
    useVODStore.setState({
      categories: {},
      categoriesLoaded: false,
      categoriesError: 'VOD unavailable',
    });
    show();
    expect(screen.getAllByText('1 of 2 categories selected')).toHaveLength(2);
    expect(screen.getByText('1 of 1 categories selected')).toBeInTheDocument();
    expect(screen.queryByText('…')).toBeNull();
    expect(API.getVODCategories).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull();
  });

  it.each([
    ['Live TV', '20 / 8', 'streams'],
    ['Movies', '40 / 12', 'movies'],
    ['Series', '60 / 16', 'series'],
  ])(
    'shows %s selection and imported counts in a read-only card',
    (label, entries, unit) => {
      show();
      const card = screen.getByRole('article', { name: `${label} categories` });
      expect(within(card).queryByRole('progressbar')).not.toBeInTheDocument();
      expect(
        within(card).getByText(`Provider / imported ${unit}`)
      ).toBeInTheDocument();
      expect(within(card).getByText(entries)).toBeInTheDocument();
      expect(within(card).queryByRole('button')).not.toBeInTheDocument();
    }
  );

  it('places one shared edit action below all three cards', () => {
    const onEdit = vi.fn();
    show({ onEdit });
    const actions = screen.getByRole('region', {
      name: 'Category selection actions',
    });
    const section = screen.getByRole('region', { name: 'Category selection' });
    expect(section).toContainElement(actions);
    expect(section.style.getPropertyValue('--paper-radius')).toBe(
      'var(--mantine-radius-md)'
    );
    for (const card of screen.getAllByRole('article')) {
      expect(section).toContainElement(card);
      expect(card.style.getPropertyValue('--paper-radius')).toBe(
        'var(--mantine-radius-md)'
      );
    }
    expect(within(actions).getByRole('button')).toHaveAttribute(
      'data-variant',
      'filled'
    );
    expect(screen.getAllByText(/of .* categories selected/)[0]).toHaveAttribute(
      'data-size',
      'sm'
    );
    expect(screen.getAllByRole('button')).toHaveLength(1);
    fireEvent.click(
      within(actions).getByRole('button', { name: 'Edit selection' })
    );
    expect(onEdit).toHaveBeenCalledExactlyOnceWith(account);
  });

  it('shows unknown entry counts as unavailable, not as a zero or loading state', () => {
    show({ account: { ...account, custom_properties: {} } });
    expect(screen.getAllByText('— / —')).toHaveLength(3);
    expect(screen.queryByText('0 / 0')).not.toBeInTheDocument();
    expect(API.getPlaylist).not.toHaveBeenCalled();
    expect(API.getVODCategories).not.toHaveBeenCalled();
  });

  it('preserves known zero totals from the last refresh', () => {
    const zero = { provider_total: 0, selected_total: 0 };
    show({
      account: {
        ...account,
        custom_properties: {
          live_catalog_counts: zero,
          vod_catalog_counts: { movies: zero, series: zero },
        },
      },
    });
    expect(screen.getAllByText('0 / 0')).toHaveLength(3);
    expect(screen.queryByText('— / —')).not.toBeInTheDocument();
  });

  it('keeps the common action disabled while missing names are loaded', async () => {
    mocks.channelGroups = {};
    let finish;
    mocks.fetchChannelGroups.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      })
    );
    const onEdit = vi.fn();
    show({ onEdit });
    fireEvent.click(screen.getByRole('button', { name: 'Edit selection' }));
    expect(
      screen.getByRole('button', { name: 'Edit selection' })
    ).toBeDisabled();
    mocks.channelGroups = { 1: {}, 2: {} };
    finish();
    await waitFor(() =>
      expect(onEdit).toHaveBeenCalledExactlyOnceWith(account)
    );
    expect(
      screen.getByRole('button', { name: 'Edit selection' })
    ).toBeEnabled();
  });
});
