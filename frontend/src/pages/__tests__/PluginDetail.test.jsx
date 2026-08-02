import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import PluginDetail from '../PluginDetail';
import { usePluginStore } from '../../store/plugins';
import useSettingsStore from '../../store/settings';
import useAuthStore from '../../store/auth';
import { reloadPlugin, refreshSinglePlugin } from '../../utils/pages/PluginsUtils';
import { useMediaQuery } from '@mantine/hooks';

vi.mock('@mantine/hooks', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    useMediaQuery: vi.fn(() => false),
  };
});

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useParams: () => ({ key: mockParams.key }),
  };
});

const mockParams = { key: 'test-plugin' };

vi.mock('../../store/plugins');
vi.mock('../../store/settings');
vi.mock('../../store/auth');

vi.mock('../../utils/pages/PluginsUtils', () => ({
  deletePluginByKey: vi.fn(),
  reloadPlugin: vi.fn(),
  refreshSinglePlugin: vi.fn(),
  runPluginAction: vi.fn(),
  setPluginEnabled: vi.fn(),
  updatePluginSettings: vi.fn(),
}));

vi.mock('../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

vi.mock('../../components/PluginHeader.jsx', () => ({
  default: ({ plugin }) => <div>{plugin.name}</div>,
}));

vi.mock('../../components/PluginDetailPanel.jsx', () => ({
  default: () => <div data-testid="plugin-detail-panel" />,
}));

vi.mock('../../components/EvenlyWrappedPills.jsx', () => ({
  default: ({ items }) => <div>{items.map((item) => <span key={item.key}>{item.node}</span>)}</div>,
}));

vi.mock('../../components/PluginFieldList.jsx', () => ({
  default: ({ updateField }) => (
    <div data-testid="plugin-field-list">
      <button onClick={() => updateField('greeting', 'changed')}>change-field</button>
      <button onClick={() => updateField('greeting', 'hello')}>revert-field</button>
    </div>
  ),
}));

vi.mock('../../components/PluginActionList.jsx', () => ({
  PluginActionList: () => <div data-testid="plugin-action-list" />,
  PluginActionStatus: () => null,
}));

vi.mock('@mantine/core', async () => {
  return {
    ActionIcon: ({ children, onClick, ...props }) => <button onClick={onClick} {...props}>{children}</button>,
    AppShellMain: ({ children }) => <div>{children}</div>,
    Badge: ({ children }) => <span>{children}</span>,
    Box: ({ children, ...props }) => <div {...props}>{children}</div>,
    Button: ({ children, onClick, loading, disabled }) => (
      <button onClick={onClick} disabled={loading || disabled}>
        {children}
      </button>
    ),
    Collapse: ({ children, in: opened }) => (opened ? <div>{children}</div> : null),
    Grid: Object.assign(
      ({ children }) => <div>{children}</div>,
      { Col: ({ children }) => <div>{children}</div> }
    ),
    Group: ({ children }) => <div>{children}</div>,
    Loader: () => <div data-testid="loader" />,
    Modal: ({ opened, children, title }) =>
      opened ? (
        <div data-testid="modal">
          <div>{title}</div>
          {children}
        </div>
      ) : null,
    Paper: ({ children }) => <div>{children}</div>,
    SegmentedControl: ({ value, onChange, disabled, data }) => (
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        {data.map((d) => (
          <option key={d.value} value={d.value}>
            {d.label}
          </option>
        ))}
      </select>
    ),
    Stack: ({ children }) => <div>{children}</div>,
    Text: ({ children }) => <span>{children}</span>,
    Tooltip: ({ children }) => <>{children}</>,
    Transition: ({ mounted, children }) => (mounted ? children({}) : null),
    UnstyledButton: ({ children, onClick }) => (
      <button onClick={onClick}>{children}</button>
    ),
  };
});

describe('PluginDetail', () => {
  const mockPlugin = {
    key: 'test-plugin',
    name: 'Test Plugin',
    description: 'A test plugin',
    version: '1.0.0',
    enabled: true,
    ever_enabled: true,
    slug: 'test-plugin',
    source_repo: 1,
    is_managed: true,
    fields: [],
    actions: [],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mockParams.key = 'test-plugin';
    usePluginStore.mockImplementation((selector) =>
      selector({
        plugins: [mockPlugin],
        loading: false,
        installPlugin: vi.fn(),
      })
    );
    usePluginStore.getState = vi.fn(() => ({
      plugins: [mockPlugin],
      loading: false,
      fetchPlugins: vi.fn(),
      fetchAvailablePlugins: vi.fn(),
      availablePlugins: [],
      updatePlugin: vi.fn(),
      removePlugin: vi.fn(),
      invalidatePlugins: vi.fn(),
      installPlugin: vi.fn(),
      hydratePluginTasks: vi.fn(),
    }));
    useSettingsStore.mockImplementation((selector) =>
      selector({ version: { version: '1.0.0' } })
    );
    useAuthStore.mockImplementation((selector) =>
      selector({
        user: { custom_properties: { pinnedPlugins: [] } },
        togglePinnedPlugin: vi.fn(),
      })
    );
  });

  it('renders plugin name and description', () => {
    render(<PluginDetail />);
    expect(screen.getByText('Test Plugin')).toBeInTheDocument();
    expect(screen.getByText('A test plugin')).toBeInTheDocument();
  });

  it('toggles pinning from the Plugin Control pane', () => {
    const mockToggle = vi.fn();
    useAuthStore.mockImplementation((selector) =>
      selector({
        user: { custom_properties: { pinnedPlugins: [] } },
        togglePinnedPlugin: mockToggle,
      })
    );
    render(<PluginDetail />);

    fireEvent.click(screen.getByLabelText('Pin to sidebar'));
    expect(mockToggle).toHaveBeenCalledWith('test-plugin');
  });

  it('shows a not-found state and a back link when the plugin does not exist', () => {
    mockParams.key = 'missing-plugin';
    usePluginStore.mockImplementation((selector) =>
      selector({ plugins: [], loading: false })
    );
    render(<PluginDetail />);
    expect(screen.getByText('Plugin not found.')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Back to Plugins'));
    expect(mockNavigate).toHaveBeenCalledWith('/plugins');
  });

  it('renders the shared PluginDetailPanel for managed plugins with a check-for-updates action', () => {
    render(<PluginDetail />);
    const panel = screen.getByTestId('plugin-detail-panel');
    expect(panel).toBeInTheDocument();
    expect(screen.getByText('Check for Updates')).toBeInTheDocument();
  });

  it('checks for updates when the button is clicked', async () => {
    refreshSinglePlugin.mockResolvedValue({ success: true });
    render(<PluginDetail />);

    fireEvent.click(screen.getByText('Check for Updates'));

    await waitFor(() => {
      expect(refreshSinglePlugin).toHaveBeenCalledWith(1, 'test-plugin');
    });
  });

  it('shows the standalone Uninstall button for managed plugins when no version is selected yet', () => {
    // availablePlugins is empty in the default setup, so PluginDetail can't
    // resolve a selectedVersion, so it should default to showing the
    // standalone button rather than silently hiding the only uninstall path.
    render(<PluginDetail />);
    expect(screen.getByText('Uninstall')).toBeInTheDocument();
  });

  it('hides the standalone Uninstall button once the selected version matches the installed one', async () => {
    usePluginStore.getState = vi.fn(() => ({
      plugins: [mockPlugin],
      loading: false,
      fetchPlugins: vi.fn(),
      fetchAvailablePlugins: vi.fn(),
      availablePlugins: [
        {
          slug: 'test-plugin',
          repo_id: 1,
          latest_version: '1.0.0', // matches mockPlugin.version
        },
      ],
      updatePlugin: vi.fn(),
      removePlugin: vi.fn(),
      invalidatePlugins: vi.fn(),
      installPlugin: vi.fn(),
      hydratePluginTasks: vi.fn(),
    }));
    render(<PluginDetail />);

    await waitFor(() => {
      expect(screen.queryByText('Uninstall')).not.toBeInTheDocument();
    });
  });

  it('renders a standalone Uninstall button for unmanaged plugins', () => {
    usePluginStore.mockImplementation((selector) =>
      selector({
        plugins: [{ ...mockPlugin, slug: '', source_repo: null, is_managed: false }],
        loading: false,
      })
    );
    render(<PluginDetail />);
    expect(screen.getByText('Uninstall')).toBeInTheDocument();
  });

  it('reloads plugin code when Reload Plugin is confirmed', async () => {
    reloadPlugin.mockResolvedValue({ success: true });
    render(<PluginDetail />);

    fireEvent.click(screen.getByText('Reload Plugin'));
    fireEvent.click(screen.getByText('Reload'));

    await waitFor(() => {
      expect(reloadPlugin).toHaveBeenCalledWith('test-plugin');
    });
  });

  describe('persistent save bar', () => {
    const pluginWithFields = {
      ...mockPlugin,
      fields: [{ id: 'greeting', label: 'Greeting', type: 'text' }],
      settings: { greeting: 'hello' },
    };

    beforeEach(() => {
      usePluginStore.mockImplementation((selector) =>
        selector({
          plugins: [pluginWithFields],
          loading: false,
          installPlugin: vi.fn(),
        })
      );
    });

    it('is hidden when settings are unchanged', () => {
      render(<PluginDetail />);
      expect(screen.queryByText('Unsaved settings changes')).not.toBeInTheDocument();
    });

    it('appears when a field is changed', () => {
      render(<PluginDetail />);
      fireEvent.click(screen.getByText('change-field'));
      expect(screen.getByText('Unsaved settings changes')).toBeInTheDocument();
    });

    it('disappears again when the field is manually reverted to its saved value', () => {
      render(<PluginDetail />);
      fireEvent.click(screen.getByText('change-field'));
      expect(screen.getByText('Unsaved settings changes')).toBeInTheDocument();

      fireEvent.click(screen.getByText('revert-field'));
      expect(screen.queryByText('Unsaved settings changes')).not.toBeInTheDocument();
    });

    it('discards local changes and hides the bar when Discard is clicked', () => {
      render(<PluginDetail />);
      fireEvent.click(screen.getByText('change-field'));
      expect(screen.getByText('Unsaved settings changes')).toBeInTheDocument();

      fireEvent.click(screen.getByText('Discard'));
      expect(screen.queryByText('Unsaved settings changes')).not.toBeInTheDocument();
    });
  });

  describe('Actions collapse (single-column mode)', () => {
    const pluginWithActions = {
      ...mockPlugin,
      actions: [{ id: 'a1', label: 'Do Thing' }],
    };

    it('always shows actions expanded in wide (multi-column) mode', () => {
      vi.mocked(useMediaQuery).mockReturnValue(false);
      usePluginStore.mockImplementation((selector) =>
        selector({ plugins: [pluginWithActions], loading: false })
      );
      render(<PluginDetail />);
      expect(screen.getByTestId('plugin-action-list')).toBeInTheDocument();
    });

    it('starts expanded but collapses on click in single-column mode', () => {
      vi.mocked(useMediaQuery).mockReturnValue(true);
      usePluginStore.mockImplementation((selector) =>
        selector({ plugins: [pluginWithActions], loading: false })
      );
      render(<PluginDetail />);

      expect(screen.getByTestId('plugin-action-list')).toBeInTheDocument();

      fireEvent.click(screen.getByText('Actions'));
      expect(screen.queryByTestId('plugin-action-list')).not.toBeInTheDocument();

      fireEvent.click(screen.getByText('Actions'));
      expect(screen.getByTestId('plugin-action-list')).toBeInTheDocument();
    });
  });
});
