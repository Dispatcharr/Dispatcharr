import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import VODsPage from '../VODs';
import useAuthStore from '../../store/auth';
import useVODStore from '../../store/useVODStore';
import {
  hideNotification,
  showNotification,
} from '../../utils/notificationUtils.js';
import { USER_LEVELS } from '../../constants';
import {
  filterCategoriesToEnabled,
  getCategoryOptions,
} from '../../utils/pages/VODsUtils.js';

vi.mock('../../store/useVODStore');
vi.mock('../../store/auth');
vi.mock('../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
  hideNotification: vi.fn(),
}));

vi.mock('../../components/SeriesModal', () => ({
  default: ({ opened, series, onClose }) =>
    opened ? (
      <div data-testid="series-modal">
        <div data-testid="series-name">{series?.name}</div>
        <button onClick={onClose}>Close</button>
      </div>
    ) : null,
}));
vi.mock('../../components/VODModal', () => ({
  default: ({ opened, vod, onClose }) =>
    opened ? (
      <div data-testid="vod-modal">
        <div data-testid="vod-name">{vod?.name}</div>
        <button onClick={onClose}>Close</button>
      </div>
    ) : null,
}));
vi.mock('../../components/cards/VODCard', () => ({
  default: ({ vod, onClick }) => (
    <div data-testid="vod-card" onClick={() => onClick(vod)}>
      <div>{vod.name}</div>
    </div>
  ),
}));
vi.mock('../../components/cards/SeriesCard', () => ({
  default: ({ series, onClick }) => (
    <div data-testid="series-card" onClick={() => onClick(series)}>
      <div>{series.name}</div>
    </div>
  ),
}));

vi.mock('@mantine/core', () => {
  const gridComponent = ({ children, ...props }) => (
    <div {...props}>{children}</div>
  );
  gridComponent.Col = ({ children, ...props }) => (
    <div {...props}>{children}</div>
  );

  return {
    Box: ({ children, ...props }) => <div {...props}>{children}</div>,
    Stack: ({ children, ...props }) => <div {...props}>{children}</div>,
    Group: ({ children, ...props }) => <div {...props}>{children}</div>,
    Flex: ({ children, ...props }) => <div {...props}>{children}</div>,
    Title: ({ children, ...props }) => <h2 {...props}>{children}</h2>,
    Text: ({ children, role }) => <span role={role}>{children}</span>,
    Button: ({ children, onClick, disabled }) => (
      <button onClick={onClick} disabled={disabled}>
        {children}
      </button>
    ),
    TextInput: ({ value, onChange, placeholder, leftSection }) => (
      <div>
        {leftSection}
        <input
          type="text"
          value={value}
          onChange={onChange}
          placeholder={placeholder}
        />
      </div>
    ),
    Select: ({
      value,
      onChange,
      data,
      label,
      placeholder,
      'aria-label': ariaLabel,
    }) => (
      <div>
        {label && <label>{label}</label>}
        <select
          value={value}
          onChange={(e) => onChange?.(e.target.value)}
          aria-label={ariaLabel || placeholder || label}
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
      <div data-testid="type-control">
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
    Pagination: ({ value: page, onChange, total }) => (
      <div data-testid="pagination">
        <button onClick={() => onChange(page - 1)} disabled={page === 1}>
          Prev
        </button>
        <span>
          {page} of {total}
        </span>
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

const mockAdminUser = {
  user_level: USER_LEVELS.ADMIN,
  custom_properties: {},
};

const renderVODsPage = (initialPath = '/vods') =>
  render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/vods" element={<VODsPage />} />
        <Route path="/channels" element={<div>Channels page</div>} />
      </Routes>
    </MemoryRouter>
  );

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
    categoriesError: null,
    categoriesLoading: false,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mockFetchContent.mockResolvedValue();
    mockFetchCategories.mockResolvedValue();
    filterCategoriesToEnabled.mockReturnValue({});
    getCategoryOptions.mockReturnValue([]);
    useVODStore.mockImplementation((selector) => selector(defaultStoreState));
    useAuthStore.mockImplementation((selector) =>
      selector({ user: mockAdminUser })
    );
    localStorage.clear();
    useVODStore.getState = vi.fn(() => ({ error: null }));
  });

  it('renders the page title', async () => {
    renderVODsPage();
    await screen.findByText('Library');
  });

  it('redirects to channels when VOD access is denied', async () => {
    useAuthStore.mockImplementation((selector) =>
      selector({
        user: {
          user_level: USER_LEVELS.STANDARD,
          custom_properties: {
            vod_movies_enabled: false,
            vod_series_enabled: false,
          },
        },
      })
    );

    renderVODsPage();

    await screen.findByText('Channels page');
    expect(screen.queryByText('Library')).not.toBeInTheDocument();
    expect(mockFetchContent).not.toHaveBeenCalled();
  });

  it('hides type control when only movies are enabled', async () => {
    useAuthStore.mockImplementation((selector) =>
      selector({
        user: {
          user_level: USER_LEVELS.STANDARD,
          custom_properties: {
            vod_movies_enabled: true,
            vod_series_enabled: false,
          },
        },
      })
    );
    useVODStore.mockImplementation((selector) =>
      selector({
        ...defaultStoreState,
        filters: { type: 'movies', search: '', category: '' },
      })
    );

    renderVODsPage();

    await screen.findByText('Library');
    expect(screen.queryByTestId('type-control')).not.toBeInTheDocument();
  });

  it('shows All / Movies / Series when both VOD types are enabled', async () => {
    useAuthStore.mockImplementation((selector) =>
      selector({
        user: {
          user_level: USER_LEVELS.STANDARD,
          custom_properties: {},
        },
      })
    );

    renderVODsPage();

    await screen.findByText('Library');
    expect(screen.getByTestId('type-control')).toBeInTheDocument();
    expect(screen.getByText('All')).toBeInTheDocument();
    expect(screen.getByText('Movies')).toBeInTheDocument();
    expect(screen.getByText('Series')).toBeInTheDocument();
  });

  it('forces movies type when series is disabled', async () => {
    useAuthStore.mockImplementation((selector) =>
      selector({
        user: {
          user_level: USER_LEVELS.STANDARD,
          custom_properties: {
            vod_movies_enabled: true,
            vod_series_enabled: false,
          },
        },
      })
    );

    renderVODsPage();

    await waitFor(() => {
      expect(mockSetFilters).toHaveBeenCalledWith({
        type: 'movies',
        category: '',
      });
    });
    expect(mockFetchContent).not.toHaveBeenCalled();
  });

  it('fetches categories on mount', async () => {
    renderVODsPage();
    await waitFor(() => {
      expect(mockFetchCategories).toHaveBeenCalledTimes(1);
    });
  });

  it('fetches content on mount', async () => {
    renderVODsPage();
    await waitFor(() => {
      expect(mockFetchContent).toHaveBeenCalledTimes(1);
    });
  });

  it('shows an initial loading status without a spinner or a false zero count', async () => {
    mockFetchContent.mockImplementationOnce(() => new Promise(() => {}));
    renderVODsPage();
    await screen.findByText('Loading library…');
    expect(screen.queryByTestId('loader')).not.toBeInTheDocument();
    expect(screen.queryByText('0–0 of 0')).not.toBeInTheDocument();
  });

  it('explains the empty library', async () => {
    renderVODsPage();
    await screen.findByText('No titles found.');
    expect(
      screen.getByText('No movies or series have been imported yet.')
    ).toBeInTheDocument();
  });

  it('reports load errors as a notification and supports retry', async () => {
    useVODStore.getState.mockReturnValue({ error: 'Failed to load content.' });
    renderVODsPage();
    await screen.findByText('Library could not be loaded.');
    expect(showNotification).toHaveBeenCalledWith(
      expect.objectContaining({
        color: 'red',
        message: 'Failed to load content.',
        autoClose: false,
      })
    );
    useVODStore.getState.mockReturnValue({ error: null });
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await screen.findByText('No titles found.');
    expect(mockFetchContent).toHaveBeenCalledTimes(2);
  });

  it('ignores invalid stored page sizes', async () => {
    localStorage.setItem('vodsPageSize', '-12');
    renderVODsPage();
    await screen.findByLabelText('Items per page');
    expect(mockSetPageSize).not.toHaveBeenCalled();
  });

  it('reports category failures independently without hiding successfully loaded titles', async () => {
    let state = {
      ...defaultStoreState,
      currentPageContent: [{ id: 1, name: 'Movie 1', contentType: 'movie' }],
      totalCount: 1,
      categoriesError: null,
    };
    useVODStore.mockImplementation((selector) => selector(state));
    const { rerender } = render(
      <MemoryRouter>
        <VODsPage />
      </MemoryRouter>
    );
    await screen.findByText('Movie 1');
    state = { ...state, categoriesError: 'Failed to load categories.' };
    rerender(
      <MemoryRouter>
        <VODsPage />
      </MemoryRouter>
    );
    expect(screen.getByText('Movie 1')).toBeInTheDocument();
    expect(
      screen.queryByText('Library could not be loaded.')
    ).not.toBeInTheDocument();
    expect(showNotification).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'vod-library-categories-error',
        title: 'Library categories could not be loaded',
        color: 'red',
        autoClose: false,
      })
    );
    fireEvent.click(screen.getByRole('button', { name: 'Retry categories' }));
    expect(mockFetchCategories).toHaveBeenCalledTimes(2);
    expect(mockFetchContent).toHaveBeenCalledTimes(1);
    state = { ...state, categoriesLoading: true };
    rerender(
      <MemoryRouter>
        <VODsPage />
      </MemoryRouter>
    );
    expect(
      screen.getByRole('button', { name: 'Retrying categories…' })
    ).toBeDisabled();
    state = { ...state, categoriesLoading: false, categoriesError: null };
    rerender(
      <MemoryRouter>
        <VODsPage />
      </MemoryRouter>
    );
    expect(
      screen.queryByRole('button', { name: 'Retry categories' })
    ).not.toBeInTheDocument();
    expect(hideNotification).toHaveBeenCalledWith(
      'vod-library-categories-error'
    );
    expect(screen.getByText('Movie 1')).toBeInTheDocument();
  });

  it('reports a category failure before content finishes without treating it as a content error', async () => {
    useVODStore.mockImplementation((selector) =>
      selector({
        ...defaultStoreState,
        categoriesError: 'Failed to load categories.',
      })
    );
    mockFetchContent.mockImplementationOnce(() => new Promise(() => {}));
    renderVODsPage();
    await screen.findByText('Loading library…');
    expect(
      screen.getByRole('button', { name: 'Retry categories' })
    ).toBeInTheDocument();
    expect(showNotification).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'vod-library-categories-error' })
    );
    expect(showNotification).not.toHaveBeenCalledWith(
      expect.objectContaining({ id: 'vod-library-load-error' })
    );
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

    renderVODsPage();

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

    renderVODsPage();

    await waitFor(() => {
      expect(screen.getByTestId('vod-card')).toBeInTheDocument();
    });
  });

  it('renders series cards for series', async () => {
    const stateWithSeries = {
      ...defaultStoreState,
      currentPageContent: [{ id: 1, name: 'Series 1', contentType: 'series' }],
    };
    useVODStore.mockImplementation((selector) => selector(stateWithSeries));

    renderVODsPage();

    await waitFor(() => {
      expect(screen.getByTestId('series-card')).toBeInTheDocument();
    });
  });

  it('opens VOD modal when VOD card is clicked', async () => {
    const stateWithMovies = {
      ...defaultStoreState,
      currentPageContent: [{ id: 1, name: 'Test Movie', contentType: 'movie' }],
    };
    useVODStore.mockImplementation((selector) => selector(stateWithMovies));

    renderVODsPage();

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

    renderVODsPage();

    await waitFor(() => {
      fireEvent.click(screen.getByTestId('series-card'));
    });

    expect(screen.getByTestId('series-modal')).toBeInTheDocument();
    expect(screen.getByTestId('series-name')).toHaveTextContent('Test Series');
  });

  it('closes VOD modal when close button is clicked', async () => {
    const stateWithMovies = {
      ...defaultStoreState,
      currentPageContent: [{ id: 1, name: 'Test Movie', contentType: 'movie' }],
    };
    useVODStore.mockImplementation((selector) => selector(stateWithMovies));

    renderVODsPage();

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

    renderVODsPage();

    await waitFor(() => {
      fireEvent.click(screen.getByTestId('series-card'));
    });

    fireEvent.click(screen.getByText('Close'));

    expect(screen.queryByTestId('series-modal')).not.toBeInTheDocument();
  });

  it('updates filters when search input changes', async () => {
    renderVODsPage();

    const searchInput = screen.getByPlaceholderText('Search VODs...');
    fireEvent.change(searchInput, { target: { value: 'test search' } });

    await waitFor(() => {
      expect(mockSetFilters).toHaveBeenCalledWith({ search: 'test search' });
    });
  });

  it('updates filters and resets page when type changes', async () => {
    renderVODsPage();

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
    getCategoryOptions.mockReturnValue([{ value: 'action', label: 'Action' }]);

    renderVODsPage();

    const categorySelect = screen.getByLabelText('Category');
    fireEvent.change(categorySelect, { target: { value: 'action' } });

    await waitFor(() => {
      expect(mockSetFilters).toHaveBeenCalledWith({ category: 'action' });
      expect(mockSetPage).toHaveBeenCalledWith(1);
    });
  });

  it('updates page size and saves to localStorage', async () => {
    renderVODsPage();

    const pageSizeSelect = await screen.findByLabelText('Items per page');
    fireEvent.change(pageSizeSelect, { target: { value: '24' } });

    await waitFor(() => {
      expect(mockSetPageSize).toHaveBeenCalledWith(24);
      expect(localStorage.getItem('vodsPageSize')).toBe('24');
    });
  });

  it('hydrates page size from localStorage then fetches once', async () => {
    localStorage.setItem('vodsPageSize', '48');

    let storeState = { ...defaultStoreState, pageSize: 12 };
    mockSetPageSize.mockImplementation((size) => {
      storeState = {
        ...storeState,
        pageSize: Number(size),
        currentPage: 1,
      };
    });
    useVODStore.mockImplementation((selector) => selector(storeState));

    renderVODsPage();

    await waitFor(() => {
      expect(mockSetPageSize).toHaveBeenCalledWith(48);
      expect(mockFetchContent).toHaveBeenCalledTimes(1);
    });
  });

  it('fetches once when localStorage page size already matches', async () => {
    localStorage.setItem('vodsPageSize', '12');

    renderVODsPage();

    await waitFor(() => {
      expect(mockFetchContent).toHaveBeenCalledTimes(1);
    });
    expect(mockSetPageSize).not.toHaveBeenCalled();
  });

  it('displays pagination when total pages > 1', async () => {
    const stateWithPagination = {
      ...defaultStoreState,
      currentPageContent: [{ id: 1, name: 'Movie 1', contentType: 'movie' }],
      totalCount: 25,
      pageSize: 12,
    };
    useVODStore.mockImplementation((selector) => selector(stateWithPagination));

    renderVODsPage();

    await waitFor(() => {
      expect(screen.getByTestId('pagination')).toBeInTheDocument();
    });
  });

  it('keeps the count and page size available on a single page', async () => {
    const stateNoPagination = {
      ...defaultStoreState,
      currentPageContent: [{ id: 1, name: 'Movie 1', contentType: 'movie' }],
      totalCount: 5,
      pageSize: 12,
    };
    useVODStore.mockImplementation((selector) => selector(stateNoPagination));

    renderVODsPage();

    await waitFor(() => {
      expect(screen.getByText('1–5 of 5')).toBeInTheDocument();
      expect(screen.getByLabelText('Items per page')).toBeInTheDocument();
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
    useVODStore.mockImplementation((selector) => selector(stateWithPagination));

    renderVODsPage();

    await waitFor(() => {
      fireEvent.click(screen.getByText('Next'));
    });

    expect(mockSetPage).toHaveBeenCalledWith(2);
  });

  it('refetches content when filters change', async () => {
    const { rerender } = renderVODsPage();

    const updatedState = {
      ...defaultStoreState,
      filters: { type: 'movies', search: '', category: '' },
    };
    useVODStore.mockImplementation((selector) => selector(updatedState));

    rerender(
      <MemoryRouter initialEntries={['/vods']}>
        <Routes>
          <Route path="/vods" element={<VODsPage />} />
          <Route path="/channels" element={<div>Channels page</div>} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockFetchContent).toHaveBeenCalledTimes(2);
    });
  });

  it('refetches content when page changes', async () => {
    const { rerender } = renderVODsPage();

    const updatedState = {
      ...defaultStoreState,
      currentPage: 2,
    };
    useVODStore.mockImplementation((selector) => selector(updatedState));

    rerender(
      <MemoryRouter initialEntries={['/vods']}>
        <Routes>
          <Route path="/vods" element={<VODsPage />} />
          <Route path="/channels" element={<div>Channels page</div>} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockFetchContent).toHaveBeenCalledTimes(2);
    });
  });

  it('refetches content when page size changes', async () => {
    const { rerender } = renderVODsPage();

    const updatedState = {
      ...defaultStoreState,
      pageSize: 24,
    };
    useVODStore.mockImplementation((selector) => selector(updatedState));

    rerender(
      <MemoryRouter initialEntries={['/vods']}>
        <Routes>
          <Route path="/vods" element={<VODsPage />} />
          <Route path="/channels" element={<div>Channels page</div>} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockFetchContent).toHaveBeenCalledTimes(2);
    });
  });
});
