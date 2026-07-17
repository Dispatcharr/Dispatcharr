import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../store/plugins.jsx', () => {
  const mockStore = vi.fn();
  mockStore.getState = vi.fn(() => ({ repos: [], invalidatePlugins: vi.fn() }));
  return { usePluginStore: mockStore };
});

vi.mock('../../store/settings.jsx', () => ({
  default: vi.fn(),
}));

// ── Component mocks ────────────────────────────────────────────────────────────
vi.mock('../../components/cards/AvailablePluginCard.jsx', () => ({
  default: ({ plugin }) => (
    <div data-testid="plugin-card" data-slug={plugin.slug}>
      {plugin.name}
    </div>
  ),
}));

vi.mock('../../components/modals/ManageReposModal.jsx', () => ({
  default: ({ opened, onClose }) =>
    opened ? (
      <div data-testid="manage-repos-modal">
        <button data-testid="manage-repos-close" onClick={onClose}>
          Close
        </button>
      </div>
    ) : null,
}));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

vi.mock('../../utils/pages/PluginsUtils.js', () => ({
  reloadPlugins: vi.fn(),
}));

vi.mock('../../utils/components/pluginUtils.js', () => ({
  compareVersions: vi.fn(() => 0),
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  Package: () => <svg data-testid="icon-package" />,
  RefreshCcw: () => <svg data-testid="icon-refresh" />,
  Search: () => <svg data-testid="icon-search" />,
}));

// ── @mantine/core ──────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  ActionIcon: ({ children, onClick, loading, title }) => (
    <button
      data-testid="action-icon"
      data-loading={loading}
      title={title}
      onClick={onClick}
    >
      {children}
    </button>
  ),
  AppShellMain: ({ children }) => <main>{children}</main>,
  Badge: ({ children, color, variant }) => (
    <span data-testid="badge" data-color={color} data-variant={variant}>
      {children}
    </span>
  ),
  Box: ({ children }) => <div>{children}</div>,
  Button: ({ children, onClick, href, variant, color, leftSection }) => (
    <button
      onClick={onClick}
      data-href={href}
      data-variant={variant}
      data-color={color}
    >
      {leftSection}
      {children}
    </button>
  ),
  Group: ({ children }) => <div>{children}</div>,
  Loader: () => <div data-testid="loader" />,
  NativeSelect: ({ value, onChange, data }) => (
    <select data-testid="page-size-select" value={value} onChange={onChange}>
      {data?.map((d) => (
        <option key={d} value={d}>
          {d}
        </option>
      ))}
    </select>
  ),
  Pagination: ({ total, value, onChange }) => (
    <div data-testid="pagination">
      <span data-testid="pagination-total">{total}</span>
      <span data-testid="pagination-value">{value}</span>
      <button
        data-testid="next-page"
        onClick={() => onChange(value + 1)}
        disabled={value >= total}
      >
        Next
      </button>
    </div>
  ),
  Select: ({ data, value, onChange }) => {
    const isSort = data?.some((d) => d.value === 'name-asc');
    const isStatus = data?.some((d) => d.value === 'installed');
    const testId = isSort
      ? 'sort-select'
      : isStatus
        ? 'status-select'
        : 'repo-select';
    return (
      <select
        data-testid={testId}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value)}
      >
        {data?.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    );
  },
  SimpleGrid: ({ children }) => <div data-testid="plugin-grid">{children}</div>,
  Text: ({ children, fw, size, c }) => (
    <span data-fw={fw} data-size={size} data-color={c}>
      {children}
    </span>
  ),
  TextInput: ({ value, onChange, placeholder }) => (
    <input
      data-testid="search-input"
      value={value ?? ''}
      onChange={onChange}
      placeholder={placeholder}
    />
  ),
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import PluginBrowsePage from '../PluginBrowse';
import { usePluginStore } from '../../store/plugins.jsx';
import useSettingsStore from '../../store/settings.jsx';
import { showNotification } from '../../utils/notificationUtils.js';
import { reloadPlugins } from '../../utils/pages/PluginsUtils.js';

// ── Shared helpers ─────────────────────────────────────────────────────────────
const makePlugin = (overrides = {}) => ({
  slug: 'my-plugin',
  repo_id: 1,
  repo_name: 'Main Repo',
  name: 'My Plugin',
  description: 'A test plugin',
  author: 'Test Author',
  installed: false,
  install_status: null,
  deprecated: false,
  min_dispatcharr_version: null,
  max_dispatcharr_version: null,
  last_updated: '2024-01-01',
  ...overrides,
});

const makeRepo = (overrides = {}) => ({
  id: 1,
  name: 'Main Repo',
  url: 'https://example.com',
  ...overrides,
});

let mockFetchRepos;
let mockFetchAvailablePlugins;
let mockRefreshRepo;
let mockInvalidatePlugins;

const setupStore = ({
  repos = [],
  availablePlugins = [],
  availableLoading = false,
} = {}) => {
  mockFetchRepos = vi.fn();
  mockFetchAvailablePlugins = vi.fn();
  mockRefreshRepo = vi.fn().mockResolvedValue(undefined);
  mockInvalidatePlugins = vi.fn();

  vi.mocked(usePluginStore).mockImplementation((sel) =>
    sel({
      repos,
      availablePlugins,
      availableLoading,
      fetchRepos: mockFetchRepos,
      fetchAvailablePlugins: mockFetchAvailablePlugins,
      refreshRepo: mockRefreshRepo,
    })
  );

  vi.mocked(usePluginStore).getState.mockReturnValue({
    repos,
    invalidatePlugins: mockInvalidatePlugins,
  });

  vi.mocked(useSettingsStore).mockImplementation((sel) =>
    sel({ version: { version: '1.0.0' } })
  );
};

// ──────────────────────────────────────────────────────────────────────────────

describe('PluginBrowsePage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(reloadPlugins).mockResolvedValue(undefined);
    setupStore();
    localStorage.clear();
  });

  // ── Initialization ─────────────────────────────────────────────────────────

  describe('initialization', () => {
    it('calls fetchRepos and fetchAvailablePlugins on mount', () => {
      render(<PluginBrowsePage />);
      expect(mockFetchRepos).toHaveBeenCalledTimes(1);
      expect(mockFetchAvailablePlugins).toHaveBeenCalledTimes(1);
    });

    it('does not refetch on re-render (hasFetched guard)', () => {
      const { rerender } = render(<PluginBrowsePage />);
      rerender(<PluginBrowsePage />);
      expect(mockFetchRepos).toHaveBeenCalledTimes(1);
    });
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders "Find Plugins" title', () => {
      render(<PluginBrowsePage />);
      expect(screen.getByText('Find Plugins')).toBeInTheDocument();
    });

    it('shows plugin count badge when plugins are available', () => {
      setupStore({
        availablePlugins: [makePlugin(), makePlugin({ slug: 'p2' })],
      });
      render(<PluginBrowsePage />);
      expect(screen.getByText('2 Plugins Available')).toBeInTheDocument();
    });

    it('does not show plugin count badge when no plugins', () => {
      render(<PluginBrowsePage />);
      expect(screen.queryByText(/Plugins Available/)).not.toBeInTheDocument();
    });

    it('shows repo count badge when repos > 1', () => {
      setupStore({ repos: [makeRepo(), makeRepo({ id: 2 })] });
      render(<PluginBrowsePage />);
      expect(screen.getByText('2 Repos')).toBeInTheDocument();
    });

    it('does not show repo count badge when only 1 repo', () => {
      setupStore({ repos: [makeRepo()] });
      render(<PluginBrowsePage />);
      expect(screen.queryByText(/\d+ Repos/)).not.toBeInTheDocument();
    });

    it('shows Loader when loading and no plugins yet', () => {
      setupStore({ availableLoading: true, availablePlugins: [] });
      render(<PluginBrowsePage />);
      expect(screen.getByTestId('loader')).toBeInTheDocument();
    });

    it('does not show Loader when not loading', () => {
      setupStore({ availableLoading: false });
      render(<PluginBrowsePage />);
      expect(screen.queryByTestId('loader')).not.toBeInTheDocument();
    });

    it('does not show Loader when loading but plugins are already loaded', () => {
      setupStore({ availableLoading: true, availablePlugins: [makePlugin()] });
      render(<PluginBrowsePage />);
      expect(screen.queryByTestId('loader')).not.toBeInTheDocument();
    });
  });

  // ── Empty states ───────────────────────────────────────────────────────────

  describe('empty states', () => {
    it('shows "No plugins available" when there are no plugins', () => {
      render(<PluginBrowsePage />);
      expect(
        screen.getByText(/No plugins available. Try refreshing repos/)
      ).toBeInTheDocument();
    });

    it('shows "No plugins match" when all plugins are filtered out', () => {
      setupStore({ availablePlugins: [makePlugin({ name: 'Plex' })] });
      render(<PluginBrowsePage />);
      fireEvent.change(screen.getByTestId('search-input'), {
        target: { value: 'xyznotfound' },
      });
      expect(
        screen.getByText(/No plugins match your filters/)
      ).toBeInTheDocument();
    });

    it('does not show "No plugins match" when there are no plugins at all', () => {
      render(<PluginBrowsePage />);
      expect(
        screen.queryByText(/No plugins match your filters/)
      ).not.toBeInTheDocument();
    });
  });

  // ── Plugin cards ───────────────────────────────────────────────────────────

  describe('plugin cards', () => {
    it('renders a card for each visible plugin', () => {
      setupStore({
        availablePlugins: [
          makePlugin({ slug: 'a', name: 'Plugin A' }),
          makePlugin({ slug: 'b', name: 'Plugin B' }),
        ],
      });
      render(<PluginBrowsePage />);
      expect(screen.getAllByTestId('plugin-card')).toHaveLength(2);
    });

    it('renders no cards when no plugins available', () => {
      render(<PluginBrowsePage />);
      expect(screen.queryByTestId('plugin-card')).not.toBeInTheDocument();
    });
  });

  // ── Manage Repos modal ─────────────────────────────────────────────────────

  describe('Manage Repos modal', () => {
    it('ManageReposModal is not visible initially', () => {
      render(<PluginBrowsePage />);
      expect(
        screen.queryByTestId('manage-repos-modal')
      ).not.toBeInTheDocument();
    });

    it('opens ManageReposModal when "Manage Repos" button is clicked', () => {
      render(<PluginBrowsePage />);
      fireEvent.click(screen.getByText('Manage Repos'));
      expect(screen.getByTestId('manage-repos-modal')).toBeInTheDocument();
    });

    it('closes ManageReposModal when its close handler is called', () => {
      render(<PluginBrowsePage />);
      fireEvent.click(screen.getByText('Manage Repos'));
      fireEvent.click(screen.getByTestId('manage-repos-close'));
      expect(
        screen.queryByTestId('manage-repos-modal')
      ).not.toBeInTheDocument();
    });
  });

  // ── Refresh all ────────────────────────────────────────────────────────────

  describe('handleRefreshAll', () => {
    it('calls refreshRepo for each repo in the store', async () => {
      const repos = [makeRepo({ id: 1 }), makeRepo({ id: 2 })];
      setupStore({ repos });
      vi.mocked(usePluginStore).getState.mockReturnValue({
        repos,
        invalidatePlugins: mockInvalidatePlugins,
      });
      render(<PluginBrowsePage />);
      fireEvent.click(screen.getByTestId('action-icon'));
      await waitFor(() => {
        expect(mockRefreshRepo).toHaveBeenCalledWith(1);
        expect(mockRefreshRepo).toHaveBeenCalledWith(2);
      });
    });

    it('calls fetchAvailablePlugins, reloadPlugins, and invalidatePlugins after refresh', async () => {
      setupStore({ repos: [makeRepo()] });
      vi.mocked(usePluginStore).getState.mockReturnValue({
        repos: [makeRepo()],
        invalidatePlugins: mockInvalidatePlugins,
      });
      render(<PluginBrowsePage />);
      fireEvent.click(screen.getByTestId('action-icon'));
      await waitFor(() => {
        expect(mockFetchAvailablePlugins).toHaveBeenCalled();
        expect(reloadPlugins).toHaveBeenCalled();
        expect(mockInvalidatePlugins).toHaveBeenCalled();
      });
    });

    it('shows success notification on successful refresh', async () => {
      render(<PluginBrowsePage />);
      fireEvent.click(screen.getByTestId('action-icon'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Refreshed', color: 'green' })
        );
      });
    });

    it('shows error notification when refresh fails', async () => {
      mockRefreshRepo = vi.fn().mockRejectedValue(new Error('Network error'));
      vi.mocked(usePluginStore).mockImplementation((sel) =>
        sel({
          repos: [makeRepo()],
          availablePlugins: [],
          availableLoading: false,
          fetchRepos: vi.fn(),
          fetchAvailablePlugins: vi.fn(),
          refreshRepo: mockRefreshRepo,
        })
      );
      vi.mocked(usePluginStore).getState.mockReturnValue({
        repos: [makeRepo()],
        invalidatePlugins: vi.fn(),
      });
      render(<PluginBrowsePage />);
      fireEvent.click(screen.getByTestId('action-icon'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Error', color: 'red' })
        );
      });
    });
  });

  // ── Search filter ──────────────────────────────────────────────────────────

  describe('search filter', () => {
    it('filters plugins by name', () => {
      setupStore({
        availablePlugins: [
          makePlugin({ slug: 'plex', name: 'Plex Plugin' }),
          makePlugin({ slug: 'other', name: 'Other Plugin' }),
        ],
      });
      render(<PluginBrowsePage />);
      fireEvent.change(screen.getByTestId('search-input'), {
        target: { value: 'plex' },
      });
      const cards = screen.getAllByTestId('plugin-card');
      expect(cards).toHaveLength(1);
      expect(cards[0]).toHaveTextContent('Plex Plugin');
    });

    it('filters plugins by description', () => {
      setupStore({
        availablePlugins: [
          makePlugin({
            slug: 'a',
            name: 'Alpha',
            description: 'streaming service',
          }),
          makePlugin({ slug: 'b', name: 'Beta', description: 'other thing' }),
        ],
      });
      render(<PluginBrowsePage />);
      fireEvent.change(screen.getByTestId('search-input'), {
        target: { value: 'streaming' },
      });
      expect(screen.getAllByTestId('plugin-card')).toHaveLength(1);
      expect(screen.getByText('Alpha')).toBeInTheDocument();
    });

    it('filters plugins by author', () => {
      setupStore({
        availablePlugins: [
          makePlugin({ slug: 'a', name: 'A', author: 'alice' }),
          makePlugin({ slug: 'b', name: 'B', author: 'bob' }),
        ],
      });
      render(<PluginBrowsePage />);
      fireEvent.change(screen.getByTestId('search-input'), {
        target: { value: 'alice' },
      });
      expect(screen.getAllByTestId('plugin-card')).toHaveLength(1);
    });

    it('is case-insensitive', () => {
      setupStore({ availablePlugins: [makePlugin({ name: 'PlexPlugin' })] });
      render(<PluginBrowsePage />);
      fireEvent.change(screen.getByTestId('search-input'), {
        target: { value: 'PLEXPLUGIN' },
      });
      expect(screen.getAllByTestId('plugin-card')).toHaveLength(1);
    });
  });

  // ── Status filter ──────────────────────────────────────────────────────────

  describe('status filter', () => {
    it('filters to installed plugins only', () => {
      setupStore({
        availablePlugins: [
          makePlugin({ slug: 'a', installed: true }),
          makePlugin({ slug: 'b', installed: false }),
        ],
      });
      render(<PluginBrowsePage />);
      fireEvent.change(screen.getByTestId('status-select'), {
        target: { value: 'installed' },
      });
      expect(screen.getAllByTestId('plugin-card')).toHaveLength(1);
    });

    it('filters to not-installed plugins only', () => {
      setupStore({
        availablePlugins: [
          makePlugin({ slug: 'a', installed: true }),
          makePlugin({ slug: 'b', installed: false }),
          makePlugin({ slug: 'c', installed: false }),
        ],
      });
      render(<PluginBrowsePage />);
      fireEvent.change(screen.getByTestId('status-select'), {
        target: { value: 'not-installed' },
      });
      expect(screen.getAllByTestId('plugin-card')).toHaveLength(2);
    });
  });

  // ── Repo filter ────────────────────────────────────────────────────────────

  describe('repo filter', () => {
    it('does not show repo filter when only one repo', () => {
      setupStore({
        availablePlugins: [makePlugin({ repo_id: 1, repo_name: 'Repo 1' })],
      });
      render(<PluginBrowsePage />);
      // repoOptions.length = 2 (all + 1 repo), which is NOT > 2, so hidden
      expect(screen.queryByTestId('repo-select')).not.toBeInTheDocument();
    });

    it('shows repo filter when there are multiple repos', () => {
      setupStore({
        availablePlugins: [
          makePlugin({ slug: 'a', repo_id: 1, repo_name: 'Repo 1' }),
          makePlugin({ slug: 'b', repo_id: 2, repo_name: 'Repo 2' }),
          makePlugin({ slug: 'c', repo_id: 3, repo_name: 'Repo 3' }),
        ],
      });
      render(<PluginBrowsePage />);
      // repoOptions.length = 4 (all + 3 repos), which IS > 2
      expect(screen.getByTestId('repo-select')).toBeInTheDocument();
    });

    it('filters plugins by selected repo', () => {
      setupStore({
        availablePlugins: [
          makePlugin({ slug: 'a', repo_id: 1, repo_name: 'Repo 1' }),
          makePlugin({ slug: 'b', repo_id: 2, repo_name: 'Repo 2' }),
          makePlugin({ slug: 'c', repo_id: 3, repo_name: 'Repo 3' }),
        ],
      });
      render(<PluginBrowsePage />);
      fireEvent.change(screen.getByTestId('repo-select'), {
        target: { value: '2' },
      });
      expect(screen.getAllByTestId('plugin-card')).toHaveLength(1);
    });
  });

  // ── Pagination ─────────────────────────────────────────────────────────────

  describe('pagination', () => {
    it('shows pagination bar only when there are filtered plugins', () => {
      render(<PluginBrowsePage />);
      expect(screen.queryByTestId('pagination')).not.toBeInTheDocument();
    });

    it('shows pagination when plugins are available', () => {
      setupStore({ availablePlugins: [makePlugin()] });
      render(<PluginBrowsePage />);
      expect(screen.getByTestId('pagination')).toBeInTheDocument();
    });

    it('shows correct pagination range text', () => {
      const plugins = Array.from({ length: 5 }, (_, i) =>
        makePlugin({ slug: `plugin-${i}`, name: `Plugin ${i}` })
      );
      setupStore({ availablePlugins: plugins });
      render(<PluginBrowsePage />);
      expect(screen.getByText('1 to 5 of 5')).toBeInTheDocument();
    });

    it('saves perPage to localStorage when page size changes', () => {
      const setItemSpy = vi.spyOn(Storage.prototype, 'setItem');
      setupStore({ availablePlugins: [makePlugin()] });
      render(<PluginBrowsePage />);
      fireEvent.change(screen.getByTestId('page-size-select'), {
        target: { value: '18' },
      });
      expect(setItemSpy).toHaveBeenCalledWith('pluginBrowsePerPage', '18');
    });

    it('reads initial perPage from localStorage', () => {
      localStorage.setItem('pluginBrowsePerPage', '27');
      const plugins = Array.from({ length: 27 }, (_, i) =>
        makePlugin({ slug: `p-${i}`, name: `Plugin ${i}` })
      );
      setupStore({ availablePlugins: plugins });
      render(<PluginBrowsePage />);
      expect(screen.getByTestId('page-size-select')).toHaveValue('27');
    });

    it('resets page to 1 when search query changes', () => {
      const plugins = Array.from({ length: 20 }, (_, i) =>
        makePlugin({ slug: `p-${i}`, name: `Plugin ${i}` })
      );
      setupStore({ availablePlugins: plugins });
      render(<PluginBrowsePage />);
      // Go to page 2
      fireEvent.click(screen.getByTestId('next-page'));
      expect(screen.getByTestId('pagination-value')).toHaveTextContent('2');
      // Change search → page resets
      fireEvent.change(screen.getByTestId('search-input'), {
        target: { value: 'Plugin' },
      });
      expect(screen.getByTestId('pagination-value')).toHaveTextContent('1');
    });
  });
});
