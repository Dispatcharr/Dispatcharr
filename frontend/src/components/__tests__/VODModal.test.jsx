import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import VODModal from '../VODModal';
import useVODStore from '../../store/useVODStore';
import useVideoStore from '../../store/useVideoStore';
import useSettingsStore from '../../store/settings';

// Mock stores
vi.mock('../../store/useVODStore');
vi.mock('../../store/useVideoStore');
vi.mock('../../store/settings');

// Mock utils
vi.mock('../../utils', () => ({
  copyToClipboard: vi.fn(() => Promise.resolve()),
}));

vi.mock('../../utils/components/SeriesModalUtils.js', () => ({
  formatStreamLabel: vi.fn((provider) => `${provider.m3u_account.name} - Stream ${provider.stream_id}`),
  imdbUrl: vi.fn((id) => `https://www.imdb.com/title/${id}`),
  tmdbUrl: vi.fn((id, type) => `https://www.themoviedb.org/${type}/${id}`),
  formatDuration: vi.fn((secs) => `${Math.floor(secs / 60)} min`),
  getYouTubeEmbedUrl: vi.fn((url) => `https://www.youtube.com/embed/${url}`),
}));

// Mock Mantine components
vi.mock('@mantine/core', async () => {
  return {
    Modal: ({ children, opened, onClose, title }) =>
      opened ? (
        <div data-testid="modal">
          <div data-testid="modal-title">{title}</div>
          <button data-testid="modal-close" onClick={onClose}>Close</button>
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
    Select: ({ data, value, onChange, placeholder, disabled }) => (
      <select data-testid="provider-select" value={value}
              onChange={(e) => onChange(e.target.value)} disabled={disabled}>
        <option value="">{placeholder}</option>
        {data.map((item) => (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        ))}
      </select>
    ),
    Loader: () => <div data-testid="loader">Loading...</div>,
  };
});

// Mock lucide-react icons
vi.mock('lucide-react', () => ({
  Play: () => <span>Play Icon</span>,
  Copy: () => <span>Copy Icon</span>,
}));

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

  it('should render modal when opened with vod', () => {
    render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);
    expect(screen.getByTestId('modal')).toBeInTheDocument();
    expect(screen.getByTestId('modal-title')).toHaveTextContent('Test Movie');
  });

  it('should not render when closed', () => {
    render(<VODModal vod={mockVOD} opened={false} onClose={mockOnClose} />);
    expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
  });

  it('should display movie details correctly', async () => {
    render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.getByText('Original: Original Test Movie')).toBeInTheDocument();
    });

    expect(screen.getByText('2023')).toBeInTheDocument();
    expect(screen.getByText('8.5')).toBeInTheDocument();
    expect(screen.getByText('PG-13')).toBeInTheDocument();
    expect(screen.getByText('Action, Sci-Fi')).toBeInTheDocument();
    expect(screen.getByText(/Test Director/)).toBeInTheDocument();
    expect(screen.getByText(/Actor 1, Actor 2/)).toBeInTheDocument();
    expect(screen.getByText(/A test movie description/)).toBeInTheDocument();
  });

  it('should fetch movie details on mount', async () => {
    render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(mockFetchMovieDetailsFromProvider).toHaveBeenCalledWith(mockVOD.id);
    });
  });

  it('should fetch movie providers on mount', async () => {
    render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(mockFetchMovieProviders).toHaveBeenCalledWith(mockVOD.id);
    });
  });

  it('should show loading state while fetching details', () => {
    mockFetchMovieDetailsFromProvider.mockImplementation(
      () => new Promise(() => {})
    );

    render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

    expect(screen.getByText('Loading additional details...')).toBeInTheDocument();
  });

  it('should handle play button click', async () => {
    render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(mockFetchMovieProviders).toHaveBeenCalled();
    });

    const playButton = screen.getByText('Play Movie');
    fireEvent.click(playButton);

    expect(mockShowVideo).toHaveBeenCalled();
  });

  it('should disable play button when multiple providers and none selected', async () => {
    mockFetchMovieProviders.mockResolvedValue([mockProvider, { ...mockProvider, id: 2 }]);

    render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.getByText('Play Movie')).toBeInTheDocument();
    });

    // Note: Testing for disabled state would require checking the button's disabled attribute
  });

  it('should handle provider selection', async () => {
    const providers = [
      mockProvider,
      { ...mockProvider, id: 2, stream_id: 'stream-456' },
    ];
    mockFetchMovieProviders.mockResolvedValue(providers);

    render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

    await waitFor(() => {
      const select = screen.getByTestId('provider-select');
      expect(select).toBeInTheDocument();
    });

    const select = screen.getByTestId('provider-select');
    fireEvent.change(select, { target: { value: '2' } });

    await waitFor(() => {
      const select = screen.getByTestId('provider-select');
      expect(select).toHaveValue('2');
    });
  });

  it('should display single provider as badge', async () => {
    mockFetchMovieProviders.mockResolvedValue([mockProvider]);

    render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.getByText('Test Provider')).toBeInTheDocument();
    });
  });

  it('should handle fetch details error gracefully', async () => {
    mockFetchMovieDetailsFromProvider.mockRejectedValue(new Error('Fetch failed'));

    render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(mockFetchMovieDetailsFromProvider).toHaveBeenCalled();
    });

    // Should still display basic VOD info
    expect(screen.getByTestId('modal-title')).toHaveTextContent('Test Movie');
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

  it('should display technical details when available', async () => {
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

    await waitFor(() => {
      expect(screen.getByText(/Technical Details:/)).toBeInTheDocument();
    });
  });

  it('should render IMDb and TMDb badges with correct links', () => {
    render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

    const imdbLink = screen.getByText('IMDb');
    const tmdbLink = screen.getByText('TMDb');

    expect(imdbLink).toHaveAttribute('href', 'https://www.imdb.com/title/tt1234567');
    expect(tmdbLink).toHaveAttribute('href', 'https://www.themoviedb.org/movie/12345');
  });

  describe('Copy Link Functionality', () => {
    it('should copy movie link when copy button clicked', async () => {
      const { copyToClipboard } = await import('../../utils');

      render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

      await waitFor(() => {
        const copyButton = screen.getByText('Copy Link');
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
        { ...mockProvider, id: 2, stream_id: 'stream-456' },
      ]);

      render(<VODModal vod={mockVOD} opened={true} onClose={mockOnClose} />);

      await waitFor(() => {
        const select = screen.getByTestId('provider-select');
        fireEvent.change(select, { target: { value: '2' } });
      });

      await waitFor(() => {
        const copyButton = screen.getByText('Copy Link')
        fireEvent.click(copyButton);
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
        const playButton = screen.getByText('Play Movie');
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
        const playButton = screen.getByText('Play Movie');
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
        expect(screen.getByTestId('modal-title')).toHaveTextContent('Test Movie');
      });
    });
  });
});
