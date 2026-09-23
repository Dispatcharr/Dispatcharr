import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import VODModal from '../VODModal';
import useVODStore from '../../store/useVODStore';
import useVideoStore from '../../store/useVideoStore';
import useSettingsStore from '../../store/settings';
import API from '../../api';

// Mock stores
vi.mock('../../store/useVODStore');
vi.mock('../../store/useVideoStore');
vi.mock('../../store/settings');
vi.mock('../VODExternalIds.jsx', () => ({
  default: ({ tmdbId, imdbId }) => (
    <div>
      {imdbId && <a href={`https://www.imdb.com/title/${imdbId}`}>IMDb</a>}
      {tmdbId && (
        <a href={`https://www.themoviedb.org/movie/${tmdbId}`}>TMDb</a>
      )}
    </div>
  ),
}));

// Mock utils
vi.mock('../../utils', () => ({
  copyToClipboard: vi.fn(() => Promise.resolve()),
}));

vi.mock('../../utils/components/SeriesModalUtils.js', () => ({
  imdbUrl: vi.fn((id) => `https://www.imdb.com/title/${id}`),
  tmdbUrl: vi.fn((id, type) => `https://www.themoviedb.org/${type}/${id}`),
  formatDuration: vi.fn((secs) => `${Math.floor(secs / 60)} min`),
  getYouTubeEmbedUrl: vi.fn((url) => `https://www.youtube.com/embed/${url}`),
}));

// Mock Mantine components
vi.mock('@mantine/core', async () => {
  const actual = await vi.importActual('@mantine/core');
  return {
    ...actual,
    Modal: ({ children, opened, onClose, title }) =>
      opened ? (
        <div data-testid="modal">
          <div data-testid="modal-title">{title}</div>
          <button data-testid="modal-close" onClick={onClose}>
            Close
          </button>
          {children}
        </div>
      ) : null,
    Box: ({ children, ...props }) => <div {...props}>{children}</div>,
    Stack: ({ children }) => <div>{children}</div>,
    Group: ({ children }) => <div>{children}</div>,
    Flex: ({ children }) => <div>{children}</div>,
    Image: ({ src, alt }) => <img src={src} alt={alt} />,
    Text: ({ children, ...props }) => <span {...props}>{children}</span>,
    Title: ({ children }) => <h3>{children}</h3>,
    Button: ({ children, onClick, disabled, leftSection }) => (
      <button onClick={onClick} disabled={disabled}>
        {leftSection}
        {children}
      </button>
    ),
    Badge: ({ children, component, href, ...props }) =>
      component === 'a' ? (
        <a href={href} {...props}>
          {children}
        </a>
      ) : (
        <span {...props}>{children}</span>
      ),
    Select: ({ data, value, onChange, placeholder, disabled, ...props }) => (
      <select
        data-testid={`${props['aria-label']}-select`}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        {...props}
      >
        <option value="">{placeholder}</option>
        {data.map((item) => (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        ))}
      </select>
    ),
    Loader: () => <div data-testid="loader">Loading...</div>,
    Alert: ({ children }) => <div>{children}</div>,
    ActionIcon: ({ children, onClick, disabled, ...props }) => (
      <button onClick={onClick} disabled={disabled} {...props}>
        {children}
      </button>
    ),
    ScrollArea: ({ children }) => <div>{children}</div>,
    Tooltip: ({ children }) => <>{children}</>,
    Table: ({ children, ...props }) => <table {...props}>{children}</table>,
    TableThead: ({ children }) => <thead>{children}</thead>,
    TableTbody: ({ children }) => <tbody>{children}</tbody>,
    TableTr: ({ children, ...props }) => <tr {...props}>{children}</tr>,
    TableTh: ({ children, ...props }) => <th {...props}>{children}</th>,
    TableTd: ({ children, ...props }) => <td {...props}>{children}</td>,
  };
});

// Mock lucide-react icons
vi.mock('lucide-react', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    Play: () => <span>Play Icon</span>,
    Copy: () => <span>Copy Icon</span>,
    Wrench: () => <span>Wrench Icon</span>,
  };
});

describe('VODModal', () => {
  const mockShowVideo = vi.fn();
  const mockFetchMovieDetailsFromProvider = vi.fn();
  const mockFetchMovieProviders = vi.fn();
  const mockOnClose = vi.fn();

  const mockVOD = {
    id: 1,
    uuid: 'test-uuid',
    name: 'Test Movie',
    o_name: 'Original Test Movie',
    year: 2023,
    duration_secs: 7200,
    rating: '8.5',
    age: 'PG-13',
    imdb_id: 'tt1234567',
    tmdb_id: '12345',
    release_date: '2023-01-15',
    genre: 'Action, Sci-Fi',
    director: 'Test Director',
    actors: 'Actor 1, Actor 2',
    country: 'USA',
    description: 'A test movie description',
    youtube_trailer: 'test-trailer-id',
    movie_image: 'https://example.com/poster.jpg',
    backdrop_path: ['https://example.com/backdrop.jpg'],
    bitrate: 5000,
    m3u_account: { name: 'Test Account', id: 1 },
  };

  const mockProvider = {
    id: 1,
    stream_id: 'stream-123',
    m3u_account: { name: 'Test Provider', id: 1 },
    category: { id: 10, name: 'GERMANY MOVIES' },
    bitrate: 6000,
  };

  beforeEach(() => {
    vi.clearAllMocks();

    useVideoStore.mockImplementation((selector) => {
      const state = { showVideo: mockShowVideo };
      return selector ? selector(state) : state;
    });

    useVODStore.mockImplementation((selector) => {
      const state = {
        fetchMovieDetailsFromProvider: mockFetchMovieDetailsFromProvider,
        fetchMovieProviders: mockFetchMovieProviders,
      };
      return selector ? selector(state) : state;
    });

    useSettingsStore.mockImplementation((selector) => {
      const state = { environment: { env_mode: 'prod' } };
      return selector ? selector(state) : state;
    });

    mockFetchMovieDetailsFromProvider.mockResolvedValue(mockVOD);
    mockFetchMovieProviders.mockResolvedValue([mockProvider]);
  });

  it('should not render when vod is null', () => {
    render(<VODModal vod={null} opened={true} onClose={mockOnClose} />);
    expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
  });

  it('keeps cached sources available when provider details are loading', async () => {
    mockFetchMovieDetailsFromProvider.mockResolvedValue({
      ...mockVOD,
      detail_fetched: false,
      detail_refresh_status: 'pending',
    });

    render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

    expect(
      await screen.findByText(/Provider details are loading in the background/)
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: 'Sources (1)' })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Refresh provider details' })
    ).toBeDisabled();
  });

  it('allows retrying a failed provider lookup without blocking the source list', async () => {
    const refresh = vi
      .spyOn(API, 'refreshMovieProviderInfo')
      .mockResolvedValue({
        detail_refresh_status: 'pending',
      });
    mockFetchMovieDetailsFromProvider.mockResolvedValue({
      ...mockVOD,
      detail_fetched: false,
      detail_refresh_status: 'failed',
    });

    render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);
    expect(
      await screen.findByText(/provider did not return details/i)
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', { name: 'Refresh provider details' })
    );

    await waitFor(() => expect(refresh).toHaveBeenCalledWith(1, 1));
    expect(
      screen.getByRole('heading', { name: 'Sources (1)' })
    ).toBeInTheDocument();
    refresh.mockRestore();
  });

  it('should render modal when opened with vod', () => {
    render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);
    expect(screen.getByTestId('modal')).toBeInTheDocument();
    expect(screen.getByTestId('modal-title')).toBeEmptyDOMElement();
    expect(
      screen.getByRole('heading', { level: 3, name: 'Test Movie' })
    ).toBeInTheDocument();
  });

  it('does not reload providers when the same movie is passed as a new object', async () => {
    const view = render(
      <VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />
    );
    await waitFor(() =>
      expect(mockFetchMovieProviders).toHaveBeenCalledTimes(1)
    );

    view.rerender(
      <VODModal vod={{ ...mockVOD }} opened={true} onClose={mockOnClose} />
    );

    await waitFor(() =>
      expect(mockFetchMovieProviders).toHaveBeenCalledTimes(1)
    );
  });

  it('should not render when closed', () => {
    render(<VODModal vod={mockVOD} opened={false} onClose={mockOnClose} />);
    expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
  });

  it('should display movie details correctly', async () => {
    render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(
        screen.getByText('Original: Original Test Movie')
      ).toBeInTheDocument();
    });

    expect(screen.getByText('2023')).toBeInTheDocument();
    expect(screen.getByText('8.5')).toBeInTheDocument();
    expect(screen.getByText('PG-13')).toBeInTheDocument();
    expect(screen.getByText('Action, Sci-Fi')).toBeInTheDocument();
    expect(screen.getByText(/Test Director/)).toBeInTheDocument();
    expect(screen.getByText(/Actor 1, Actor 2/)).toBeInTheDocument();
    expect(screen.getByText(/A test movie description/)).toBeInTheDocument();
  });

  it('keeps the canonical title when provider details use a raw title', async () => {
    mockFetchMovieDetailsFromProvider.mockResolvedValue({
      ...mockVOD,
      name: '┃DE┃ Test Movie UHD',
    });

    render(
      <VODModal
        vod={{ ...mockVOD, name: 'Canonical Test Movie' }}
        opened={true}
        onClose={mockOnClose}
        allowSourceEditing={false}
      />
    );

    expect(
      await screen.findByRole('heading', {
        level: 3,
        name: 'Canonical Test Movie',
      })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('heading', {
        level: 3,
        name: '┃DE┃ Test Movie UHD',
      })
    ).not.toBeInTheDocument();
  });

  it('should fetch movie details on mount', async () => {
    render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(mockFetchMovieDetailsFromProvider).toHaveBeenCalledWith(
        mockVOD.id,
        mockProvider.id
      );
    });
  });

  it('should fetch movie providers on mount', async () => {
    render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(mockFetchMovieProviders).toHaveBeenCalledWith(mockVOD.id);
    });
  });

  it('stops the source loader when profile ordering replaces the detail request', async () => {
    mockFetchMovieDetailsFromProvider
      .mockImplementationOnce(() => new Promise(() => {}))
      .mockResolvedValueOnce(mockVOD);

    render(
      <VODModal
        vod={mockVOD}
        opened={true}
        onClose={mockOnClose}
        profileCandidates={{
          profile_id: 7,
          canonical_id: mockVOD.id,
          results: [
            { relation_id: mockProvider.id, allowed: true, position: 1 },
          ],
        }}
      />
    );

    const heading = await screen.findByRole('heading', {
      level: 3,
      name: 'Sources (1)',
    });
    await waitFor(() =>
      expect(mockFetchMovieDetailsFromProvider).toHaveBeenCalledTimes(2)
    );
    expect(
      screen.queryByText('Loading additional details...')
    ).not.toBeInTheDocument();
    expect(
      heading.parentElement.querySelector('[data-testid="loader"]')
    ).not.toBeInTheDocument();
  });

  it('should show loading state while fetching details', () => {
    mockFetchMovieDetailsFromProvider.mockImplementation(
      () => new Promise(() => {})
    );

    render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

    expect(
      screen.getByText('Loading additional details...')
    ).toBeInTheDocument();
  });

  it('should handle play button click', async () => {
    render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(mockFetchMovieProviders).toHaveBeenCalled();
    });

    const playButton = screen.getByLabelText('Play exact source');
    fireEvent.click(playButton);

    expect(mockShowVideo).toHaveBeenCalled();
  });

  it('should render an exact play action for every provider', async () => {
    mockFetchMovieProviders.mockResolvedValue([
      mockProvider,
      { ...mockProvider, id: 2 },
    ]);

    render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.getAllByLabelText('Play exact source')).toHaveLength(2);
    });

    // Note: Testing for disabled state would require checking the button's disabled attribute
  });

  it('should handle provider selection', async () => {
    const providers = [
      mockProvider,
      {
        ...mockProvider,
        id: 2,
        stream_id: 'stream-456',
        category: { id: 11, name: 'NETFLIX MOVIES' },
      },
    ];
    mockFetchMovieProviders.mockResolvedValue(providers);

    render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

    const source = await screen.findByText('Stream stream-456');
    fireEvent.click(source.closest('tr'));

    await waitFor(() => {
      expect(mockFetchMovieDetailsFromProvider).toHaveBeenCalledWith(1, 2);
    });
  });

  it('keeps source metadata and canonical details scoped during selection', async () => {
    let resolveSecondDetails;
    const providers = [
      {
        ...mockProvider,
        stream_name: 'First source',
        source_metadata: { values: { bitrate_kbps: 9000 } },
      },
      {
        ...mockProvider,
        id: 2,
        stream_id: 'stream-456',
        stream_name: 'Second source',
        source_metadata: { values: {} },
      },
    ];
    mockFetchMovieProviders.mockResolvedValue(providers);
    mockFetchMovieDetailsFromProvider
      .mockResolvedValueOnce({
        ...mockVOD,
        canonical: { ...mockVOD, name: 'Stable canonical title' },
        source_metadata: { values: { bitrate_kbps: 9000 } },
      })
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveSecondDetails = resolve;
          })
      );

    render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

    expect(
      await screen.findByText('Stable canonical title')
    ).toBeInTheDocument();
    const secondRow = screen.getByText('Second source').closest('tr');
    fireEvent.click(secondRow);

    expect(within(secondRow).queryByText('9.00 Mbps')).not.toBeInTheDocument();
    expect(
      screen.queryByText('Loading additional details...')
    ).not.toBeInTheDocument();

    resolveSecondDetails({
      ...mockVOD,
      canonical: { ...mockVOD, name: 'Different provider canonical' },
      source_metadata: { values: { bitrate_kbps: 4200 } },
    });

    await waitFor(() =>
      expect(within(secondRow).getByText('4.20 Mbps')).toBeInTheDocument()
    );
    expect(screen.getByText('Stable canonical title')).toBeInTheDocument();
    expect(
      screen.queryByText('Different provider canonical')
    ).not.toBeInTheDocument();
  });

  it('should select the M3U account independently from the category', async () => {
    const providers = [
      mockProvider,
      {
        ...mockProvider,
        id: 2,
        stream_id: 'stream-other-account',
        m3u_account: { id: 2, name: 'Backup Provider' },
      },
    ];
    mockFetchMovieProviders.mockResolvedValue(providers);

    render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

    const account = await screen.findByText('Backup Provider');
    fireEvent.click(account.closest('tr'));

    await waitFor(() => {
      expect(mockFetchMovieDetailsFromProvider).toHaveBeenCalledWith(1, 2);
      expect(screen.getAllByText('GERMANY MOVIES')).toHaveLength(2);
    });
  });

  it('should display account and category separately for one provider', async () => {
    mockFetchMovieProviders.mockResolvedValue([mockProvider]);

    render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.getByText('M3U account')).toBeInTheDocument();
      expect(screen.getByText('Test Provider')).toBeInTheDocument();
      expect(screen.getByText('Category')).toBeInTheDocument();
      expect(screen.getByText('GERMANY MOVIES')).toBeInTheDocument();
    });
  });

  it('should handle fetch details error gracefully', async () => {
    mockFetchMovieDetailsFromProvider.mockRejectedValue(
      new Error('Fetch failed')
    );

    render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(mockFetchMovieDetailsFromProvider).toHaveBeenCalled();
    });

    // Should still display basic VOD info
    expect(
      screen.getByRole('heading', { level: 3, name: 'Test Movie' })
    ).toBeInTheDocument();
  });

  it('should handle fetch providers error gracefully', async () => {
    mockFetchMovieProviders.mockRejectedValue(new Error('Fetch failed'));

    render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(mockFetchMovieProviders).toHaveBeenCalled();
    });

    // Should still render without providers
    expect(screen.getByTestId('modal')).toBeInTheDocument();
  });

  it('does not duplicate technical details below the exact source list', async () => {
    const vodWithTech = {
      ...mockVOD,
      bitrate: 5000,
      video: {
        codec_name: 'h264',
        width: 1920,
        height: 1080,
      },
      audio: {
        codec_name: 'aac',
        channels: 2,
      },
    };

    mockFetchMovieDetailsFromProvider.mockResolvedValue(vodWithTech);

    render(<VODModal vod={vodWithTech} opened={true} onClose={mockOnClose} />);

    await screen.findByRole('heading', { level: 3, name: 'Sources (1)' });
    expect(screen.queryByText(/Technical Details:/)).not.toBeInTheDocument();
  });

  it('should render IMDb and TMDb badges with correct links', () => {
    render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

    const imdbLink = screen.getByText('IMDb');
    const tmdbLink = screen.getByText('TMDb');

    expect(imdbLink).toHaveAttribute(
      'href',
      'https://www.imdb.com/title/tt1234567'
    );
    expect(tmdbLink).toHaveAttribute(
      'href',
      'https://www.themoviedb.org/movie/12345'
    );
  });

  describe('Copy Link Functionality', () => {
    it('should copy movie link when copy button clicked', async () => {
      const { copyToClipboard } = await import('../../utils');

      render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

      await waitFor(() => {
        const copyButton = screen.getByLabelText('Copy exact source link');
        fireEvent.click(copyButton);
      });

      expect(copyToClipboard).toHaveBeenCalledWith(
        expect.stringContaining('/proxy/vod/movie/test-uuid'),
        expect.objectContaining({
          successTitle: expect.any(String),
          successMessage: expect.any(String),
        })
      );
    });

    it('should include provider stream_id in copied URL when provider selected', async () => {
      const { copyToClipboard } = await import('../../utils');

      mockFetchMovieProviders.mockResolvedValue([
        { ...mockProvider, id: 1 },
        {
          ...mockProvider,
          id: 2,
          stream_id: 'stream-456',
          category: { id: 11, name: 'NETFLIX MOVIES' },
        },
      ]);

      render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

      await waitFor(() => {
        const copyButtons = screen.getAllByLabelText('Copy exact source link');
        fireEvent.click(copyButtons[1]);
      });

      expect(copyToClipboard).toHaveBeenCalledWith(
        expect.stringContaining('stream_id=stream-456'),
        expect.any(Object)
      );
    });
  });

  describe('URL Generation', () => {
    it('should use dev mode URL in development', async () => {
      useSettingsStore.mockImplementation((selector) => {
        const state = { environment: { env_mode: 'dev' } };
        return selector ? selector(state) : state;
      });

      render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

      await waitFor(() => {
        const playButton = screen.getByLabelText('Play exact source');
        fireEvent.click(playButton);
      });

      expect(mockShowVideo).toHaveBeenCalledWith(
        expect.stringContaining('localhost:5656'),
        'vod',
        expect.any(Object)
      );
    });

    it('should use production URL in production', async () => {
      render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

      await waitFor(() => {
        const playButton = screen.getByLabelText('Play exact source');
        fireEvent.click(playButton);
      });

      expect(mockShowVideo).toHaveBeenCalledWith(
        expect.not.stringContaining('localhost:5656'),
        'vod',
        expect.any(Object)
      );
    });
  });

  describe('Modal Interaction', () => {
    it('should call onClose when close button clicked', async () => {
      render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

      await waitFor(() => {
        const closeButton = screen.getByTestId('modal-close');
        fireEvent.click(closeButton);
      });

      expect(mockOnClose).toHaveBeenCalled();
    });
  });

  describe('Edge Cases', () => {
    it('should handle VOD with no image', async () => {
      const vodNoImage = { ...mockVOD, movie_image: null };
      render(<VODModal vod={vodNoImage} opened={true} onClose={mockOnClose} />);

      await waitFor(() => {
        expect(screen.getByTestId('modal')).toBeInTheDocument();
      });
    });

    it('should handle VOD with missing optional fields', async () => {
      const minimalVOD = {
        id: 1,
        uuid: 'test-uuid',
        name: 'Test Movie',
        m3u_account: { name: 'Test Account', id: 1 },
      };

      render(<VODModal vod={minimalVOD} opened={true} onClose={mockOnClose} />);

      await waitFor(() => {
        expect(
          screen.getByRole('heading', { level: 3, name: 'Test Movie' })
        ).toBeInTheDocument();
      });
    });
  });
});
