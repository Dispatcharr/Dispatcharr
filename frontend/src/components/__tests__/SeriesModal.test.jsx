import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import SeriesModal from '../SeriesModal';
import useVODStore from '../../store/useVODStore';
import useVideoStore from '../../store/useVideoStore';
import useSettingsStore from '../../store/settings';
import { copyToClipboard } from '../../utils';

// Mock stores
vi.mock('../../store/useVODStore', () => ({
  default: vi.fn(),
}));

vi.mock('../../store/useVideoStore', () => ({
  default: vi.fn(),
}));

vi.mock('../../store/settings', () => ({
  default: vi.fn(),
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
}));

// Mock Mantine components
vi.mock('@mantine/core', async () => {
  const actual = await vi.importActual('@mantine/core');

  return {
    ...actual,
    Modal: ({ opened, onClose, title, children, size, ...props }) => {
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
    Stack: ({ children, ...props }) => (
      <div data-testid="stack" {...props}>
        {children}
      </div>
    ),
    ActionIcon: ({ children, onClick, disabled, ...props }) => (
      <button
        onClick={onClick}
        disabled={disabled}
        data-testid="action-icon"
        {...props}
      >
        {children}
      </button>
    ),
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
      account_id: 5,
      m3u_account: { name: 'Provider 1' },
      stream_name: 'Test Series 1080p',
      quality_info: { quality: '1080p' },
    },
    {
      id: 2,
      stream_id: 101,
      account_id: 5,
      m3u_account: { name: 'Provider 2' },
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
        expect(mockVODStore.fetchSeriesInfo).toHaveBeenCalledWith(1);
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
        const link = screen.getByText(/TMDB/i).closest('a');
        expect(link).toHaveAttribute(
          'href',
          'https://www.themoviedb.org/tv/12345'
        );
      });
    });
  });

  describe('Provider Selection', () => {
    it('should display provider select with fetched providers', async () => {
      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        const select = screen.getByTestId('select');
        expect(select).toBeInTheDocument();
      });
    });

    it('should format provider label correctly with quality info', async () => {
      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(screen.getByText(/Provider 1 - 1080p/)).toBeInTheDocument();
      });
    });

    it('should handle provider selection', async () => {
      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      let select;
      await waitFor(() => {
        select = screen.getByTestId('select').querySelector('select');
        fireEvent.change(select, { target: { value: '1' } });
      });

      await waitFor(() => {
        expect(select.value).toBe('1');
      });
    });

    it('should show loader while fetching providers', () => {
      mockVODStore.fetchSeriesProviders = vi.fn(() => new Promise(() => {}));

      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      // Should show loading text and loader
      expect(screen.getByText('Stream Selection')).toBeInTheDocument();
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
        const episodes = screen.getAllByTestId('table-tr');
        expect(episodes[1]).toHaveTextContent('Pilot');
        expect(episodes[2]).toHaveTextContent('Second Episode');
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
        const select = screen.getByTestId('select').querySelector('select');
        fireEvent.change(select, { target: { value: '1' } });
      });

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
        const rows = screen.getAllByTestId('table-tr');
        fireEvent.click(rows[1]);
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
        const rows = screen.getAllByTestId('table-tr');
        fireEvent.click(rows[1]);
      });

      await waitFor(() => {
        expect(screen.getByText(/8\.0/)).toBeInTheDocument();
      });

      await waitFor(() => {
        const rows = screen.getAllByTestId('table-tr');
        fireEvent.click(rows[1]);
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

  describe('Quality Info Extraction', () => {
    it('should extract quality from quality_info field', async () => {
      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(screen.getByText(/Provider 1 - 1080p/)).toBeInTheDocument();
      });
    });

    it('should extract quality from custom_properties.detailed_info.video', async () => {
      const customProviders = [
        {
          ...mockProviders[0],
          quality_info: null,
          custom_properties: {
            detailed_info: {
              video: { width: 1920, height: 1080 },
            },
          },
        },
        mockProviders[1],
      ];
      mockVODStore.fetchSeriesProviders.mockResolvedValue(customProviders);

      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(screen.getByText(/Provider 1 - 1080p/)).toBeInTheDocument();
      });
    });

    it('should extract quality from stream_name as fallback', async () => {
      const customProviders = [
        {
          ...mockProviders[0],
          quality_info: null,
          stream_name: 'Test Series 720p',
        },
        mockProviders[1],
      ];
      mockVODStore.fetchSeriesProviders.mockResolvedValue(customProviders);

      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(screen.getByText(/Provider 1 - 720p/)).toBeInTheDocument();
      });
    });

    it('should detect 4K quality', async () => {
      const customProviders = [
        {
          ...mockProviders[0],
          quality_info: null,
          custom_properties: {
            detailed_info: {
              video: { width: 3840, height: 2160 },
            },
          },
        },
        mockProviders[1],
      ];
      mockVODStore.fetchSeriesProviders.mockResolvedValue(customProviders);

      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(screen.getByText(/Provider 1 - 4K/)).toBeInTheDocument();
      });
    });

    it('should show resolution when standard quality not detected', async () => {
      const customProviders = [
        {
          ...mockProviders[0],
          quality_info: null,
          custom_properties: {
            detailed_info: {
              video: { width: 720, height: 480 },
            },
          },
        },
        mockProviders[1],
      ];
      mockVODStore.fetchSeriesProviders.mockResolvedValue(customProviders);

      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(screen.getByText(/720x480/)).toBeInTheDocument();
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

    it('should handle empty provider list', async () => {
      mockVODStore.fetchSeriesProviders.mockResolvedValue([]);

      render(
        <SeriesModal series={mockSeries} opened={true} onClose={vi.fn()} />
      );

      await waitFor(() => {
        expect(screen.getByText('Test Account')).toBeInTheDocument();
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
