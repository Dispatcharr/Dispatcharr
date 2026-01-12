import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import VODsPage from '../VODs';
import useVODStore from '../../store/useVODStore';
import {
  filterCategoriesToEnabled,
  getCategoryOptions,
} from '../../utils/pages/VODsUtils.js';

vi.mock('../../store/useVODStore');

vi.mock('../../components/SeriesModal', () => ({
  default: ({ opened, series, onClose }) =>
    opened ? (
      <div data-testid="series-modal">
        <div data-testid="series-name">{series?.name}</div>
        <button onClick={onClose}>Close</button>
      </div>
    ) : null
}));
vi.mock('../../components/VODModal', () => ({
  default: ({ opened, vod, onClose }) =>
    opened ? (
      <div data-testid="vod-modal">
        <div data-testid="vod-name">{vod?.name}</div>
        <button onClick={onClose}>Close</button>
      </div>
    ) : null
}));
vi.mock('../../components/cards/VODCard', () => ({
  default: ({ vod, onClick }) => (
    <div data-testid="vod-card" onClick={() => onClick(vod)}>
      <div>{vod.name}</div>
    </div>
  )
}));
vi.mock('../../components/cards/SeriesCard', () => ({
  default: ({ series, onClick }) => (
    <div data-testid="series-card" onClick={() => onClick(series)}>
      <div>{series.name}</div>
    </div>
  )
}));

vi.mock('@mantine/core', () => {
  const gridComponent = ({ children, ...props }) => <div {...props}>{children}</div>;
  gridComponent.Col = ({ children, ...props }) => <div {...props}>{children}</div>;

  return {
    Box: ({ children, ...props }) => <div {...props}>{children}</div>,
    Stack: ({ children, ...props }) => <div {...props}>{children}</div>,
    Group: ({ children, ...props }) => <div {...props}>{children}</div>,
    Flex: ({ children, ...props }) => <div {...props}>{children}</div>,
    Title: ({ children, ...props }) => <h2 {...props}>{children}</h2>,
    TextInput: ({ value, onChange, placeholder, icon }) => (
      <div>
        {icon}
        <input
          type="text"
          value={value}
          onChange={onChange}
          placeholder={placeholder}
        />
      </div>
    ),
    Select: ({ value, onChange, data, label, placeholder }) => (
      <div>
        {label && <label>{label}</label>}
        <select
          value={value}
          onChange={(e) => onChange?.(e.target.value)}
          aria-label={placeholder || label}
        >
          {data?.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
    ),
    SegmentedControl: ({ value, onChange, data }) => (
      <div>
        {data.map((item) => (
          <button
            key={item.value}
            onClick={() => onChange(item.value)}
            data-active={value === item.value}
          >
            {item.label}
          </button>
        ))}
      </div>
    ),
    Pagination: ({ page, onChange, total }) => (
      <div data-testid="pagination">
        <button onClick={() => onChange(page - 1)} disabled={page === 1}>
          Prev
        </button>
        <span>{page} of {total}</span>
        <button onClick={() => onChange(page + 1)} disabled={page === total}>
          Next
        </button>
      </div>
    ),
    Grid: gridComponent,
    GridCol: gridComponent.Col,
    Loader: () => <div data-testid="loader">Loading...</div>,
    LoadingOverlay: ({ visible }) =>
      visible ? <div data-testid="loading-overlay">Loading...</div> : null,
  };
});

vi.mock('../../utils/pages/VODsUtils.js', () => {
  return {
    filterCategoriesToEnabled: vi.fn(),
    getCategoryOptions: vi.fn(),
  };
});

describe('VODsPage', () => {
  const mockFetchContent = vi.fn();
  const mockFetchCategories = vi.fn();
  const mockSetFilters = vi.fn();
  const mockSetPage = vi.fn();
  const mockSetPageSize = vi.fn();

  const defaultStoreState = {
    currentPageContent: [],
    categories: {},
    filters: { type: 'all', search: '', category: '' },
    currentPage: 1,
    totalCount: 0,
    pageSize: 12,
    setFilters: mockSetFilters,
    setPage: mockSetPage,
    setPageSize: mockSetPageSize,
    fetchContent: mockFetchContent,
    fetchCategories: mockFetchCategories,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mockFetchContent.mockResolvedValue();
    mockFetchCategories.mockResolvedValue();
    filterCategoriesToEnabled.mockReturnValue({});
    getCategoryOptions.mockReturnValue([]);
    useVODStore.mockImplementation((selector) => selector(defaultStoreState));
    localStorage.clear();
  });

  it('renders the page title', async () => {
    render(<VODsPage />);
    await screen.findByText('Video on Demand');
  });

  it('fetches categories on mount', async () => {
    render(<VODsPage />);
    await waitFor(() => {
      expect(mockFetchCategories).toHaveBeenCalledTimes(1);
    });
  });

  it('fetches content on mount', async () => {
    render(<VODsPage />);
    await waitFor(() => {
      expect(mockFetchContent).toHaveBeenCalledTimes(1);
    });
  });

  it('displays loader during initial load', async () => {
    render(<VODsPage />);
    await screen.findByTestId('loader');
  });

  it('displays content after loading', async () => {
    const stateWithContent = {
      ...defaultStoreState,
      currentPageContent: [
        { id: 1, name: 'Movie 1', contentType: 'movie' },
        { id: 2, name: 'Series 1', contentType: 'series' },
      ],
    };
    useVODStore.mockImplementation((selector) => selector(stateWithContent));

    render(<VODsPage />);

    await waitFor(() => {
      expect(screen.getByText('Movie 1')).toBeInTheDocument();
      expect(screen.getByText('Series 1')).toBeInTheDocument();
    });
  });

  it('renders VOD cards for movies', async () => {
    const stateWithMovies = {
      ...defaultStoreState,
      currentPageContent: [{ id: 1, name: 'Movie 1', contentType: 'movie' }],
    };
    useVODStore.mockImplementation((selector) => selector(stateWithMovies));

    render(<VODsPage />);

    await waitFor(() => {
      expect(screen.getByTestId('vod-card')).toBeInTheDocument();
    });
  });

  it('renders series cards for series', async () => {
    const stateWithSeries = {
      ...defaultStoreState,
      currentPageContent: [
        { id: 1, name: 'Series 1', contentType: 'series' },
      ],
    };
    useVODStore.mockImplementation((selector) => selector(stateWithSeries));

    render(<VODsPage />);

    await waitFor(() => {
      expect(screen.getByTestId('series-card')).toBeInTheDocument();
    });
  });

  it('opens VOD modal when VOD card is clicked', async () => {
    const stateWithMovies = {
      ...defaultStoreState,
      currentPageContent: [
        { id: 1, name: 'Test Movie', contentType: 'movie' },
      ],
    };
    useVODStore.mockImplementation((selector) => selector(stateWithMovies));

    render(<VODsPage />);

    await waitFor(() => {
      fireEvent.click(screen.getByTestId('vod-card'));
    });

    expect(screen.getByTestId('vod-modal')).toBeInTheDocument();
    expect(screen.getByTestId('vod-name')).toHaveTextContent('Test Movie');
  });

  it('opens series modal when series card is clicked', async () => {
    const stateWithSeries = {
      ...defaultStoreState,
      currentPageContent: [
        { id: 1, name: 'Test Series', contentType: 'series' },
      ],
    };
    useVODStore.mockImplementation((selector) => selector(stateWithSeries));

    render(<VODsPage />);

    await waitFor(() => {
      fireEvent.click(screen.getByTestId('series-card'));
    });

    expect(screen.getByTestId('series-modal')).toBeInTheDocument();
    expect(screen.getByTestId('series-name')).toHaveTextContent('Test Series');
  });

  it('closes VOD modal when close button is clicked', async () => {
    const stateWithMovies = {
      ...defaultStoreState,
      currentPageContent: [
        { id: 1, name: 'Test Movie', contentType: 'movie' },
      ],
    };
    useVODStore.mockImplementation((selector) => selector(stateWithMovies));

    render(<VODsPage />);

    await waitFor(() => {
      fireEvent.click(screen.getByTestId('vod-card'));
    });

    fireEvent.click(screen.getByText('Close'));

    expect(screen.queryByTestId('vod-modal')).not.toBeInTheDocument();
  });

  it('closes series modal when close button is clicked', async () => {
    const stateWithSeries = {
      ...defaultStoreState,
      currentPageContent: [
        { id: 1, name: 'Test Series', contentType: 'series' },
      ],
    };
    useVODStore.mockImplementation((selector) => selector(stateWithSeries));

    render(<VODsPage />);

    await waitFor(() => {
      fireEvent.click(screen.getByTestId('series-card'));
    });

    fireEvent.click(screen.getByText('Close'));

    expect(screen.queryByTestId('series-modal')).not.toBeInTheDocument();
  });

  it('updates filters when search input changes', async () => {
    render(<VODsPage />);

    const searchInput = screen.getByPlaceholderText('Search VODs...');
    fireEvent.change(searchInput, { target: { value: 'test search' } });

    await waitFor(() => {
      expect(mockSetFilters).toHaveBeenCalledWith({ search: 'test search' });
    });
  });

  it('updates filters and resets page when type changes', async () => {
    render(<VODsPage />);

    const moviesButton = screen.getByText('Movies');
    fireEvent.click(moviesButton);

    await waitFor(() => {
      expect(mockSetFilters).toHaveBeenCalledWith({
        type: 'movies',
        category: '',
      });
      expect(mockSetPage).toHaveBeenCalledWith(1);
    });
  });

  it('updates filters and resets page when category changes', async () => {
    getCategoryOptions.mockReturnValue([
      { value: 'action', label: 'Action' },
    ]);

    render(<VODsPage />);

    const categorySelect = screen.getByLabelText('Category');
    fireEvent.change(categorySelect, { target: { value: 'action' } });

    await waitFor(() => {
      expect(mockSetFilters).toHaveBeenCalledWith({ category: 'action' });
      expect(mockSetPage).toHaveBeenCalledWith(1);
    });
  });

  it('updates page size and saves to localStorage', async () => {
    render(<VODsPage />);

    const pageSizeSelect = screen.getByLabelText('Page Size');
    fireEvent.change(pageSizeSelect, { target: { value: '24' } });

    await waitFor(() => {
      expect(mockSetPageSize).toHaveBeenCalledWith(24);
      expect(localStorage.getItem('vodsPageSize')).toBe('24');
    });
  });

  it('loads page size from localStorage on mount', async () => {
    localStorage.setItem('vodsPageSize', '48');

    render(<VODsPage />);

    await waitFor(() => {
      expect(mockSetPageSize).toHaveBeenCalledWith(48);
    });
  });

  it('displays pagination when total pages > 1', async () => {
    const stateWithPagination = {
      ...defaultStoreState,
      currentPageContent: [{ id: 1, name: 'Movie 1', contentType: 'movie' }],
      totalCount: 25,
      pageSize: 12,
    };
    useVODStore.mockImplementation((selector) =>
      selector(stateWithPagination)
    );

    render(<VODsPage />);

    await waitFor(() => {
      expect(screen.getByTestId('pagination')).toBeInTheDocument();
    });
  });

  it('does not display pagination when total pages <= 1', async () => {
    const stateNoPagination = {
      ...defaultStoreState,
      currentPageContent: [{ id: 1, name: 'Movie 1', contentType: 'movie' }],
      totalCount: 5,
      pageSize: 12,
    };
    useVODStore.mockImplementation((selector) => selector(stateNoPagination));

    render(<VODsPage />);

    await waitFor(() => {
      expect(screen.queryByTestId('pagination')).not.toBeInTheDocument();
    });
  });

  it('changes page when pagination is clicked', async () => {
    const stateWithPagination = {
      ...defaultStoreState,
      currentPageContent: [{ id: 1, name: 'Movie 1', contentType: 'movie' }],
      totalCount: 25,
      pageSize: 12,
      currentPage: 1,
    };
    useVODStore.mockImplementation((selector) =>
      selector(stateWithPagination)
    );

    render(<VODsPage />);

    await waitFor(() => {
      fireEvent.click(screen.getByText('Next'));
    });

    expect(mockSetPage).toHaveBeenCalledWith(2);
  });

  it('refetches content when filters change', async () => {
    const { rerender } = render(<VODsPage />);

    const updatedState = {
      ...defaultStoreState,
      filters: { type: 'movies', search: '', category: '' },
    };
    useVODStore.mockImplementation((selector) => selector(updatedState));

    rerender(<VODsPage />);

    await waitFor(() => {
      expect(mockFetchContent).toHaveBeenCalledTimes(2);
    });
  });

  it('refetches content when page changes', async () => {
    const { rerender } = render(<VODsPage />);

    const updatedState = {
      ...defaultStoreState,
      currentPage: 2,
    };
    useVODStore.mockImplementation((selector) => selector(updatedState));

    rerender(<VODsPage />);

    await waitFor(() => {
      expect(mockFetchContent).toHaveBeenCalledTimes(2);
    });
  });

  it('refetches content when page size changes', async () => {
    const { rerender } = render(<VODsPage />);

    const updatedState = {
      ...defaultStoreState,
      pageSize: 24,
    };
    useVODStore.mockImplementation((selector) => selector(updatedState));

    rerender(<VODsPage />);

    await waitFor(() => {
      expect(mockFetchContent).toHaveBeenCalledTimes(2);
    });
  });
});
