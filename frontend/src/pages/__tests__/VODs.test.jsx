import React from 'react';
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

vi.mock('../../store/useVODStore', () => ({ default: vi.fn() }));
vi.mock('../../store/auth', () => ({ default: vi.fn() }));
vi.mock('../../store/playlists', () => ({ default: vi.fn() }));
vi.mock('../../api', () => ({
  default: {
    bulkUpdateVODSourceMetadata: vi.fn(),
    updateVODRelationTmdbMatch: vi.fn(),
    getVODMetadataStatus: vi.fn(),
    getVODFilterOptions: vi.fn(),
  },
}));
vi.mock('../../utils/pages/VODsUtils.js', () => ({
  filterCategoriesToEnabled: vi.fn(() => ({})),
  getCategoryOptions: vi.fn(() => []),
}));
vi.mock('../../utils/notificationUtils', () => ({
  showNotification: vi.fn(),
}));
vi.mock('../../components/LanguagePicker.jsx', () => ({
  default: ({ label, value = [], onChange, disabled }) => (
    <label>
      {label}
      <input
        aria-label={label}
        value={value.join(',')}
        disabled={disabled}
        onChange={(event) =>
          onChange(event.target.value.split(',').filter(Boolean))
        }
      />
    </label>
  ),
  LanguageSelect: ({ label, value, onChange }) => (
    <label>
      {label}
      <select
        aria-label={label}
        value={value || ''}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="" />
        <option value="ger">GER — German</option>
        <option value="eng">ENG — English</option>
      </select>
    </label>
  ),
}));
vi.mock('../../components/ErrorBoundary.jsx', () => ({
  default: ({ children }) => children,
}));
vi.mock('../../components/SeriesModal', () => ({
  default: ({ opened, series }) =>
    opened ? <div data-testid="series-modal">{series?.name}</div> : null,
}));
vi.mock('../../components/VODModal', () => ({
  default: ({ opened, vod }) =>
    opened ? <div data-testid="movie-modal">{vod?.name}</div> : null,
}));
vi.mock('../../components/VODSourceManagerModal', () => ({
  default: ({ opened }) =>
    opened ? <div data-testid="history-modal">History</div> : null,
}));
vi.mock('../../components/VODOutputProfilesModal', () => ({
  default: ({ opened }) =>
    opened ? <div data-testid="profiles-modal">Profiles</div> : null,
}));
vi.mock('../../components/VODMetadataModal', () => ({
  default: ({ opened }) =>
    opened ? <div data-testid="metadata-modal">Metadata</div> : null,
}));
vi.mock('../../components/VideoFeaturePicker.jsx', () => ({
  default: ({ label }) => <div>{label}</div>,
}));
vi.mock('lucide-react', () => ({
  DatabaseZap: () => null,
  Eye: () => null,
  Filter: () => null,
  History: () => null,
  LayoutGrid: (props) => <span {...props}>Poster wall</span>,
  List: (props) => <span {...props}>List view</span>,
  LockKeyhole: (props) => <span {...props}>Locked</span>,
  Play: () => null,
  RefreshCw: () => null,
  Search: () => null,
  SlidersHorizontal: () => null,
  Wrench: () => null,
}));
vi.mock('@mantine/hooks', () => ({
  useDebouncedValue: (value) => [value],
  useDisclosure: (initial = false) => {
    const [opened, setOpened] = React.useState(initial);
    return [
      opened,
      { open: () => setOpened(true), close: () => setOpened(false) },
    ];
  },
}));
vi.mock('@mantine/core', () => {
  const Wrapper = ({ children }) => <div>{children}</div>;
  const Modal = ({ opened, children, title }) =>
    opened ? (
      <div>
        <h3>{title}</h3>
        {children}
      </div>
    ) : null;
  const Select = ({ label, placeholder, value, onChange, data = [] }) => (
    <label>
      {label}
      <select
        aria-label={label || placeholder}
        value={value || ''}
        onChange={(event) => onChange?.(event.target.value || null)}
      >
        <option value="" />
        {data.map((item) => {
          const option =
            typeof item === 'string' ? { value: item, label: item } : item;
          return (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          );
        })}
      </select>
    </label>
  );
  return {
    Alert: Wrapper,
    ActionIcon: ({ children, onClick, 'aria-label': ariaLabel }) => (
      <button aria-label={ariaLabel} onClick={onClick}>
        {children}
      </button>
    ),
    Box: Wrapper,
    Button: ({ children, onClick, disabled, loading }) => (
      <button onClick={onClick} disabled={disabled || loading}>
        {children}
      </button>
    ),
    Checkbox: ({ checked, onChange, 'aria-label': ariaLabel }) => (
      <input
        type="checkbox"
        aria-label={ariaLabel}
        checked={checked}
        onChange={onChange}
      />
    ),
    Flex: Wrapper,
    Group: Wrapper,
    Image: ({ src }) => <img src={src} />,
    Loader: () => <div data-testid="loader" />,
    LoadingOverlay: () => null,
    Modal,
    MultiSelect: ({ label, value = [], onChange, data = [], disabled }) => (
      <label>
        {label}
        <select
          aria-label={label}
          multiple
          value={value}
          disabled={disabled}
          onChange={(event) =>
            onChange?.(
              Array.from(event.target.selectedOptions, (option) => option.value)
            )
          }
        >
          {data.map((item) => {
            const option =
              typeof item === 'string' ? { value: item, label: item } : item;
            return (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            );
          })}
        </select>
      </label>
    ),
    Pagination: ({ value, onChange, total }) => (
      <button data-testid="pagination" onClick={() => onChange(value + 1)}>
        {total}
      </button>
    ),
    Popover: Wrapper,
    PopoverDropdown: Wrapper,
    PopoverTarget: Wrapper,
    SegmentedControl: ({ value, onChange, data }) => (
      <div data-testid="type-control">
        {data.map((item) => (
          <button
            key={item.value}
            data-active={value === item.value}
            onClick={() => onChange(item.value)}
          >
            {item.label}
          </button>
        ))}
      </div>
    ),
    Select,
    SimpleGrid: Wrapper,
    ScrollArea: ({ children, 'data-testid': testId }) => (
      <div data-testid={testId}>{children}</div>
    ),
    Stack: Wrapper,
    Table: Wrapper,
    TableTbody: Wrapper,
    TableTd: Wrapper,
    TableTh: Wrapper,
    TableThead: Wrapper,
    TableTr: Wrapper,
    Text: Wrapper,
    TextInput: ({ value, onChange, placeholder, label, type }) => (
      <label>
        {label}
        <input
          aria-label={label}
          type={type}
          value={value}
          onChange={onChange}
          placeholder={placeholder}
        />
      </label>
    ),
    Title: ({ children }) => <h2>{children}</h2>,
    Tooltip: Wrapper,
  };
});

import API from '../../api';
import useAuthStore from '../../store/auth';
import usePlaylistsStore from '../../store/playlists';
import useVODStore from '../../store/useVODStore';
import { showVODProfileRebuildNotice } from '../../utils/vodProfileUpdates.js';
import VODsPage from '../VODs';

const renderVODs = () =>
  render(
    <MemoryRouter initialEntries={['/vods']}>
      <Routes>
        <Route path="/vods" element={<VODsPage />} />
        <Route
          path="/vods/profiles"
          element={<div data-testid="profiles-page">Profiles</div>}
        />
      </Routes>
    </MemoryRouter>
  );

describe('VODsPage list and bulk editing', () => {
  const fetchContent = vi.fn().mockResolvedValue(undefined);
  const fetchCategories = vi.fn().mockResolvedValue(undefined);
  const setFilters = vi.fn();
  const setPage = vi.fn();
  const setPageSize = vi.fn();
  const state = {
    currentPageContent: [
      {
        id: 1,
        name: 'Movie A',
        contentType: 'movie',
        year: 2025,
        source_count: 3,
      },
      {
        id: 2,
        name: 'Series B',
        contentType: 'series',
        year: 2024,
        source_count: 2,
      },
    ],
    categories: {},
    filters: {
      type: 'all',
      search: '',
      category: '',
      m3u_account: '',
      audio_language: '',
      subtitle_language: '',
      resolution: '',
      container_extension: '',
      video_feature: '',
      metadata_status: '',
      genre: '',
      anime_mode: '',
      adult_mode: '',
      library_added_after: '',
      representation: 'canonical',
    },
    currentPage: 1,
    totalCount: 30,
    pageSize: 24,
    setFilters,
    setPage,
    setPageSize,
    fetchContent,
    fetchCategories,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.removeItem('vodsViewMode');
    localStorage.removeItem('vod-profile-rebuild-notice-suppressed');
    fetchContent.mockResolvedValue(undefined);
    fetchCategories.mockResolvedValue(undefined);
    API.bulkUpdateVODSourceMetadata.mockResolvedValue({ updated_sources: 3 });
    API.updateVODRelationTmdbMatch.mockResolvedValue({ moved_sources: 1 });
    API.getVODMetadataStatus.mockResolvedValue({ settings: {} });
    API.getVODFilterOptions.mockResolvedValue({
      audio_languages: ['ger', 'eng'],
      subtitle_languages: ['eng'],
      resolutions: ['1080p'],
      container_extensions: ['mkv'],
      video_features: ['hdr'],
    });
    state.filters.representation = 'canonical';
    state.filters.metadata_status = '';
    state.currentPageContent[0].relation_id = undefined;
    state.currentPageContent[0].is_variant = false;
    state.currentPageContent[0].clean_title = '';
    state.currentPageContent[0].tmdb_status = '';
    state.currentPageContent[0].metadata_auto_locked = false;
    state.currentPageContent[1].relation_id = undefined;
    state.currentPageContent[1].is_variant = false;
    state.currentPageContent[1].clean_title = '';
    state.currentPageContent[1].tmdb_status = '';
    state.currentPageContent[1].metadata_auto_locked = false;
    useVODStore.mockImplementation((selector) => selector(state));
    useAuthStore.mockImplementation((selector) =>
      selector({ user: { id: 1, user_level: 10 } })
    );
    usePlaylistsStore.mockImplementation((selector) =>
      selector({ playlists: [], fetchPlaylists: vi.fn() })
    );
  });

  it('renders movies and series as list rows and loads data', async () => {
    renderVODs();
    expect(await screen.findByText('Movie A')).toBeInTheDocument();
    expect(screen.getByText('Series B')).toBeInTheDocument();
    expect(screen.getByText('Sources')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getAllByText('2').length).toBeGreaterThan(0);
    expect(screen.getByTestId('vod-list-scroll')).toBeInTheDocument();
    expect(fetchCategories).toHaveBeenCalled();
    expect(fetchContent).toHaveBeenCalled();
  });

  it('opens the correct detail dialog from a row', async () => {
    renderVODs();
    await screen.findByText('Movie A');
    fireEvent.click(screen.getByLabelText('Details Movie A'));
    expect(await screen.findByTestId('movie-modal')).toHaveTextContent(
      'Movie A'
    );
    fireEvent.click(screen.getByLabelText('Details Series B'));
    expect(await screen.findByTestId('series-modal')).toHaveTextContent(
      'Series B'
    );
  });

  it('switches to a paginated poster wall and remembers the view', async () => {
    renderVODs();
    await screen.findByText('Movie A');
    fireEvent.click(screen.getByLabelText('Poster wall'));
    expect(localStorage.getItem('vodsViewMode')).toBe('posters');
    expect(screen.getByText('Movie · 2025')).toBeInTheDocument();
    expect(screen.getByText('3 sources')).toBeInTheDocument();
    expect(screen.getByTestId('pagination')).toBeInTheDocument();
  });

  it('does not allow selecting variants in the poster wall', async () => {
    state.filters.representation = 'variants';
    state.currentPageContent[0].relation_id = 101;
    state.currentPageContent[0].is_variant = true;
    state.currentPageContent[1].relation_id = 202;
    state.currentPageContent[1].is_variant = true;
    renderVODs();

    await screen.findByText('Movie A');
    fireEvent.click(screen.getByLabelText('Poster wall'));

    expect(screen.queryByLabelText('Select Movie A')).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /Edit selected/ })
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/selected/)).not.toBeInTheDocument();
  });

  it('shows the shared clean title for matched provider variants', async () => {
    state.filters.representation = 'variants';
    state.currentPageContent[0].relation_id = 101;
    state.currentPageContent[0].is_variant = true;
    state.currentPageContent[0].clean_title = 'Canonical Movie A';
    state.currentPageContent[0].tmdb_status = 'matched';
    renderVODs();

    await screen.findByText('Movie A');
    expect(screen.getByText('Clean: Canonical Movie A')).toBeInTheDocument();
  });

  it('shows an automatic metadata lock for canonical list rows', async () => {
    state.currentPageContent[0].metadata_auto_locked = true;
    renderVODs();

    await screen.findByText('Movie A');
    expect(
      screen.getByLabelText('Automatic metadata matching locked')
    ).toBeInTheDocument();
  });

  it('shows the canonical automatic metadata lock for variant list rows', async () => {
    state.filters.representation = 'variants';
    state.currentPageContent[0].relation_id = 101;
    state.currentPageContent[0].is_variant = true;
    state.currentPageContent[0].metadata_auto_locked = true;
    renderVODs();

    await screen.findByText('Movie A');
    expect(
      screen.getByLabelText('Automatic metadata matching locked')
    ).toBeInTheDocument();
  });

  it('bulk-updates selected provider variants only', async () => {
    state.filters.representation = 'variants';
    state.currentPageContent[0].relation_id = 101;
    state.currentPageContent[0].is_variant = true;
    state.currentPageContent[1].relation_id = 202;
    state.currentPageContent[1].is_variant = true;
    renderVODs();
    await screen.findByText('Movie A');
    fireEvent.click(screen.getByLabelText('Select Movie A'));
    fireEvent.click(screen.getByRole('button', { name: /Edit selected/ }));
    expect(
      screen.queryByLabelText('Move selected sources to TMDB ID')
    ).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('DUB languages'), {
      target: { value: 'ger,eng' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Apply and lock' }));
    await waitFor(() =>
      expect(API.bulkUpdateVODSourceMetadata).toHaveBeenCalledWith(
        [{ content_type: 'movie', relation_id: 101 }],
        { audio_languages: ['ger', 'eng'] },
        { filters: state.filters }
      )
    );
  });

  it('updates search and pagination through the store', async () => {
    renderVODs();
    await screen.findByText('Movie A');
    expect(screen.getByText('Rows')).toBeInTheDocument();
    expect(screen.getByText('1–24 of 30')).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText('Search VODs...'), {
      target: { value: 'avatar' },
    });
    expect(setFilters).toHaveBeenCalledWith({ search: 'avatar' });
    fireEvent.click(screen.getByTestId('pagination'));
    expect(setPage).toHaveBeenCalledWith(2);
  });

  it('explains that changed VOD data needs an output profile rebuild', async () => {
    renderVODs();
    await screen.findByText('Movie A');

    act(() =>
      showVODProfileRebuildNotice({
        profile_update: 'outdated',
        profiles_affected: 2,
      })
    );

    expect(
      await screen.findByRole('heading', {
        name: 'Output profile rebuild required',
      })
    ).toBeInTheDocument();
    expect(
      screen.getByText('2 prepared output profiles are now outdated.')
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', { name: 'Open output profiles' })
    );
    expect(await screen.findByTestId('profiles-page')).toBeInTheDocument();
  });

  it('can permanently suppress the output profile rebuild notice', async () => {
    renderVODs();
    await screen.findByText('Movie A');

    act(() =>
      showVODProfileRebuildNotice({
        profile_update: 'outdated',
        profiles_affected: 1,
      })
    );
    fireEvent.click(screen.getAllByRole('checkbox').at(-1));
    fireEvent.click(screen.getByRole('button', { name: 'Later' }));

    expect(localStorage.getItem('vod-profile-rebuild-notice-suppressed')).toBe(
      'true'
    );

    act(() =>
      showVODProfileRebuildNotice({
        profile_update: 'outdated',
        profiles_affected: 1,
      })
    );
    expect(
      screen.queryByRole('heading', {
        name: 'Output profile rebuild required',
      })
    ).not.toBeInTheDocument();
  });

  it('selects every VOD matching the active filters across pages', async () => {
    state.filters.representation = 'variants';
    state.currentPageContent[0].relation_id = 101;
    state.currentPageContent[0].is_variant = true;
    state.currentPageContent[1].relation_id = 202;
    state.currentPageContent[1].is_variant = true;
    renderVODs();
    await screen.findByText('Movie A');
    fireEvent.click(screen.getByLabelText('Select all filtered VODs'));
    expect(
      screen.getByRole('button', { name: 'Edit selected (30)' })
    ).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Edit selected (30)' }));
    fireEvent.change(screen.getAllByLabelText('Resolution').at(-1), {
      target: { value: '1080p' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Apply and lock' }));
    await waitFor(() =>
      expect(API.bulkUpdateVODSourceMetadata).toHaveBeenCalledWith(
        [],
        { resolution: '1080p' },
        {
          select_all: true,
          filters: state.filters,
          exclude_selections: [],
        }
      )
    );
  });

  it('redirects when both VOD access flags are disabled', async () => {
    useAuthStore.mockImplementation((selector) =>
      selector({
        user: {
          id: 2,
          user_level: 1,
          custom_properties: {
            vod_movies_enabled: false,
            vod_series_enabled: false,
          },
        },
      })
    );

    render(
      <MemoryRouter initialEntries={['/vods']}>
        <Routes>
          <Route path="/vods" element={<VODsPage />} />
          <Route path="/channels" element={<div>Channels page</div>} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText('Channels page')).toBeInTheDocument();
    expect(fetchCategories).not.toHaveBeenCalled();
    expect(fetchContent).not.toHaveBeenCalled();
  });

  it('locks the catalog to movies when series access is disabled', async () => {
    useAuthStore.mockImplementation((selector) =>
      selector({
        user: {
          id: 3,
          user_level: 1,
          custom_properties: {
            vod_movies_enabled: true,
            vod_series_enabled: false,
          },
        },
      })
    );

    renderVODs();

    await waitFor(() =>
      expect(setFilters).toHaveBeenCalledWith({
        type: 'movies',
        category: '',
      })
    );
    expect(fetchContent).not.toHaveBeenCalled();
  });
});
