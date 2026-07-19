import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import PluginDetailPanel from '../PluginDetailPanel';

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../utils/components/pluginUtils.js', () => ({
  compareVersions: vi.fn(),
  buildCompatibilityTooltip: vi.fn(),
  buildVersionSelectItems: vi.fn(),
}));

vi.mock('../../utils/networkUtils.js', () => ({
  formatKB: vi.fn((kb) => `${kb} KB`),
}));

// ── Icon mocks ─────────────────────────────────────────────────────────────────
vi.mock('../icons.jsx', () => ({
  DiscordIcon: ({ size }) => (
    <svg data-testid="discord-icon" data-size={size} />
  ),
  GitHubIcon: ({ size }) => <svg data-testid="github-icon" data-size={size} />,
}));

vi.mock('lucide-react', () => ({
  AlertTriangle: ({ size, color }) => (
    <svg
      data-testid="icon-alert-triangle"
      data-size={size}
      data-color={color}
    />
  ),
  Ban: ({ size }) => <svg data-testid="icon-ban" data-size={size} />,
  Download: ({ size }) => <svg data-testid="icon-download" data-size={size} />,
  RefreshCw: ({ size }) => (
    <svg data-testid="icon-refresh-cw" data-size={size} />
  ),
  ShieldAlert: ({ size }) => (
    <svg data-testid="icon-shield-alert" data-size={size} />
  ),
  ShieldCheck: ({ size }) => (
    <svg data-testid="icon-shield-check" data-size={size} />
  ),
  Trash2: ({ size }) => <svg data-testid="icon-trash2" data-size={size} />,
}));

// ── Mantine core mock ──────────────────────────────────────────────────────────
vi.mock('@mantine/core', async () => ({
  ActionIcon: ({ children, href, target, rel, color }) => (
    <a
      data-testid="action-icon"
      href={href}
      target={target}
      rel={rel}
      data-color={color}
    >
      {children}
    </a>
  ),
  Alert: ({ children, title, color, icon }) => (
    <div data-testid="alert" data-color={color}>
      <div data-testid="alert-title">{title}</div>
      {icon}
      {children}
    </div>
  ),
  Badge: ({
    children,
    component,
    href,
    target,
    rel,
    leftSection,
    color,
    style,
  }) =>
    component === 'a' ? (
      <a
        data-testid="badge"
        href={href}
        target={target}
        rel={rel}
        style={style}
      >
        {leftSection}
        {children}
      </a>
    ) : (
      <span data-testid="badge" data-color={color}>
        {leftSection}
        {children}
      </span>
    ),
  Button: ({ children, onClick, disabled, variant, color, leftSection }) => (
    <button
      data-testid="button"
      onClick={onClick}
      disabled={disabled}
      data-variant={variant}
      data-color={color}
    >
      {leftSection}
      {children}
    </button>
  ),
  Group: ({ children }) => <div>{children}</div>,
  Loader: ({ size }) => <span data-testid="loader" data-size={size} />,
  Select: ({ label, value, onChange, data, disabled }) => (
    <select
      data-testid="version-select"
      value={value ?? ''}
      onChange={(e) => onChange?.(e.target.value)}
      disabled={disabled}
      aria-label={label}
    >
      {(data ?? []).map((item) => (
        <option key={item.value} value={item.value} disabled={item.disabled}>
          {item.label}
        </option>
      ))}
    </select>
  ),
  Stack: ({ children }) => <div>{children}</div>,
  Table: ({ children }) => <table>{children}</table>,
  TableTbody: ({ children }) => <tbody>{children}</tbody>,
  TableTd: ({ children, style }) => <td style={style}>{children}</td>,
  TableTr: ({ children }) => <tr>{children}</tr>,
  Text: ({ children, size, c, fw, component, href, target, rel }) =>
    component === 'a' ? (
      <a data-testid="text-link" href={href} target={target} rel={rel}>
        {children}
      </a>
    ) : (
      <span data-size={size} data-color={c} data-fw={fw}>
        {children}
      </span>
    ),
  Tooltip: ({ children, label }) => <div data-tooltip={label}>{children}</div>,
}));

// ──────────────────────────────────────────────────────────────────────────────
// Imports after mocks
// ──────────────────────────────────────────────────────────────────────────────
import {
  compareVersions,
  buildCompatibilityTooltip,
  buildVersionSelectItems,
} from '../../utils/components/pluginUtils.js';

// ──────────────────────────────────────────────────────────────────────────────
// Factories & helpers
// ──────────────────────────────────────────────────────────────────────────────

const makeVersion = (version, overrides = {}) => ({
  version,
  prerelease: false,
  url: `https://example.com/plugin-${version}.zip`,
  checksum_sha256: `sha256-${version}`,
  size: 1024,
  build_timestamp: '2024-01-15T10:00:00Z',
  min_dispatcharr_version: null,
  max_dispatcharr_version: null,
  commit_sha: `abc${version}`,
  commit_sha_short: `abc`,
  ...overrides,
});

const makeManifest = (overrides = {}) => ({
  description: 'A useful plugin.',
  author: 'Test Author',
  license: 'MIT',
  repo_url: 'https://github.com/example/plugin',
  discord_thread: null,
  deprecated: false,
  registry_url: null,
  versions: [makeVersion('2.0.0'), makeVersion('1.0.0')],
  latest: { version: '2.0.0' },
  ...overrides,
});

const makeDetail = (manifestOverrides = {}, overrides = {}) => ({
  manifest: makeManifest(manifestOverrides),
  signature_verified: true,
  ...overrides,
});

const defaultProps = (overrides = {}) => ({
  detail: makeDetail(),
  detailLoading: false,
  selectedVersion: '2.0.0',
  onVersionChange: vi.fn(),
  installedVersion: null,
  installedVersionIsPrerelease: false,
  appVersion: '1.5.0',
  installing: false,
  uninstalling: false,
  onInstall: vi.fn(),
  onUninstall: vi.fn(),
  installStatus: 'not_installed',
  installedSourceRepoName: null,
  repoId: 1,
  slug: 'my-plugin',
  ...overrides,
});

// ──────────────────────────────────────────────────────────────────────────────

describe('PluginDetailPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // default: every compareVersions call returns 0 (versions equal) unless
    // individual tests override it
    vi.mocked(compareVersions).mockReturnValue(0);
    vi.mocked(buildCompatibilityTooltip).mockReturnValue('1.0.0 or newer');
    // default: buildVersionSelectItems returns two standard items so that
    // any test rendering the version select has populated options
    vi.mocked(buildVersionSelectItems).mockReturnValue([
      { value: '2.0.0', label: 'v2.0.0 (latest)', disabled: false },
      { value: '1.0.0', label: 'v1.0.0', disabled: false },
    ]);
  });

  // ── Loading & error states ─────────────────────────────────────────────────

  describe('loading and error states', () => {
    it('shows a loader when detailLoading is true', () => {
      render(<PluginDetailPanel {...defaultProps({ detailLoading: true })} />);
      expect(screen.getByTestId('loader')).toBeInTheDocument();
      expect(screen.getByText(/Loading plugin details/i)).toBeInTheDocument();
    });

    it('shows error text when detail is null', () => {
      render(
        <PluginDetailPanel
          {...defaultProps({ detail: null, detailLoading: false })}
        />
      );
      expect(
        screen.getByText(/Failed to load plugin details/i)
      ).toBeInTheDocument();
    });

    it('shows error text when detail has no manifest', () => {
      render(
        <PluginDetailPanel
          {...defaultProps({ detail: {}, detailLoading: false })}
        />
      );
      expect(
        screen.getByText(/Failed to load plugin details/i)
      ).toBeInTheDocument();
    });
  });

  // ── Description ───────────────────────────────────────────────────────────

  describe('description', () => {
    it('renders manifest description', () => {
      render(<PluginDetailPanel {...defaultProps()} />);
      expect(screen.getByText('A useful plugin.')).toBeInTheDocument();
    });

    it('does not render description section when absent', () => {
      render(
        <PluginDetailPanel
          {...defaultProps({ detail: makeDetail({ description: null }) })}
        />
      );
      expect(screen.queryByText('A useful plugin.')).not.toBeInTheDocument();
    });
  });

  // ── Author & license badges ────────────────────────────────────────────────

  describe('author and license badges', () => {
    it('renders author badge', () => {
      render(<PluginDetailPanel {...defaultProps()} />);
      expect(screen.getByText('Test Author')).toBeInTheDocument();
    });

    it('does not render author badge when author is absent', () => {
      render(
        <PluginDetailPanel
          {...defaultProps({ detail: makeDetail({ author: null }) })}
        />
      );
      expect(screen.queryByText('Test Author')).not.toBeInTheDocument();
    });

    it('renders license badge as a link to spdx.org', () => {
      render(<PluginDetailPanel {...defaultProps()} />);
      const badge = screen
        .getAllByTestId('badge')
        .find((el) => el.tagName === 'A' && el.href?.includes('spdx.org'));
      expect(badge).toBeTruthy();
      expect(badge.href).toContain('MIT');
    });

    it('does not render license badge when license is absent', () => {
      render(
        <PluginDetailPanel
          {...defaultProps({ detail: makeDetail({ license: null }) })}
        />
      );
      const badges = screen.getAllByTestId('badge');
      expect(badges.find((b) => b.href?.includes('spdx.org'))).toBeUndefined();
    });
  });

  // ── Signature badges ───────────────────────────────────────────────────────

  describe('signature badge', () => {
    it('shows "Verified Signature" badge when signature_verified is true', () => {
      render(<PluginDetailPanel {...defaultProps()} />);
      expect(screen.getByText('Verified Signature')).toBeInTheDocument();
      expect(screen.getByTestId('icon-shield-check')).toBeInTheDocument();
    });

    it('shows "Unverified" badge when signature_verified is false', () => {
      render(
        <PluginDetailPanel
          {...defaultProps({
            detail: makeDetail({}, { signature_verified: false }),
          })}
        />
      );
      expect(screen.getByText('Unverified')).toBeInTheDocument();
      expect(screen.getByTestId('icon-shield-alert')).toBeInTheDocument();
    });

    it('renders no signature badge when signature_verified is null', () => {
      render(
        <PluginDetailPanel
          {...defaultProps({
            detail: makeDetail({}, { signature_verified: null }),
          })}
        />
      );
      expect(screen.queryByText('Verified Signature')).not.toBeInTheDocument();
      expect(screen.queryByText('Unverified')).not.toBeInTheDocument();
    });
  });

  // ── GitHub link ────────────────────────────────────────────────────────────

  describe('GitHub link', () => {
    it('renders GitHub icon linking to repo_url', () => {
      render(<PluginDetailPanel {...defaultProps()} />);
      expect(screen.getByTestId('github-icon')).toBeInTheDocument();
      const link = screen
        .getAllByTestId('action-icon')
        .find((el) => el.href?.includes('github.com'));
      expect(link).toBeTruthy();
    });

    it('does not render GitHub icon when repo_url is absent', () => {
      render(
        <PluginDetailPanel
          {...defaultProps({ detail: makeDetail({ repo_url: null }) })}
        />
      );
      expect(screen.queryByTestId('github-icon')).not.toBeInTheDocument();
    });
  });

  // ── Discord link ───────────────────────────────────────────────────────────

  describe('Discord link', () => {
    it('renders Discord icon when discord_thread is set', () => {
      render(
        <PluginDetailPanel
          {...defaultProps({
            detail: makeDetail({
              discord_thread: 'https://example.com/discord',
            }),
          })}
        />
      );
      expect(screen.getByTestId('discord-icon')).toBeInTheDocument();
    });

    it('does not render Discord icon when discord_thread is null', () => {
      render(<PluginDetailPanel {...defaultProps()} />);
      expect(screen.queryByTestId('discord-icon')).not.toBeInTheDocument();
    });

    it('rewrites discord.com/channels URL to discord:// protocol', () => {
      render(
        <PluginDetailPanel
          {...defaultProps({
            detail: makeDetail({
              discord_thread: 'https://discord.com/channels/123/456',
            }),
          })}
        />
      );
      const link = screen
        .getAllByTestId('action-icon')
        .find((el) => el.href?.startsWith('discord://'));
      expect(link).toBeTruthy();
    });

    it('keeps non-discord.com/channels URL unchanged', () => {
      const url = 'https://discord.gg/invite/abc';
      render(
        <PluginDetailPanel
          {...defaultProps({
            detail: makeDetail({ discord_thread: url }),
          })}
        />
      );
      const link = screen
        .getAllByTestId('action-icon')
        .find((el) => el.href === url);
      expect(link).toBeTruthy();
    });
  });

  // ── Deprecated alert ───────────────────────────────────────────────────────

  describe('deprecated alert', () => {
    it('shows deprecated alert when deprecated is true', () => {
      render(
        <PluginDetailPanel
          {...defaultProps({ detail: makeDetail({ deprecated: true }) })}
        />
      );
      expect(screen.getByTestId('alert')).toBeInTheDocument();
      expect(screen.getByTestId('alert-title')).toHaveTextContent(
        'Deprecated Plugin'
      );
      expect(screen.getByTestId('icon-ban')).toBeInTheDocument();
    });

    it('does not show deprecated alert when deprecated is false', () => {
      render(<PluginDetailPanel {...defaultProps()} />);
      expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
    });
  });

  // ── Version select ─────────────────────────────────────────────────────────

  describe('version select', () => {
    it('renders the version select when versions exist', () => {
      render(<PluginDetailPanel {...defaultProps()} />);
      expect(screen.getByTestId('version-select')).toBeInTheDocument();
    });

    it('does not render version select when versions list is empty', () => {
      render(
        <PluginDetailPanel
          {...defaultProps({ detail: makeDetail({ versions: [] }) })}
        />
      );
      expect(screen.queryByTestId('version-select')).not.toBeInTheDocument();
    });

    it('renders options from buildVersionSelectItems return value', () => {
      render(<PluginDetailPanel {...defaultProps()} />);
      // default mock returns v2.0.0 (latest) and v1.0.0
      expect(screen.getByText('v2.0.0 (latest)')).toBeInTheDocument();
      expect(screen.getByText('v1.0.0')).toBeInTheDocument();
    });

    it('calls buildVersionSelectItems with manifest versions, latest version, installedVersion, and installedVersionIsPrerelease', () => {
      const detail = makeDetail({
        versions: [makeVersion('2.0.0'), makeVersion('1.0.0')],
        latest: { version: '2.0.0' },
      });
      render(
        <PluginDetailPanel
          {...defaultProps({
            detail,
            installedVersion: '1.0.0',
            installedVersionIsPrerelease: false,
          })}
        />
      );
      expect(buildVersionSelectItems).toHaveBeenCalledWith(
        detail.manifest.versions,
        '2.0.0',
        '1.0.0',
        false
      );
    });

    it('passes installedVersionIsPrerelease=true to buildVersionSelectItems', () => {
      render(
        <PluginDetailPanel
          {...defaultProps({
            installedVersion: '2.0.0-beta',
            installedVersionIsPrerelease: true,
          })}
        />
      );
      expect(buildVersionSelectItems).toHaveBeenCalledWith(
        expect.any(Array),
        expect.anything(),
        '2.0.0-beta',
        true
      );
    });

    it('passes null installedVersion to buildVersionSelectItems when not installed', () => {
      render(
        <PluginDetailPanel {...defaultProps({ installedVersion: null })} />
      );
      expect(buildVersionSelectItems).toHaveBeenCalledWith(
        expect.any(Array),
        expect.anything(),
        null,
        false
      );
    });

    it('does not call buildVersionSelectItems when versions list is empty', () => {
      render(
        <PluginDetailPanel
          {...defaultProps({ detail: makeDetail({ versions: [] }) })}
        />
      );
      expect(buildVersionSelectItems).not.toHaveBeenCalled();
    });

    it('renders a disabled ghost option when buildVersionSelectItems returns one', () => {
      vi.mocked(buildVersionSelectItems).mockReturnValue([
        { value: '2.0.0', label: 'v2.0.0 (latest)', disabled: false },
        { value: '1.5.0', label: 'v1.5.0 (installed)', disabled: true },
        { value: '1.0.0', label: 'v1.0.0', disabled: false },
      ]);
      render(
        <PluginDetailPanel
          {...defaultProps({
            installedVersion: '1.5.0',
            installStatus: 'installed',
          })}
        />
      );
      const ghostOption = screen
        .getAllByRole('option')
        .find((o) => o.value === '1.5.0');
      expect(ghostOption).toBeTruthy();
      expect(ghostOption.disabled).toBe(true);
    });

    it('calls onVersionChange when version select changes', () => {
      const onVersionChange = vi.fn();
      render(<PluginDetailPanel {...defaultProps({ onVersionChange })} />);
      fireEvent.change(screen.getByTestId('version-select'), {
        target: { value: '1.0.0' },
      });
      expect(onVersionChange).toHaveBeenCalledWith('1.0.0');
    });
  });

  // ── Install button ─────────────────────────────────────────────────────────

  describe('install button', () => {
    it('shows "Install" button when plugin is not installed', () => {
      render(<PluginDetailPanel {...defaultProps()} />);
      expect(screen.getByTestId('button')).toHaveTextContent('Install');
    });

    it('calls onInstall with correct params when Install is clicked', () => {
      const onInstall = vi.fn();
      render(<PluginDetailPanel {...defaultProps({ onInstall })} />);
      fireEvent.click(screen.getByTestId('button'));
      expect(onInstall).toHaveBeenCalledWith(
        expect.objectContaining({
          slug: 'my-plugin',
          version: '2.0.0',
          download_url: 'https://example.com/plugin-2.0.0.zip',
        })
      );
    });

    it('shows installing spinner while installing is true', () => {
      render(<PluginDetailPanel {...defaultProps({ installing: true })} />);
      expect(screen.getByTestId('button')).toHaveTextContent('Installing…');
      expect(screen.getByTestId('loader')).toBeInTheDocument();
    });

    it('shows "Update" button when a newer version is selected over installed', () => {
      vi.mocked(compareVersions).mockImplementation((a, b) => {
        const strip = (v) => v.replace(/^v/, '');
        const pa = strip(a).split('.').map(Number);
        const pb = strip(b).split('.').map(Number);
        for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
          const d = (pa[i] || 0) - (pb[i] || 0);
          if (d !== 0) return d;
        }
        return 0;
      });
      render(
        <PluginDetailPanel
          {...defaultProps({
            installedVersion: '1.0.0',
            selectedVersion: '2.0.0',
            installStatus: 'installed',
          })}
        />
      );
      expect(screen.getByTestId('button')).toHaveTextContent('Update');
    });

    it('shows "Downgrade" button when an older version is selected over installed', () => {
      vi.mocked(compareVersions).mockImplementation((a, b) => {
        const strip = (v) => v.replace(/^v/, '');
        const pa = strip(a).split('.').map(Number);
        const pb = strip(b).split('.').map(Number);
        for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
          const d = (pa[i] || 0) - (pb[i] || 0);
          if (d !== 0) return d;
        }
        return 0;
      });
      render(
        <PluginDetailPanel
          {...defaultProps({
            installedVersion: '2.0.0',
            selectedVersion: '1.0.0',
            installStatus: 'installed',
          })}
        />
      );
      expect(screen.getByTestId('button')).toHaveTextContent('Downgrade');
    });

    it('shows "Uninstall" button when installed version equals selected version', () => {
      vi.mocked(compareVersions).mockReturnValue(0);
      render(
        <PluginDetailPanel
          {...defaultProps({
            installedVersion: '2.0.0',
            selectedVersion: '2.0.0',
            installStatus: 'installed',
          })}
        />
      );
      expect(screen.getByTestId('button')).toHaveTextContent('Uninstall');
    });

    it('calls onUninstall when Uninstall is clicked', () => {
      vi.mocked(compareVersions).mockReturnValue(0);
      const onUninstall = vi.fn();
      render(
        <PluginDetailPanel
          {...defaultProps({
            installedVersion: '2.0.0',
            selectedVersion: '2.0.0',
            installStatus: 'installed',
            onUninstall,
          })}
        />
      );
      fireEvent.click(screen.getByTestId('button'));
      expect(onUninstall).toHaveBeenCalled();
    });

    it('shows "Uninstalling…" and loader while uninstalling', () => {
      vi.mocked(compareVersions).mockReturnValue(0);
      render(
        <PluginDetailPanel
          {...defaultProps({
            installedVersion: '2.0.0',
            selectedVersion: '2.0.0',
            installStatus: 'installed',
            uninstalling: true,
          })}
        />
      );
      expect(screen.getByTestId('button')).toHaveTextContent('Uninstalling…');
    });

    it('shows "Overwrite" for unmanaged install status', () => {
      render(
        <PluginDetailPanel {...defaultProps({ installStatus: 'unmanaged' })} />
      );
      expect(screen.getByTestId('button')).toHaveTextContent('Overwrite');
    });

    it('shows "Overwrite" for different_repo install status', () => {
      render(
        <PluginDetailPanel
          {...defaultProps({
            installStatus: 'different_repo',
            installedSourceRepoName: 'Other Repo',
          })}
        />
      );
      expect(screen.getByTestId('button')).toHaveTextContent('Overwrite');
    });

    it('disables install button when no selectedVersionData url', () => {
      const detail = makeDetail({
        versions: [makeVersion('2.0.0', { url: null })],
        latest: { version: '2.0.0' },
      });
      render(<PluginDetailPanel {...defaultProps({ detail })} />);
      expect(screen.getByTestId('button')).toBeDisabled();
    });

    it('shows "Incompatible" when version does not meet min requirement', () => {
      // selMeetsMin=false: appVersion < min_dispatcharr_version
      vi.mocked(compareVersions).mockImplementation((a, b) => {
        // appVersion (1.5.0) vs min (2.0.0): return negative
        if (a === '1.5.0' && b === '2.0.0') return -1;
        return 0;
      });
      const detail = makeDetail({
        versions: [makeVersion('2.0.0', { min_dispatcharr_version: '2.0.0' })],
        latest: { version: '2.0.0' },
      });
      render(
        <PluginDetailPanel {...defaultProps({ detail, appVersion: '1.5.0' })} />
      );
      expect(screen.getByTestId('button')).toHaveTextContent('Incompatible');
    });
  });

  // ── Compatibility warning ──────────────────────────────────────────────────

  describe('compatibility warning', () => {
    it('shows compatibility warning tooltip when version is incompatible and not same as installed', () => {
      vi.mocked(compareVersions).mockImplementation((a, b) => {
        if (a === '1.5.0' && b === '2.0.0') return -1;
        return 0;
      });
      vi.mocked(buildCompatibilityTooltip).mockReturnValue('2.0.0 or newer');
      const detail = makeDetail({
        versions: [makeVersion('2.0.0', { min_dispatcharr_version: '2.0.0' })],
        latest: { version: '2.0.0' },
      });
      render(
        <PluginDetailPanel {...defaultProps({ detail, appVersion: '1.5.0' })} />
      );
      const tooltip = screen
        .getAllByRole('generic')
        .find((el) =>
          el.getAttribute('data-tooltip')?.includes('Incompatible')
        );
      expect(tooltip).toBeTruthy();
    });
  });

  // ── Version detail table ───────────────────────────────────────────────────

  describe('version detail table', () => {
    it('renders build timestamp', () => {
      render(<PluginDetailPanel {...defaultProps()} />);
      // The date is locale-formatted; just check the "Built" label exists
      expect(screen.getByText('Built')).toBeInTheDocument();
    });

    it('renders file size via formatKB', () => {
      render(<PluginDetailPanel {...defaultProps()} />);
      expect(screen.getByText('File Size')).toBeInTheDocument();
      expect(screen.getByText('1024 KB')).toBeInTheDocument();
    });

    it('does not render file size row when size is 0', () => {
      const detail = makeDetail({
        versions: [makeVersion('2.0.0', { size: 0 })],
        latest: { version: '2.0.0' },
      });
      render(<PluginDetailPanel {...defaultProps({ detail })} />);
      expect(screen.queryByText('File Size')).not.toBeInTheDocument();
    });

    it('renders min version row when present', () => {
      const detail = makeDetail({
        versions: [makeVersion('2.0.0', { min_dispatcharr_version: '1.0.0' })],
        latest: { version: '2.0.0' },
      });
      render(<PluginDetailPanel {...defaultProps({ detail })} />);
      expect(screen.getByText('Min Version')).toBeInTheDocument();
      expect(screen.getByText('1.0.0')).toBeInTheDocument();
    });

    it('does not render min version row when absent', () => {
      render(<PluginDetailPanel {...defaultProps()} />);
      expect(screen.queryByText('Min Version')).not.toBeInTheDocument();
    });

    it('renders max version row when present', () => {
      const detail = makeDetail({
        versions: [makeVersion('2.0.0', { max_dispatcharr_version: '3.0.0' })],
        latest: { version: '2.0.0' },
      });
      render(<PluginDetailPanel {...defaultProps({ detail })} />);
      expect(screen.getByText('Max Version')).toBeInTheDocument();
      expect(screen.getByText('3.0.0')).toBeInTheDocument();
    });

    it('renders commit short SHA', () => {
      render(<PluginDetailPanel {...defaultProps()} />);
      expect(screen.getByText('Commit')).toBeInTheDocument();
      expect(screen.getByText('abc')).toBeInTheDocument();
    });

    it('renders commit as a link when registry_url is present', () => {
      const detail = makeDetail({
        registry_url: 'https://github.com/example/plugin',
        versions: [makeVersion('2.0.0', { commit_sha: 'abc123full' })],
        latest: { version: '2.0.0' },
      });
      render(<PluginDetailPanel {...defaultProps({ detail })} />);
      const commitLink = screen
        .getAllByTestId('text-link')
        .find((el) => el.href?.includes('abc123full'));
      expect(commitLink).toBeTruthy();
    });

    it('renders download URL as a link', () => {
      render(<PluginDetailPanel {...defaultProps()} />);
      expect(screen.getByText('Download')).toBeInTheDocument();
      const link = screen
        .getAllByTestId('text-link')
        .find((el) => el.href?.includes('plugin-2.0.0.zip'));
      expect(link).toBeTruthy();
    });
  });

  // ── buildVersionSelectItems integration ───────────────────────────────────

  describe('buildVersionSelectItems integration', () => {
    it('passes manifest.latest.version to buildVersionSelectItems', () => {
      const detail = makeDetail({ latest: { version: '2.0.0' } });
      render(<PluginDetailPanel {...defaultProps({ detail })} />);
      expect(buildVersionSelectItems).toHaveBeenCalledWith(
        detail.manifest.versions,
        '2.0.0',
        null, // installedVersion from defaultProps
        false // installedVersionIsPrerelease from defaultProps
      );
    });

    it('passes undefined latest to buildVersionSelectItems when manifest.latest is absent', () => {
      const detail = makeDetail({ latest: null });
      render(<PluginDetailPanel {...defaultProps({ detail })} />);
      expect(buildVersionSelectItems).toHaveBeenCalledWith(
        detail.manifest.versions,
        undefined,
        null, // installedVersion from defaultProps
        false // installedVersionIsPrerelease from defaultProps
      );
    });

    it('Select data reflects exactly what buildVersionSelectItems returns', () => {
      const customItems = [
        { value: '3.0.0', label: 'v3.0.0 (latest)', disabled: false },
        { value: '2.0.0', label: 'v2.0.0 (installed)', disabled: false },
      ];
      vi.mocked(buildVersionSelectItems).mockReturnValue(customItems);
      render(
        <PluginDetailPanel {...defaultProps({ selectedVersion: '3.0.0' })} />
      );
      const options = screen.getAllByRole('option');
      expect(options).toHaveLength(2);
      expect(options[0].value).toBe('3.0.0');
      expect(options[1].value).toBe('2.0.0');
    });
  });
});
