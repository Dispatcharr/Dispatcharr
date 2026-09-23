import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from '@testing-library/react';
import SeriesModal from '../SeriesModal';
import useVODStore from '../../store/useVODStore';
import useVideoStore from '../../store/useVideoStore';
import useSettingsStore from '../../store/settings';
import { copyToClipboard } from '../../utils';
import API from '../../api';

// Mock stores
vi.mock('../../store/auth', () => ({
  default: {
    getState: () => ({ accessToken: null }),
  },
}));

vi.mock('../../store/useVODStore', () => ({
  default: vi.fn(),
}));

vi.mock('../../store/useVideoStore', () => ({
  default: vi.fn(),
}));

vi.mock('../../store/settings', () => ({
  default: vi.fn(),
}));
vi.mock('../VODExternalIds.jsx', () => ({
  default: ({ tmdbId, imdbId }) => (
    <div>
      {imdbId && <a href={`https://www.imdb.com/title/${imdbId}`}>IMDb</a>}
      {tmdbId && <a href={`https://www.themoviedb.org/tv/${tmdbId}`}>TMDb</a>}
    </div>
  ),
}));

// Mock utils
vi.mock('../../utils', () => ({
  copyToClipboard: vi.fn(),
}));

// Mock lucide-react icons
vi.mock('lucide-react', () => ({
  ListOrdered: () => <div data-testid="icon-list-ordered" />,
  Play: () => <div data-testid="play-icon" />,
  Copy: () => <div data-testid="copy-icon" />,
  Check: () => <div data-testid="check-icon" />,
  Wrench: () => <div data-testid="wrench-icon" />,
  DatabaseZap: () => <div data-testid="database-zap-icon" />,
  Pencil: () => <div data-testid="pencil-icon" />,
  LockKeyhole: () => <div data-testid="lock-keyhole-icon" />,
  LockKeyholeOpen: () => <div data-testid="lock-keyhole-open-icon" />,
  Search: () => <div data-testid="search-icon" />,
  Save: () => <div data-testid="save-icon" />,
}));

// Mock Mantine components
vi.mock('@mantine/core', async () => {
  const actual = await vi.importActual('@mantine/core');

  return {
    ...actual,
    Modal: ({ opened, onClose, title, children, size }) => {
      if (!opened) return null;
      return (
        <div data-testid="modal" data-title={title} data-size={size}>
          <button onClick={onClose} data-testid="modal-close">
            Close
          </button>
          <div>{children}</div>
        </div>
      );
    },
    Box: ({ children, ...props }) => (
      <div data-testid="box" {...props}>
        {children}
      </div>
    ),
    Button: ({ children, onClick, disabled, ...props }) => (
      <button
        onClick={onClick}
        disabled={disabled}
        data-testid="button"
        {...props}
      >
        {children}
      </button>
    ),
    Flex: ({ children, ...props }) => (
      <div data-testid="flex" {...props}>
        {children}
      </div>
    ),
    Group: ({ children, ...props }) => (
      <div data-testid="group" {...props}>
        {children}
      </div>
    ),
    Image: ({ src, alt, ...props }) => (
      <img src={src} alt={alt} data-testid="image" {...props} />
    ),
    Text: ({ children, ...props }) => (
      <div data-testid="text" {...props}>
        {children}
      </div>
    ),
    Title: ({ children, order, ...props }) => (
      <div data-testid="title" data-order={order} {...props}>
        {children}
      </div>
    ),
    Select: ({
      value,
      onChange,
      data,
      label,
      placeholder,
      disabled,
      ...props
    }) => (
      <div data-testid="select" data-label={label}>
        <select
          value={value || ''}
          onChange={(e) => onChange?.(e.target.value)}
          disabled={disabled}
          {...props}
        >
          <option value="">{placeholder}</option>
          {data?.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
      </div>
    ),
    Badge: ({ children, ...props }) => (
      <a data-testid="badge" {...props}>
        {children}
      </a>
    ),
    Loader: (props) => <div data-testid="loader" {...props} />,
    Alert: ({ children }) => <div>{children}</div>,
    Stack: ({ children, ...props }) => (
      <div data-testid="stack" {...props}>
        {children}
      </div>
    ),
    ActionIcon: ({ children, onClick, disabled, ...props }) => (
      <button
        onClick={onClick}
        disabled={disabled}
        data-testid={props['aria-label'] ? 'source-action-icon' : 'action-icon'}
        {...props}
      >
        {children}
      </button>
    ),
    ScrollArea: ({ children }) => <div>{children}</div>,
    Tooltip: ({ children }) => <>{children}</>,
    Tabs: ({ children, value, onChange, ...props }) => (
      <div data-testid="tabs" data-value={value} {...props}>
        <div
          onClick={(e) => {
            const tab = e.target.closest('[data-tab-value]');
            if (tab) onChange?.(tab.dataset.tabValue);
          }}
        >
          {children}
        </div>
      </div>
    ),
    TabsList: ({ children }) => <div data-testid="tabs-list">{children}</div>,
    TabsTab: ({ children, value }) => (
      <button data-testid="tabs-tab" data-tab-value={value}>
        {children}
      </button>
    ),
    TabsPanel: ({ children, value }) => (
      <div data-testid="tabs-panel" data-value={value}>
        {children}
      </div>
    ),
    Table: ({ children, ...props }) => (
      <table data-testid="table" {...props}>
        {children}
      </table>
    ),
    TableThead: ({ children }) => (
      <thead data-testid="table-thead">{children}</thead>
    ),
    TableTbody: ({ children }) => (
      <tbody data-testid="table-tbody">{children}</tbody>
    ),
    TableTr: ({ children, onClick, ...props }) => (
      <tr onClick={onClick} data-testid="table-tr" {...props}>
        {children}
      </tr>
    ),
    TableTh: ({ children, ...props }) => (
      <th data-testid="table-th" {...props}>
        {children}
      </th>
    ),
    TableTd: ({ children, ...props }) => (
      <td data-testid="table-td" {...props}>
        {children}
      </td>
    ),
    Divider: (props) => <hr data-testid="divider" {...props} />,
  };
});

describe('SeriesModal', () => {
  let mockVODStore;
  let mockVideoStore;
  let mockSettingsStore;

  const mockSeries = {
    id: 1,
    name: 'Test Series',
    series_image: 'https://example.com/cover.jpg',
    genre: 'Drama, Action',
    cast: 'Actor 1, Actor 2',
    director: 'Director Name',
    m3u_account: { name: 'Test Account' },
    rating: '8.5',
    release_date: '2020-01-01',
    youtube_trailer: 'dQw4w9WgXcQ',
  };

  const mockEpisode = {
    id: 1,
    uuid: 'episode-uuid-1',
    series_id: 1,
    season_number: 1,
    episode_number: 1,
    name: 'Pilot',
    duration_secs: 3600,
    rating: '8.0',
    container_extension: 'mkv',
    resolution: '1080p',
    video_codec: 'h264',
    added: '2024-01-01T00:00:00Z',
  };

  const mockDetailedSeries = {
    ...mockSeries,
    episodesList: [mockEpisode],
    tmdb_id: '12345',
    imdb_id: 'tt1234567',
  };

  const mockProviders = [
    {
      id: 1,
      stream_id: 100,
      external_series_id: 100,
      account_id: 5,
      m3u_account: { id: 5, name: 'Provider 1' },
      category: { id: 10, name: 'NETFLIX ANIME' },
      stream_name: 'Test Series 1080p',
      quality_info: { quality: '1080p' },
    },
    {
      id: 2,
      stream_id: 101,
      external_series_id: 101,
      account_id: 5,
      m3u_account: { id: 5, name: 'Provider 1' },
      category: { id: 11, name: 'GERMANY KINDER' },
      stream_name: 'Test Series 720p',
      quality_info: null,
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();

    mockVODStore = {
      fetchSeriesInfo: vi.fn().mockResolvedValue(mockDetailedSeries),
      fetchSeriesProviders: vi.fn().mockResolvedValue(mockProviders),
    };

    mockVideoStore = {
      showVideo: vi.fn(),
    };

    mockSettingsStore = {
      environment: { env_mode: 'prod' },
    };

    useVODStore.mockImplementation((selector) =>
      selector ? selector(mockVODStore) : mockVODStore
    );
    useVideoStore.mockImplementation((selector) =>
      selector ? selector(mockVideoStore) : mockVideoStore
    );
    useSettingsStore.mockImplementation((selector) =>
      selector ? selector(mockSettingsStore) : mockSettingsStore
    );

    copyToClipboard.mockResolvedValue(undefined);
  });

  it('shows stored sources while missing episodes load in the background', async () => {
    mockVODStore.fetchSeriesInfo.mockResolvedValue({
      ...mockDetailedSeries,
      episodesList: [],
      detail_refresh_status: 'pending',
    });

    render(<SeriesModal series={mockSeries} opened onClose={vi.fn()} />);

    expect(
      await screen.findByText(
        /Provider episodes are updating in the background/
      )
    ).toBeInTheDocument();
    expect(screen.getByText('Sources (2)')).toBeInTheDocument();
    expect(
      screen.getByText('Episodes are loading in the background.')
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Refresh provider episodes' })
    ).toBeDisabled();
  });

  it('retries a failed provider lookup without hiding stored episodes', async () => {
    const refresh = vi
      .spyOn(API, 'refreshSeriesProviderInfo')
      .mockResolvedValue({
        detail_refresh_status: 'pending',
      });
    mockVODStore.fetchSeriesInfo.mockResolvedValue({
      ...mockDetailedSeries,
      detail_refresh_status: 'failed',
    });

    render(<SeriesModal series={mockSeries} opened onClose={vi.fn()} />);
    expect(
      await screen.findByText(/provider did not return episode details/i)
    ).toBeInTheDocument();
    expect(screen.getByText('Pilot')).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole('button', { name: 'Refresh provider episodes' })
    );
    await waitFor(() => expect(refresh).toHaveBeenCalledWith(1, 1));
    expect(screen.getByText('Pilot')).toBeInTheDocument();
    refresh.mockRestore();
  });

  it('does not reload providers when the same series is passed as a new object', async () => {
    const onClose = vi.fn();
    const view = render(
      <SeriesModal series={mockSeries} opened={true} onClose={onClose} />
    );
    await waitFor(() =>
      expect(mockVODStore.fetchSeriesProviders).toHaveBeenCalledTimes(1)
    );

    view.rerender(
      <SeriesModal series={{ ...mockSeries }} opened={true} onClose={onClose} />
    );

    await waitFor(() =>
      expect(mockVODStore.fetchSeriesProviders).toHaveBeenCalledTimes(1)
    );
  });

  it('stops the source loader when profile ordering replaces the detail request', async () => {
    mockVODStore.fetchSeriesInfo
      .mockImplementationOnce(() => new Promise(() => {}))
      .mockResolvedValueOnce(mockDetailedSeries);

    render(
      <SeriesModal
        series={mockSeries}
        opened={true}
        onClose={vi.fn()}
        profileCandidates={{
          profile_id: 7,
          canonical_id: mockSeries.id,
          results: [
            { relation_id: mockProviders[0].id, allowed: true, position: 1 },
          ],
        }}
      />
    );

    await waitFor(() =>
      expect(mockVODStore.fetchSeriesInfo).toHaveBeenCalledTimes(2)
    );
    const sourcesTitle = screen
      .getAllByTestId('title')
      .find((node) => node.textContent === 'Sources (2)');
    expect(sourcesTitle).toBeTruthy();
    expect(
      sourcesTitle.parentElement.querySelector('[data-testid="loader"]')
    ).not.toBeInTheDocument();
  });

  describe('Rendering', () => {
    it('should render nothing when series is null', () => {
      const { container } = render(
        <SeriesModal series={null} opened={true} onClose={vi.fn()} />
      );

      expect(container.firstChild).toBeNull();
    });

    it('should render nothing when modal is closed', () => {
      render(
        <SeriesModal series={mockSeries} opened={false} onClose={vi.fn()} />
      );

      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('should render modal when opened with series', async () => {
      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(screen.getByTestId('modal')).toBeInTheDocument();
      });
    });

    it('should display series name as title', async () => {
      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(screen.getByText('Test Series')).toBeInTheDocument();
      });
    });

    it('keeps the canonical title when provider details use a raw title', async () => {
      mockVODStore.fetchSeriesInfo.mockResolvedValue({
        ...mockDetailedSeries,
        name: '┃DE┃ Provider Series UHD',
      });

      render(
        <SeriesModal
          series={{ ...mockSeries, name: 'Canonical Series' }}
          opened={true}
          onClose={vi.fn()}
          allowSourceEditing={false}
        />
      );

      expect(await screen.findByText('Canonical Series')).toBeInTheDocument();
      expect(
        screen.queryByText('┃DE┃ Provider Series UHD')
      ).not.toBeInTheDocument();
    });

    it('should display cover image', async () => {
      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        const image = screen.getByAltText('Test Series');
        expect(image).toHaveAttribute('src', 'https://example.com/cover.jpg');
      });
    });

    it('should show loader while fetching details', () => {
      mockVODStore.fetchSeriesInfo = vi.fn(() => new Promise(() => {}));

      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      //expect multiple loader instances since we have one for details and one for providers
      const loaders = screen.getAllByTestId('loader');
      expect(loaders.length).toBeGreaterThan(0);
    });
  });

  describe('Data Fetching', () => {
    it('should fetch series info when opened', async () => {
      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(mockVODStore.fetchSeriesInfo).toHaveBeenCalledWith(1, 1);
      });
    });

    it('should fetch series providers when opened', async () => {
      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(mockVODStore.fetchSeriesProviders).toHaveBeenCalledWith(1);
      });
    });

    it('should not fetch data when modal is closed', () => {
      render(
        <SeriesModal series={mockSeries} opened={false} onClose={vi.fn()} />
      );

      expect(mockVODStore.fetchSeriesInfo).not.toHaveBeenCalled();
      expect(mockVODStore.fetchSeriesProviders).not.toHaveBeenCalled();
    });

    it('should reset state when modal closes', async () => {
      const { rerender } = render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(mockVODStore.fetchSeriesInfo).toHaveBeenCalled();
      });

      rerender(
        <SeriesModal series={mockSeries} opened={false} onClose={vi.fn()} />
      );

      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });
  });

  describe('Series Information Display', () => {
    it('should display genre', async () => {
      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(screen.getByText(/Drama, Action/)).toBeInTheDocument();
      });
    });

    it('should display rating', async () => {
      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(screen.getByText(/8\.5/)).toBeInTheDocument();
      });
    });

    it('should display IMDB link when imdb_id exists', async () => {
      render(
        <SeriesModal
          series={mockDetailedSeries}
          opened={true}
          onClose={vi.fn()}
        />
      );

      await waitFor(() => {
        const link = screen.getByText(/IMDB/i).closest('a');
        expect(link).toHaveAttribute(
          'href',
          'https://www.imdb.com/title/tt1234567'
        );
      });
    });

    it('should display TMDB link when tmdb_id exists', async () => {
      render(
        <SeriesModal
          series={mockDetailedSeries}
          opened={true}
          onClose={vi.fn()}
        />
      );

      await waitFor(() => {
        const link = screen.getByRole('link', { name: 'TMDb' });
        expect(link).toHaveAttribute(
          'href',
          'https://www.themoviedb.org/tv/12345'
        );
      });
    });
  });

  describe('Provider Selection', () => {
    it('should display account and category columns', async () => {
      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(screen.getByText('M3U account')).toBeInTheDocument();
        expect(screen.getAllByText('Provider 1')).toHaveLength(2);
        expect(screen.getByText('Category')).toBeInTheDocument();
      });
    });

    it('should show category names separately from the account', async () => {
      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(screen.getByText('NETFLIX ANIME')).toBeInTheDocument();
        expect(screen.getByText('GERMANY KINDER')).toBeInTheDocument();
      });
    });

    it('should handle provider selection', async () => {
      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(mockVODStore.fetchSeriesInfo).toHaveBeenCalledWith(1, 1);
      });
      const openFetchCount = mockVODStore.fetchSeriesInfo.mock.calls.length;

      const source = await screen.findByText('Test Series 720p');
      fireEvent.click(source.closest('tr'));

      await waitFor(() => {
        expect(mockVODStore.fetchSeriesInfo).toHaveBeenCalledWith(1, 2);
        // Open effect must not re-fire when selectedProvider changes.
        expect(mockVODStore.fetchSeriesInfo.mock.calls.length).toBe(
          openFetchCount + 1
        );
      });
    });

    it('keeps primary series metadata stable while changing sources', async () => {
      let resolveSecondDetails;
      mockVODStore.fetchSeriesInfo
        .mockResolvedValueOnce({
          ...mockDetailedSeries,
          canonical: { ...mockSeries, name: 'Stable canonical series' },
        })
        .mockImplementationOnce(
          () =>
            new Promise((resolve) => {
              resolveSecondDetails = resolve;
            })
        );

      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      expect(
        await screen.findByText('Stable canonical series')
      ).toBeInTheDocument();
      fireEvent.click(screen.getByText('Test Series 720p').closest('tr'));
      expect(
        screen.queryByText('Loading series details and episodes...')
      ).not.toBeInTheDocument();

      resolveSecondDetails({
        ...mockDetailedSeries,
        canonical: { ...mockSeries, name: 'Different provider series' },
      });

      await waitFor(() =>
        expect(mockVODStore.fetchSeriesInfo).toHaveBeenCalledWith(1, 2)
      );
      expect(screen.getByText('Stable canonical series')).toBeInTheDocument();
      expect(
        screen.queryByText('Different provider series')
      ).not.toBeInTheDocument();
    });

    it('should show loader while fetching providers', () => {
      mockVODStore.fetchSeriesProviders = vi.fn(() => new Promise(() => {}));

      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      // Should show loading text and loader
      expect(screen.getByText('Sources (0)')).toBeInTheDocument();
      const loaders = screen.getAllByTestId('loader');
      expect(loaders.length).toBeGreaterThan(0);
    });
  });

  describe('Episodes Display', () => {
    it('should display episodes grouped by season', async () => {
      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(screen.getByText(/Season 1/i)).toBeInTheDocument();
      });
    });

    it('should display episode information', async () => {
      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(screen.getByText(/Pilot/)).toBeInTheDocument();
      });
    });

    it('shows the exact resolution and codec for each episode', async () => {
      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      const episodeRow = (await screen.findByText('Pilot')).closest('tr');
      expect(within(episodeRow).getByText('1080p')).toBeInTheDocument();
      expect(within(episodeRow).getByText('H264')).toBeInTheDocument();
    });

    it('should format episode duration correctly', async () => {
      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(screen.getByText(/1h 0m/)).toBeInTheDocument();
      });
    });

    it('should handle episodes with no duration', async () => {
      const episodeNoDuration = { ...mockEpisode, duration_secs: null };
      mockVODStore.fetchSeriesInfo.mockResolvedValue({
        ...mockDetailedSeries,
        episodesList: [episodeNoDuration],
      });

      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(screen.getByText(/Pilot/)).toBeInTheDocument();
      });
    });

    it('should sort episodes by episode number', async () => {
      const episode2 = {
        ...mockEpisode,
        id: 2,
        episode_number: 2,
        name: 'Second Episode',
      };
      mockVODStore.fetchSeriesInfo.mockResolvedValue({
        ...mockDetailedSeries,
        episodesList: [episode2, mockEpisode],
      });

      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        const pilot = screen.getByText('Pilot').closest('tr');
        const second = screen.getByText('Second Episode').closest('tr');
        expect(
          pilot.compareDocumentPosition(second) &
            Node.DOCUMENT_POSITION_FOLLOWING
        ).toBeTruthy();
      });
    });
  });

  describe('Episode Actions', () => {
    it('should play episode when play button clicked', async () => {
      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        const playButtons = screen.getAllByTestId('action-icon');
        fireEvent.click(playButtons[0]);
      });

      expect(mockVideoStore.showVideo).toHaveBeenCalledWith(
        expect.stringContaining('/proxy/vod/episode/episode-uuid-1'),
        'vod',
        mockEpisode
      );
    });

    it('should include provider stream_id in URL when provider selected', async () => {
      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        const playButtons = screen.getAllByTestId('action-icon');
        fireEvent.click(playButtons[0]);
      });

      expect(mockVideoStore.showVideo).toHaveBeenCalledWith(
        expect.stringContaining('stream_id=100'),
        'vod',
        mockEpisode
      );
    });

    it('should use dev mode URL in development', async () => {
      mockSettingsStore.environment.env_mode = 'dev';

      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        const playButtons = screen.getAllByTestId('action-icon');
        fireEvent.click(playButtons[0]);
      });

      expect(mockVideoStore.showVideo).toHaveBeenCalledWith(
        expect.stringContaining('localhost:5656'),
        'vod',
        mockEpisode
      );
    });

    it('should copy episode link when copy button clicked', async () => {
      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        const copyButtons = screen.getAllByTestId('action-icon');
        fireEvent.click(copyButtons[1]);
      });

      expect(copyToClipboard).toHaveBeenCalledWith(
        expect.stringContaining('/proxy/vod/episode/episode-uuid-1'),
        expect.objectContaining({
          successTitle: 'Link Copied!',
          successMessage: 'Episode link copied to clipboard',
        })
      );
    });

    it('should expand episode details when row clicked', async () => {
      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        fireEvent.click(screen.getByText('Pilot').closest('tr'));
      });

      await waitFor(() => {
        expect(screen.getByText(/8\.0/)).toBeInTheDocument();
      });
    });

    it('should collapse episode details when clicked again', async () => {
      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        fireEvent.click(screen.getByText('Pilot').closest('tr'));
      });

      await waitFor(() => {
        expect(screen.getByText(/8\.0/)).toBeInTheDocument();
      });

      await waitFor(() => {
        fireEvent.click(screen.getByText('Pilot').closest('tr'));
      });

      await waitFor(() => {
        expect(screen.queryByText(/8\.0/)).not.toBeInTheDocument();
      });
    });
  });

  it('should show trailer button when youtube_trailer exists', async () => {
    render(<SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('Watch Trailer')).toBeInTheDocument();
    });
  });

  describe('Season Tabs', () => {
    it('should create tabs for each season', async () => {
      const season2Episode = {
        ...mockEpisode,
        id: 2,
        season_number: 2,
        episode_num: 1,
      };
      mockVODStore.fetchSeriesInfo.mockResolvedValue({
        ...mockDetailedSeries,
        episodesList: [mockEpisode, season2Episode],
      });

      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(screen.getByText(/Season 1/i)).toBeInTheDocument();
        expect(screen.getByText(/Season 2/i)).toBeInTheDocument();
      });
    });

    it('should sort seasons in ascending order', async () => {
      const season3Episode = { ...mockEpisode, id: 3, season_number: 3 };
      const season2Episode = { ...mockEpisode, id: 2, season_number: 2 };
      mockVODStore.fetchSeriesInfo.mockResolvedValue({
        ...mockDetailedSeries,
        episodesList: [season3Episode, mockEpisode, season2Episode],
      });

      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        const tabs = screen.getAllByTestId('tabs-tab');
        expect(tabs[0]).toHaveTextContent('Season 1');
        expect(tabs[1]).toHaveTextContent('Season 2');
        expect(tabs[2]).toHaveTextContent('Season 3');
      });
    });

    it('should activate first season tab by default', async () => {
      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        const tabs = screen.getByTestId('tabs');
        expect(tabs).toHaveAttribute('data-value', 'season-1');
      });
    });
  });

  describe('Duplicate source differentiation', () => {
    it('shows a source selector when account and category are identical', async () => {
      mockVODStore.fetchSeriesProviders.mockResolvedValue([
        mockProviders[0],
        {
          ...mockProviders[1],
          category: mockProviders[0].category,
        },
      ]);

      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(screen.getByLabelText('Exact VOD sources')).toBeInTheDocument();
        expect(screen.getByText('Test Series 1080p')).toBeInTheDocument();
        expect(screen.getByText('Test Series 720p')).toBeInTheDocument();
        expect(
          screen.getByText(/Provider series ID:.*100/)
        ).toBeInTheDocument();
        expect(
          screen.getByText(/Provider series ID:.*101/)
        ).toBeInTheDocument();
      });
    });
  });

  describe('Edge Cases', () => {
    it('should handle series with no episodes', async () => {
      mockVODStore.fetchSeriesInfo.mockResolvedValue({
        ...mockDetailedSeries,
        episodesList: [],
      });

      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(screen.queryByTestId('table')).not.toBeInTheDocument();
      });
    });

    it('should handle fetch errors gracefully', async () => {
      mockVODStore.fetchSeriesInfo.mockRejectedValue(new Error('Fetch failed'));

      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(mockVODStore.fetchSeriesInfo).toHaveBeenCalled();
      });
    });

    it('should handle episodes with null season_number', async () => {
      const episodeNoSeason = { ...mockEpisode, season_number: null };
      mockVODStore.fetchSeriesInfo.mockResolvedValue({
        ...mockDetailedSeries,
        episodesList: [episodeNoSeason],
      });

      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(screen.getByText(/Season 1/i)).toBeInTheDocument();
      });
    });

    it('should show a Season 0 tab for specials', async () => {
      const special = {
        ...mockEpisode,
        id: 99,
        season_number: 0,
        episode_number: 1,
        name: 'Special',
      };
      const seasonOne = { ...mockEpisode, id: 1, season_number: 1 };
      mockVODStore.fetchSeriesInfo.mockResolvedValue({
        ...mockDetailedSeries,
        episodesList: [special, seasonOne],
      });

      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(screen.getByText(/Season 0/i)).toBeInTheDocument();
        expect(screen.getByText(/Season 1/i)).toBeInTheDocument();
      });
    });

    it('should handle empty provider list', async () => {
      mockVODStore.fetchSeriesProviders.mockResolvedValue([]);

      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(
          screen.getByText(
            'No exact source relation is available for this series.'
          )
        ).toBeInTheDocument();
      });
    });
  });

  describe('Modal Close', () => {
    it('should call onClose when close button clicked', async () => {
      const onClose = vi.fn();

      render(
        <SeriesModal series={mockSeries} opened={true} onClose={onClose} />
      );

      await waitFor(() => {
        const closeButton = screen.getByTestId('modal-close');
        fireEvent.click(closeButton);
      });

      expect(onClose).toHaveBeenCalled();
    });
  });

  describe('Helper Functions', () => {
    it('should format duration with hours and minutes', () => {
      const duration = 7265; // 2h 1m 5s
      // This tests the formatDuration function indirectly through episode display
      const episode = {
        ...mockEpisode,
        info: { ...mockEpisode.info, duration },
      };
      mockVODStore.fetchSeriesInfo.mockResolvedValue({
        ...mockDetailedSeries,
        episodesList: [episode],
      });

      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      waitFor(() => {
        expect(screen.getByText(/2h 1m/)).toBeInTheDocument();
      });
    });

    it('should format duration with minutes and seconds when under an hour', () => {
      const duration = 125; // 2m 5s
      const episode = {
        ...mockEpisode,
        info: { ...mockEpisode.info, duration },
      };
      mockVODStore.fetchSeriesInfo.mockResolvedValue({
        ...mockDetailedSeries,
        episodesList: [episode],
      });

      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      waitFor(() => {
        expect(screen.getByText(/2m 5s/)).toBeInTheDocument();
      });
    });
  });
});
