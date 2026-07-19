import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import AvailablePluginCard from '../AvailablePluginCard';

// ── Router ─────────────────────────────────────────────────────────────────────
vi.mock('react-router-dom', () => ({
  useNavigate: vi.fn(),
  useLocation: vi.fn(),
}));

// ── Plugin store ───────────────────────────────────────────────────────────────
vi.mock('../../../store/plugins', () => {
  const mockUsePluginStore = vi.fn();
  mockUsePluginStore.getState = vi.fn();
  return { usePluginStore: mockUsePluginStore };
});

// ── PluginWarnings ─────────────────────────────────────────────────────────────
vi.mock('../../PluginWarnings.jsx', () => ({
  PluginDowngradeWarning: ({ children }) => (
    <div data-testid="downgrade-warning">{children}</div>
  ),
  PluginInfoNote: ({ children }) => (
    <div data-testid="info-note">{children}</div>
  ),
  PluginSecurityWarning: ({ children }) => (
    <div data-testid="security-warning">{children}</div>
  ),
  PluginSupportDisclaimer: () => <div data-testid="support-disclaimer" />,
}));

// ── PluginDetailPanel ──────────────────────────────────────────────────────────
vi.mock('../../PluginDetailPanel.jsx', () => ({
  default: ({ onInstall, onUninstall }) => (
    <div data-testid="plugin-detail-panel">
      <button
        data-testid="detail-install"
        onClick={() =>
          onInstall({
            repo_id: 1,
            slug: 'test-plugin',
            version: '1.0.0',
            download_url: 'https://example.com/plugin.zip',
            sha256: 'abc123',
          })
        }
      >
        Detail Install
      </button>
      <button data-testid="detail-uninstall" onClick={onUninstall}>
        Detail Uninstall
      </button>
    </div>
  ),
}));

// ── pluginUtils ────────────────────────────────────────────────────────────────
vi.mock('../../../utils/components/pluginUtils.js', () => ({
  buildCompatibilityTooltip: vi.fn(),
  compareVersions: vi.fn(),
  getInstallInfo: vi.fn(),
}));

// ── PluginsUtils ───────────────────────────────────────────────────────────────
vi.mock('../../../utils/pages/PluginsUtils.js', () => ({
  deletePluginByKey: vi.fn(),
  getPluginDetailManifest: vi.fn(),
  setPluginEnabled: vi.fn(),
}));

// ── SizedInstallButton ─────────────────────────────────────────────────────────
vi.mock('../../theme/SizedInstallButton.jsx', () => ({
  default: ({ children, onClick, disabled, loading, latest_size }) => (
    <button
      data-testid="sized-install-button"
      data-size={latest_size}
      onClick={onClick}
      disabled={disabled || loading}
    >
      {children}
    </button>
  ),
}));

// ── @mantine/core ──────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Avatar: ({ children, src, alt }) => (
    <div data-testid="avatar" aria-label={alt}>
      {src ? <img src={src} alt={alt} /> : children}
    </div>
  ),
  Badge: ({ children, color, component, href, leftSection }) =>
    component === 'a' ? (
      <a href={href} data-testid="badge" data-color={color}>
        {leftSection}
        {children}
      </a>
    ) : (
      <span data-testid="badge" data-color={color}>
        {leftSection}
        {children}
      </span>
    ),
  Box: ({ children, style }) => <div style={style}>{children}</div>,
  Button: ({ children, onClick, disabled, loading, color, variant }) => (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      data-color={color}
      data-variant={variant}
      data-loading={String(loading)}
    >
      {children}
    </button>
  ),
  Card: ({ children, style }) => (
    <div data-testid="plugin-card" style={style}>
      {children}
    </div>
  ),
  Group: ({ children, style }) => <div style={style}>{children}</div>,
  Loader: () => <span data-testid="loader" />,
  Modal: ({ children, opened, onClose, title }) =>
    opened ? (
      <div data-testid="modal">
        <div data-testid="modal-title">{title}</div>
        <button data-testid="modal-close" onClick={onClose}>
          ×
        </button>
        {children}
      </div>
    ) : null,
  Stack: ({ children }) => <div>{children}</div>,
  Switch: ({ checked, onChange }) => (
    <button
      type="button"
      data-testid="enable-switch"
      data-checked={String(checked)}
      onClick={() =>
        onChange && onChange({ currentTarget: { checked: !checked } })
      }
    >
      {checked ? 'On' : 'Off'}
    </button>
  ),
  Text: ({ children, fw, style }) => (
    <span data-fw={fw} style={style}>
      {children}
    </span>
  ),
  Tooltip: ({ children, label }) => <div data-tooltip={label}>{children}</div>,
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  AlertTriangle: () => <svg data-testid="icon-alert-triangle" />,
  Ban: () => <svg data-testid="icon-ban" />,
  Check: () => <svg data-testid="icon-check" />,
  Download: () => <svg data-testid="icon-download" />,
  FlaskConical: () => <svg data-testid="icon-flask-conical" />,
  Info: () => <svg data-testid="icon-info" />,
  RefreshCw: () => <svg data-testid="icon-refresh-cw" />,
  RotateCcw: () => <svg data-testid="icon-rotate-ccw" />,
  ShieldAlert: () => <svg data-testid="icon-shield-alert" />,
  ShieldCheck: () => <svg data-testid="icon-shield-check" />,
  Trash2: () => <svg data-testid="icon-trash2" />,
}));

// ──────────────────────────────────────────────────────────────────────────────
// Imports after mocks
// ──────────────────────────────────────────────────────────────────────────────
import { useNavigate, useLocation } from 'react-router-dom';
import { usePluginStore } from '../../../store/plugins';
import {
  buildCompatibilityTooltip,
  compareVersions,
  getInstallInfo,
} from '../../../utils/components/pluginUtils.js';
import * as PluginsUtils from '../../../utils/pages/PluginsUtils.js';

// ──────────────────────────────────────────────────────────────────────────────
// Factories
// ──────────────────────────────────────────────────────────────────────────────
const makePlugin = (overrides = {}) => ({
  slug: 'test-plugin',
  name: 'Test Plugin',
  author: 'Test Author',
  description: 'A test plugin description',
  latest_version: '1.0.0',
  latest_url: 'https://example.com/plugin.zip',
  latest_sha256: 'abc123',
  latest_size: 1024,
  install_status: 'not_installed',
  installed: false,
  installed_version: null,
  repo_id: 1,
  repo_name: 'Test Repo',
  is_official_repo: false,
  manifest_url: null,
  deprecated: false,
  license: 'MIT',
  last_updated: '2024-01-01T00:00:00Z',
  icon_url: null,
  signature_verified: null,
  key: null,
  ...overrides,
});

const APP_VERSION = '1.0.0';

// ──────────────────────────────────────────────────────────────────────────────
// Mock helpers
// ──────────────────────────────────────────────────────────────────────────────
const setupMocks = ({ pathname = '/available-plugins' } = {}) => {
  const mockNavigate = vi.fn();
  vi.mocked(useNavigate).mockReturnValue(mockNavigate);
  vi.mocked(useLocation).mockReturnValue({ pathname });

  const mockInstallPlugin = vi.fn().mockResolvedValue({
    success: true,
    plugin: { key: 'test-plugin', enabled: true },
  });
  const mockInvalidatePlugins = vi.fn();
  const mockFetchAvailablePlugins = vi.fn();

  vi.mocked(usePluginStore).mockImplementation((sel) =>
    sel({ installPlugin: mockInstallPlugin })
  );
  usePluginStore.getState.mockReturnValue({
    invalidatePlugins: mockInvalidatePlugins,
    fetchAvailablePlugins: mockFetchAvailablePlugins,
  });

  // Default: versions are compatible, no downgrade, no bad signature
  vi.mocked(compareVersions).mockReturnValue(0);
  vi.mocked(buildCompatibilityTooltip).mockReturnValue('1.0.0 or newer');
  vi.mocked(getInstallInfo).mockReturnValue({
    isDowngrade: false,
    isUpdate: false,
    isBadSig: false,
  });

  vi.mocked(PluginsUtils.getPluginDetailManifest).mockResolvedValue(null);
  vi.mocked(PluginsUtils.deletePluginByKey).mockResolvedValue({
    success: true,
  });
  vi.mocked(PluginsUtils.setPluginEnabled).mockResolvedValue(undefined);

  return {
    mockNavigate,
    mockInstallPlugin,
    mockInvalidatePlugins,
    mockFetchAvailablePlugins,
  };
};

/**
 * Finds the confirm/action button inside the modal (not the card's SizedInstallButton).
 * Both share the same text in many tests, so we check by data-testid absence.
 */
const getModalActionButton = (text) =>
  screen
    .getAllByText(text)
    .find((el) => el.tagName === 'BUTTON' && !el.dataset.testid);

// ──────────────────────────────────────────────────────────────────────────────

describe('AvailablePluginCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the plugin name', () => {
      setupMocks();
      render(
        <AvailablePluginCard plugin={makePlugin()} appVersion={APP_VERSION} />
      );
      expect(screen.getByText('Test Plugin')).toBeInTheDocument();
    });

    it('renders the plugin description', () => {
      setupMocks();
      render(
        <AvailablePluginCard plugin={makePlugin()} appVersion={APP_VERSION} />
      );
      expect(screen.getByText('A test plugin description')).toBeInTheDocument();
    });

    it('renders the plugin author', () => {
      setupMocks();
      render(
        <AvailablePluginCard plugin={makePlugin()} appVersion={APP_VERSION} />
      );
      expect(screen.getByText('Test Author')).toBeInTheDocument();
    });

    it('renders the latest version badge', () => {
      setupMocks();
      render(
        <AvailablePluginCard plugin={makePlugin()} appVersion={APP_VERSION} />
      );
      expect(screen.getByText(/1\.0\.0/)).toBeInTheDocument();
    });

    it('renders the license badge', () => {
      setupMocks();
      render(
        <AvailablePluginCard plugin={makePlugin()} appVersion={APP_VERSION} />
      );
      expect(screen.getByText('MIT')).toBeInTheDocument();
    });

    it('renders a last_updated badge', () => {
      setupMocks();
      render(
        <AvailablePluginCard plugin={makePlugin()} appVersion={APP_VERSION} />
      );
      // The date badge is rendered from last_updated via toLocaleDateString()
      expect(
        screen.getByText(new Date('2024-01-01T00:00:00Z').toLocaleDateString())
      ).toBeInTheDocument();
    });

    it('renders the More Info button', () => {
      setupMocks();
      render(
        <AvailablePluginCard plugin={makePlugin()} appVersion={APP_VERSION} />
      );
      expect(screen.getByText('More Info')).toBeInTheDocument();
    });

    it('renders Install button for not_installed plugin', () => {
      setupMocks();
      render(
        <AvailablePluginCard plugin={makePlugin()} appVersion={APP_VERSION} />
      );
      expect(screen.getByTestId('sized-install-button')).toHaveTextContent(
        'Install'
      );
    });

    it('renders Update button for update_available plugin', () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makePlugin({
            install_status: 'update_available',
            installed: true,
            installed_version: '0.9.0',
          })}
          appVersion={APP_VERSION}
        />
      );
      expect(screen.getByTestId('sized-install-button')).toHaveTextContent(
        'Update'
      );
    });

    it('renders Uninstall button for installed plugin', () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makePlugin({
            install_status: 'installed',
            installed: true,
            installed_version: '1.0.0',
            key: 'test-plugin',
          })}
          appVersion={APP_VERSION}
        />
      );
      expect(screen.getByText('Uninstall')).toBeInTheDocument();
    });

    it('renders Overwrite button for unmanaged plugin', () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makePlugin({ install_status: 'unmanaged', installed: true })}
          appVersion={APP_VERSION}
        />
      );
      expect(screen.getByTestId('sized-install-button')).toHaveTextContent(
        'Overwrite'
      );
    });

    it('renders Overwrite button for different_repo plugin', () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makePlugin({
            install_status: 'different_repo',
            installed: true,
            installed_source_repo_name: 'Other Repo',
          })}
          appVersion={APP_VERSION}
        />
      );
      expect(screen.getByTestId('sized-install-button')).toHaveTextContent(
        'Overwrite'
      );
    });

    it('does not render a sized install button when latest_url is null', () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makePlugin({ latest_url: null })}
          appVersion={APP_VERSION}
        />
      );
      expect(
        screen.queryByTestId('sized-install-button')
      ).not.toBeInTheDocument();
    });

    it('renders min version badge when min_dispatcharr_version is set', () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makePlugin({ min_dispatcharr_version: '0.9.0' })}
          appVersion={APP_VERSION}
        />
      );
      expect(screen.getByText('0.9.0')).toBeInTheDocument();
    });

    it('renders max version badge when max_dispatcharr_version is set', () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makePlugin({ max_dispatcharr_version: '2.0.0' })}
          appVersion={APP_VERSION}
        />
      );
      expect(screen.getByText('2.0.0')).toBeInTheDocument();
    });

    it('renders Downgrade button for update_available when isLatestDowngrade', () => {
      setupMocks();
      // compareVersions(latest, installed) < 0 → isLatestDowngrade
      vi.mocked(compareVersions).mockReturnValue(-1);
      render(
        <AvailablePluginCard
          plugin={makePlugin({
            install_status: 'update_available',
            installed: true,
            installed_version: '1.1.0',
          })}
          appVersion={APP_VERSION}
        />
      );
      expect(screen.getByTestId('sized-install-button')).toHaveTextContent(
        'Downgrade'
      );
    });
  });

  // ── RepoBadge ──────────────────────────────────────────────────────────────

  describe('RepoBadge', () => {
    it('shows "Official Repo" badge when is_official_repo is true', () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makePlugin({ is_official_repo: true })}
          appVersion={APP_VERSION}
        />
      );
      expect(screen.getByText('Official Repo')).toBeInTheDocument();
    });

    it('shows community repo name badge when is_official_repo is false', () => {
      setupMocks();
      render(
        <AvailablePluginCard plugin={makePlugin()} appVersion={APP_VERSION} />
      );
      expect(screen.getByText('Test Repo')).toBeInTheDocument();
    });

    it('shows ShieldCheck icon when signature_verified is true', () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makePlugin({ signature_verified: true })}
          appVersion={APP_VERSION}
        />
      );
      expect(screen.getByTestId('icon-shield-check')).toBeInTheDocument();
    });

    it('shows ShieldAlert icon when signature_verified is false', () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makePlugin({ signature_verified: false })}
          appVersion={APP_VERSION}
        />
      );
      expect(screen.getByTestId('icon-shield-alert')).toBeInTheDocument();
    });

    it('shows no shield icon when signature_verified is null', () => {
      setupMocks();
      render(
        <AvailablePluginCard plugin={makePlugin()} appVersion={APP_VERSION} />
      );
      expect(screen.queryByTestId('icon-shield-check')).not.toBeInTheDocument();
      expect(screen.queryByTestId('icon-shield-alert')).not.toBeInTheDocument();
    });
  });

  // ── StatusBadge ────────────────────────────────────────────────────────────

  describe('StatusBadge', () => {
    it('shows Installed badge for installed plugin', () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makePlugin({ install_status: 'installed' })}
          appVersion={APP_VERSION}
        />
      );
      expect(screen.getByText('Installed')).toBeInTheDocument();
    });

    it('shows prerelease Installed badge when installed_version_is_prerelease', () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makePlugin({
            install_status: 'installed',
            installed_version_is_prerelease: true,
          })}
          appVersion={APP_VERSION}
        />
      );
      expect(screen.getByText('Prerelease')).toBeInTheDocument();
    });

    it('shows Update Available badge for update_available plugin', () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makePlugin({
            install_status: 'update_available',
            installed_version: '0.9.0',
          })}
          appVersion={APP_VERSION}
        />
      );
      expect(screen.getByText('Update Available')).toBeInTheDocument();
    });

    it('shows Deprecated badge for not-installed deprecated plugin', () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makePlugin({
            deprecated: true,
            install_status: 'not_installed',
          })}
          appVersion={APP_VERSION}
        />
      );
      expect(screen.getByText('Deprecated')).toBeInTheDocument();
    });

    it('shows Installed badge for unmanaged plugin', () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makePlugin({ install_status: 'unmanaged' })}
          appVersion={APP_VERSION}
        />
      );
      expect(screen.getByText('Installed')).toBeInTheDocument();
    });
  });

  // ── Compatibility ──────────────────────────────────────────────────────────

  describe('version compatibility', () => {
    it('shows compatibility warning when min version is not met', () => {
      // compareVersions returns negative → appVersion < min → meetsMinVersion = false
      vi.mocked(compareVersions).mockReturnValue(-1);
      render(
        <AvailablePluginCard
          plugin={makePlugin({ min_dispatcharr_version: '2.0.0' })}
          appVersion="0.9.0"
        />
      );
      expect(screen.getByTestId('icon-alert-triangle')).toBeInTheDocument();
    });

    it('disables install button when version is incompatible', () => {
      vi.mocked(compareVersions).mockReturnValue(-1);
      render(
        <AvailablePluginCard
          plugin={makePlugin({ min_dispatcharr_version: '2.0.0' })}
          appVersion="0.9.0"
        />
      );
      expect(screen.getByTestId('sized-install-button')).toBeDisabled();
    });

    it('does not show compatibility warning when version is met', () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makePlugin({ min_dispatcharr_version: '0.5.0' })}
          appVersion={APP_VERSION}
        />
      );
      expect(
        screen.queryByTestId('icon-alert-triangle')
      ).not.toBeInTheDocument();
    });
  });

  // ── More Info modal ────────────────────────────────────────────────────────

  describe('More Info modal', () => {
    it('opens detail modal when More Info is clicked', () => {
      setupMocks();
      render(
        <AvailablePluginCard plugin={makePlugin()} appVersion={APP_VERSION} />
      );
      fireEvent.click(screen.getByText('More Info'));
      expect(screen.getByTestId('plugin-detail-panel')).toBeInTheDocument();
    });

    it('does not call getPluginDetailManifest when manifest_url is null', () => {
      setupMocks();
      render(
        <AvailablePluginCard plugin={makePlugin()} appVersion={APP_VERSION} />
      );
      fireEvent.click(screen.getByText('More Info'));
      expect(PluginsUtils.getPluginDetailManifest).not.toHaveBeenCalled();
    });

    it('calls getPluginDetailManifest with correct args when manifest_url is set', async () => {
      setupMocks();
      const plugin = makePlugin({
        manifest_url: 'https://example.com/manifest.json',
      });
      render(<AvailablePluginCard plugin={plugin} appVersion={APP_VERSION} />);
      fireEvent.click(screen.getByText('More Info'));
      await waitFor(() => {
        expect(PluginsUtils.getPluginDetailManifest).toHaveBeenCalledWith(
          1,
          'https://example.com/manifest.json'
        );
      });
    });

    it('closes detail modal when modal close button is clicked', () => {
      setupMocks();
      render(
        <AvailablePluginCard plugin={makePlugin()} appVersion={APP_VERSION} />
      );
      fireEvent.click(screen.getByText('More Info'));
      expect(screen.getByTestId('modal')).toBeInTheDocument();
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('calls onDetailClose when detail modal is closed', () => {
      setupMocks();
      const onDetailClose = vi.fn();
      render(
        <AvailablePluginCard
          plugin={makePlugin()}
          appVersion={APP_VERSION}
          onDetailClose={onDetailClose}
        />
      );
      fireEvent.click(screen.getByText('More Info'));
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onDetailClose).toHaveBeenCalled();
    });

    it('triggers install flow from PluginDetailPanel', () => {
      setupMocks();
      render(
        <AvailablePluginCard plugin={makePlugin()} appVersion={APP_VERSION} />
      );
      fireEvent.click(screen.getByText('More Info'));
      fireEvent.click(screen.getByTestId('detail-install'));
      expect(screen.getAllByTestId('modal-title').at(-1)).toHaveTextContent(
        'Confirm Install'
      );
    });

    it('triggers uninstall flow from PluginDetailPanel', () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makePlugin({
            install_status: 'installed',
            key: 'test-plugin',
          })}
          appVersion={APP_VERSION}
        />
      );
      fireEvent.click(screen.getByText('More Info'));
      fireEvent.click(screen.getByTestId('detail-uninstall'));
      expect(screen.getAllByTestId('modal-title').at(-1)).toHaveTextContent(
        'Uninstall Plugin'
      );
    });
  });

  // ── autoOpenDetail ─────────────────────────────────────────────────────────

  describe('autoOpenDetail', () => {
    it('immediately opens detail modal when autoOpenDetail is true', () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makePlugin()}
          appVersion={APP_VERSION}
          autoOpenDetail
        />
      );
      expect(screen.getByTestId('plugin-detail-panel')).toBeInTheDocument();
    });
  });

  // ── Install flow ───────────────────────────────────────────────────────────

  describe('install flow', () => {
    it('opens confirm modal when Install button is clicked', () => {
      setupMocks();
      render(
        <AvailablePluginCard plugin={makePlugin()} appVersion={APP_VERSION} />
      );
      fireEvent.click(screen.getByTestId('sized-install-button'));
      expect(screen.getByTestId('modal')).toBeInTheDocument();
      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'Confirm Install'
      );
    });

    it('shows plugin name inside confirm modal', () => {
      setupMocks();
      render(
        <AvailablePluginCard plugin={makePlugin()} appVersion={APP_VERSION} />
      );
      fireEvent.click(screen.getByTestId('sized-install-button'));
      expect(screen.getAllByText(/Test Plugin/).length).toBeGreaterThan(0);
    });

    it('shows security warning in confirm modal', () => {
      setupMocks();
      render(
        <AvailablePluginCard plugin={makePlugin()} appVersion={APP_VERSION} />
      );
      fireEvent.click(screen.getByTestId('sized-install-button'));
      expect(screen.getByTestId('security-warning')).toBeInTheDocument();
    });

    it('Cancel closes confirm modal without calling installPlugin', () => {
      const { mockInstallPlugin } = setupMocks();
      render(
        <AvailablePluginCard plugin={makePlugin()} appVersion={APP_VERSION} />
      );
      fireEvent.click(screen.getByTestId('sized-install-button'));
      fireEvent.click(screen.getByText('Cancel'));
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
      expect(mockInstallPlugin).not.toHaveBeenCalled();
    });

    it('calls installPlugin with correct params after confirmation', async () => {
      const { mockInstallPlugin } = setupMocks();
      render(
        <AvailablePluginCard plugin={makePlugin()} appVersion={APP_VERSION} />
      );
      fireEvent.click(screen.getByTestId('sized-install-button'));
      fireEvent.click(getModalActionButton('Install'));
      await waitFor(() => {
        expect(mockInstallPlugin).toHaveBeenCalledWith(
          expect.objectContaining({
            repo_id: 1,
            slug: 'test-plugin',
            version: '1.0.0',
            download_url: 'https://example.com/plugin.zip',
          })
        );
      });
    });

    it('calls onBeforeInstall with plugin slug before installing', async () => {
      setupMocks();
      const onBeforeInstall = vi.fn();
      render(
        <AvailablePluginCard
          plugin={makePlugin()}
          appVersion={APP_VERSION}
          onBeforeInstall={onBeforeInstall}
        />
      );
      fireEvent.click(screen.getByTestId('sized-install-button'));
      fireEvent.click(getModalActionButton('Install'));
      await waitFor(() => {
        expect(onBeforeInstall).toHaveBeenCalledWith('test-plugin');
      });
    });

    it('calls onInstalled with plugin slug after successful install', async () => {
      setupMocks();
      const onInstalled = vi.fn();
      render(
        <AvailablePluginCard
          plugin={makePlugin()}
          appVersion={APP_VERSION}
          onInstalled={onInstalled}
        />
      );
      fireEvent.click(screen.getByTestId('sized-install-button'));
      fireEvent.click(getModalActionButton('Install'));
      await waitFor(() => {
        expect(onInstalled).toHaveBeenCalledWith('test-plugin');
      });
    });

    it('shows restart prompt with "Plugin Installed" title after successful install', async () => {
      setupMocks();
      render(
        <AvailablePluginCard plugin={makePlugin()} appVersion={APP_VERSION} />
      );
      fireEvent.click(screen.getByTestId('sized-install-button'));
      fireEvent.click(getModalActionButton('Install'));
      await waitFor(() => {
        expect(screen.getByTestId('modal-title')).toHaveTextContent(
          'Plugin Installed'
        );
      });
    });

    it('Done button in restart prompt closes it', async () => {
      setupMocks();
      render(
        <AvailablePluginCard plugin={makePlugin()} appVersion={APP_VERSION} />
      );
      fireEvent.click(screen.getByTestId('sized-install-button'));
      fireEvent.click(getModalActionButton('Install'));
      await waitFor(() => {
        expect(screen.getByText('Done')).toBeInTheDocument();
      });
      fireEvent.click(screen.getByText('Done'));
      await waitFor(() => {
        expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
      });
    });

    it('"Go to My Plugins" button navigates to /plugins', async () => {
      const { mockNavigate } = setupMocks();
      render(
        <AvailablePluginCard plugin={makePlugin()} appVersion={APP_VERSION} />
      );
      fireEvent.click(screen.getByTestId('sized-install-button'));
      fireEvent.click(getModalActionButton('Install'));
      await waitFor(() => {
        expect(screen.getByText('Go to My Plugins')).toBeInTheDocument();
      });
      fireEvent.click(screen.getByText('Go to My Plugins'));
      expect(mockNavigate).toHaveBeenCalledWith('/plugins');
    });

    it('does not show "Go to My Plugins" when already on /plugins path', async () => {
      setupMocks({ pathname: '/plugins' });
      render(
        <AvailablePluginCard plugin={makePlugin()} appVersion={APP_VERSION} />
      );
      fireEvent.click(screen.getByTestId('sized-install-button'));
      fireEvent.click(getModalActionButton('Install'));
      await waitFor(() => {
        expect(screen.getByText('Done')).toBeInTheDocument();
      });
      expect(screen.queryByText('Go to My Plugins')).not.toBeInTheDocument();
    });

    it('does not open restart prompt when installPlugin returns no success', async () => {
      const { mockInstallPlugin } = setupMocks();
      mockInstallPlugin.mockResolvedValue({ success: false });
      render(
        <AvailablePluginCard plugin={makePlugin()} appVersion={APP_VERSION} />
      );
      fireEvent.click(screen.getByTestId('sized-install-button'));
      fireEvent.click(getModalActionButton('Install'));
      await waitFor(() => {
        expect(mockInstallPlugin).toHaveBeenCalled();
      });
      expect(screen.queryByText('Plugin Installed')).not.toBeInTheDocument();
    });
  });

  // ── Enable now ─────────────────────────────────────────────────────────────

  describe('enable now (plugin installed as disabled)', () => {
    const installDisabledPlugin = async (mockInstallPlugin) => {
      mockInstallPlugin.mockResolvedValue({
        success: true,
        plugin: { key: 'test-plugin', enabled: false },
      });
      render(
        <AvailablePluginCard plugin={makePlugin()} appVersion={APP_VERSION} />
      );
      fireEvent.click(screen.getByTestId('sized-install-button'));
      fireEvent.click(getModalActionButton('Install'));
      await waitFor(() => {
        expect(screen.getByTestId('enable-switch')).toBeInTheDocument();
      });
    };

    it('shows enable switch in restart prompt when plugin is installed disabled', async () => {
      const { mockInstallPlugin } = setupMocks();
      await installDisabledPlugin(mockInstallPlugin);
      expect(screen.getByTestId('enable-switch')).toBeInTheDocument();
    });

    it('calls setPluginEnabled when Done is clicked with enable switch toggled on', async () => {
      const { mockInstallPlugin } = setupMocks();
      await installDisabledPlugin(mockInstallPlugin);
      fireEvent.click(screen.getByTestId('enable-switch'));
      fireEvent.click(screen.getByText('Done'));
      await waitFor(() => {
        expect(PluginsUtils.setPluginEnabled).toHaveBeenCalledWith(
          'test-plugin',
          true
        );
      });
    });

    it('does not call setPluginEnabled when enable switch is left off', async () => {
      const { mockInstallPlugin } = setupMocks();
      await installDisabledPlugin(mockInstallPlugin);
      // Do NOT toggle the switch
      fireEvent.click(screen.getByText('Done'));
      await waitFor(() => {
        expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
      });
      expect(PluginsUtils.setPluginEnabled).not.toHaveBeenCalled();
    });
  });

  // ── Deprecated plugin ──────────────────────────────────────────────────────

  describe('deprecated plugin', () => {
    it('shows deprecation warning modal when Install is clicked', () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makePlugin({ deprecated: true })}
          appVersion={APP_VERSION}
        />
      );
      fireEvent.click(screen.getByTestId('sized-install-button'));
      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'Deprecated Plugin'
      );
    });

    it('shows plugin name in deprecation warning', () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makePlugin({ deprecated: true })}
          appVersion={APP_VERSION}
        />
      );
      fireEvent.click(screen.getByTestId('sized-install-button'));
      expect(screen.getAllByText(/Test Plugin/).length).toBeGreaterThan(0);
    });

    it('Cancel in deprecation modal closes it without proceeding', () => {
      const { mockInstallPlugin } = setupMocks();
      render(
        <AvailablePluginCard
          plugin={makePlugin({ deprecated: true })}
          appVersion={APP_VERSION}
        />
      );
      fireEvent.click(screen.getByTestId('sized-install-button'));
      fireEvent.click(screen.getByText('Cancel'));
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
      expect(mockInstallPlugin).not.toHaveBeenCalled();
    });

    it('"Install Anyway" proceeds to the install confirm modal', () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makePlugin({ deprecated: true })}
          appVersion={APP_VERSION}
        />
      );
      fireEvent.click(screen.getByTestId('sized-install-button'));
      fireEvent.click(screen.getByText('Install Anyway'));
      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'Confirm Install'
      );
    });

    it('after deprecation → confirm → install, onInstalled is called', async () => {
      setupMocks();
      const onInstalled = vi.fn();
      render(
        <AvailablePluginCard
          plugin={makePlugin({ deprecated: true })}
          appVersion={APP_VERSION}
          onInstalled={onInstalled}
        />
      );
      fireEvent.click(screen.getByTestId('sized-install-button'));
      fireEvent.click(screen.getByText('Install Anyway'));
      fireEvent.click(getModalActionButton('Install'));
      await waitFor(() => {
        expect(onInstalled).toHaveBeenCalledWith('test-plugin');
      });
    });
  });

  // ── Downgrade / update confirm modal ──────────────────────────────────────

  describe('downgrade confirm modal', () => {
    const makeUpdatePlugin = () =>
      makePlugin({
        install_status: 'update_available',
        installed: true,
        installed_version: '1.1.0',
      });

    it('shows Confirm Downgrade title when getInstallInfo returns isDowngrade', () => {
      setupMocks();
      vi.mocked(getInstallInfo).mockReturnValue({
        isDowngrade: true,
        isUpdate: false,
        isBadSig: false,
      });
      render(
        <AvailablePluginCard
          plugin={makeUpdatePlugin()}
          appVersion={APP_VERSION}
        />
      );
      fireEvent.click(screen.getByTestId('sized-install-button'));
      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'Confirm Downgrade'
      );
    });

    it('shows downgrade warning when isDowngrade', () => {
      setupMocks();
      vi.mocked(getInstallInfo).mockReturnValue({
        isDowngrade: true,
        isUpdate: false,
        isBadSig: false,
      });
      render(
        <AvailablePluginCard
          plugin={makeUpdatePlugin()}
          appVersion={APP_VERSION}
        />
      );
      fireEvent.click(screen.getByTestId('sized-install-button'));
      expect(screen.getByTestId('downgrade-warning')).toBeInTheDocument();
    });

    it('shows Confirm Update title when getInstallInfo returns isUpdate', () => {
      setupMocks();
      vi.mocked(getInstallInfo).mockReturnValue({
        isDowngrade: false,
        isUpdate: true,
        isBadSig: false,
      });
      render(
        <AvailablePluginCard
          plugin={makeUpdatePlugin()}
          appVersion={APP_VERSION}
        />
      );
      fireEvent.click(screen.getByTestId('sized-install-button'));
      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'Confirm Update'
      );
    });

    it('shows restart prompt with "Plugin Downgraded" after downgrade confirms', async () => {
      setupMocks();
      vi.mocked(getInstallInfo).mockReturnValue({
        isDowngrade: true,
        isUpdate: false,
        isBadSig: false,
      });
      // compareVersions < 0 so wasDowngrade = true in executeInstall
      vi.mocked(compareVersions).mockReturnValue(-1);
      render(
        <AvailablePluginCard
          plugin={makeUpdatePlugin()}
          appVersion={APP_VERSION}
        />
      );
      fireEvent.click(screen.getByTestId('sized-install-button'));
      fireEvent.click(getModalActionButton('Downgrade'));
      await waitFor(() => {
        expect(screen.getByTestId('modal-title')).toHaveTextContent(
          'Plugin Downgraded'
        );
      });
    });

    it('shows "Plugin Updated" restart prompt after update confirms', async () => {
      setupMocks();
      vi.mocked(getInstallInfo).mockReturnValue({
        isDowngrade: false,
        isUpdate: true,
        isBadSig: false,
      });
      // installed_version set → wasInstalled = true, wasDowngrade = false (compareVersions = 0)
      render(
        <AvailablePluginCard
          plugin={makePlugin({
            install_status: 'update_available',
            installed: true,
            installed_version: '0.9.0',
          })}
          appVersion={APP_VERSION}
        />
      );
      fireEvent.click(screen.getByTestId('sized-install-button'));
      fireEvent.click(getModalActionButton('Update'));
      await waitFor(() => {
        expect(screen.getByTestId('modal-title')).toHaveTextContent(
          'Plugin Updated'
        );
      });
    });
  });

  // ── Unmanaged / different_repo notes ──────────────────────────────────────

  describe('unmanaged and different_repo notes', () => {
    it('shows info note in confirm modal for unmanaged install', () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makePlugin({ install_status: 'unmanaged' })}
          appVersion={APP_VERSION}
        />
      );
      fireEvent.click(screen.getByTestId('sized-install-button'));
      expect(screen.getByTestId('info-note')).toBeInTheDocument();
    });

    it('shows info note in confirm modal for different_repo install', () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makePlugin({
            install_status: 'different_repo',
            installed_source_repo_name: 'Other Repo',
          })}
          appVersion={APP_VERSION}
        />
      );
      fireEvent.click(screen.getByTestId('sized-install-button'));
      expect(screen.getByTestId('info-note')).toBeInTheDocument();
    });
  });

  // ── Uninstall flow ─────────────────────────────────────────────────────────

  describe('uninstall flow', () => {
    const makeInstalled = () =>
      makePlugin({
        install_status: 'installed',
        installed: true,
        installed_version: '1.0.0',
        key: 'test-plugin',
      });

    it('clicking Uninstall button opens uninstall confirm modal', () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makeInstalled()}
          appVersion={APP_VERSION}
        />
      );
      fireEvent.click(screen.getByText('Uninstall'));
      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'Uninstall Plugin'
      );
    });

    it('Cancel in uninstall confirm modal closes it without deleting', () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makeInstalled()}
          appVersion={APP_VERSION}
        />
      );
      fireEvent.click(screen.getByText('Uninstall'));
      fireEvent.click(screen.getByText('Cancel'));
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
      expect(PluginsUtils.deletePluginByKey).not.toHaveBeenCalled();
    });

    it('confirming calls deletePluginByKey with plugin key', async () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makeInstalled()}
          appVersion={APP_VERSION}
        />
      );
      fireEvent.click(screen.getByText('Uninstall'));
      // Second "Uninstall" text = modal confirm button
      fireEvent.click(screen.getAllByText('Uninstall')[1]);
      await waitFor(() => {
        expect(PluginsUtils.deletePluginByKey).toHaveBeenCalledWith(
          'test-plugin'
        );
      });
    });

    it('calls invalidatePlugins and fetchAvailablePlugins after uninstall', async () => {
      const { mockInvalidatePlugins, mockFetchAvailablePlugins } = setupMocks();
      render(
        <AvailablePluginCard
          plugin={makeInstalled()}
          appVersion={APP_VERSION}
        />
      );
      fireEvent.click(screen.getByText('Uninstall'));
      fireEvent.click(screen.getAllByText('Uninstall')[1]);
      await waitFor(() => {
        expect(mockInvalidatePlugins).toHaveBeenCalled();
        expect(mockFetchAvailablePlugins).toHaveBeenCalled();
      });
    });

    it('calls onUninstalled callback with plugin slug after uninstall', async () => {
      setupMocks();
      const onUninstalled = vi.fn();
      render(
        <AvailablePluginCard
          plugin={makeInstalled()}
          appVersion={APP_VERSION}
          onUninstalled={onUninstalled}
        />
      );
      fireEvent.click(screen.getByText('Uninstall'));
      fireEvent.click(screen.getAllByText('Uninstall')[1]);
      await waitFor(() => {
        expect(onUninstalled).toHaveBeenCalledWith('test-plugin');
      });
    });

    it('shows "Plugin Uninstalled" done modal after uninstall', async () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makeInstalled()}
          appVersion={APP_VERSION}
        />
      );
      fireEvent.click(screen.getByText('Uninstall'));
      fireEvent.click(screen.getAllByText('Uninstall')[1]);
      await waitFor(() => {
        expect(screen.getByTestId('modal-title')).toHaveTextContent(
          'Plugin Uninstalled'
        );
      });
    });

    it('Done in uninstall done modal closes it', async () => {
      setupMocks();
      render(
        <AvailablePluginCard
          plugin={makeInstalled()}
          appVersion={APP_VERSION}
        />
      );
      fireEvent.click(screen.getByText('Uninstall'));
      fireEvent.click(screen.getAllByText('Uninstall')[1]);
      await waitFor(() => {
        expect(screen.getByText('Done')).toBeInTheDocument();
      });
      fireEvent.click(screen.getByText('Done'));
      await waitFor(() => {
        expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
      });
    });

    it('does not call onUninstalled when deletePluginByKey returns no success', async () => {
      setupMocks();
      vi.mocked(PluginsUtils.deletePluginByKey).mockResolvedValue({
        success: false,
      });
      const onUninstalled = vi.fn();
      render(
        <AvailablePluginCard
          plugin={makeInstalled()}
          appVersion={APP_VERSION}
          onUninstalled={onUninstalled}
        />
      );
      fireEvent.click(screen.getByText('Uninstall'));
      fireEvent.click(screen.getAllByText('Uninstall')[1]);
      await waitFor(() => {
        expect(PluginsUtils.deletePluginByKey).toHaveBeenCalled();
      });
      expect(onUninstalled).not.toHaveBeenCalled();
    });
  });
});
