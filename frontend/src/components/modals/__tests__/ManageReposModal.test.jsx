import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Store mock ─────────────────────────────────────────────────────────────────
vi.mock('../../../store/plugins.jsx', () => ({
  usePluginStore: vi.fn(),
}));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

vi.mock('../../../utils/pages/PluginsUtils.js', () => ({
  getPluginRepoSettings: vi.fn(),
  previewPluginRepo: vi.fn(),
  updatePluginRepoSettings: vi.fn(),
}));

// ── ConfirmationDialog mock ────────────────────────────────────────────────────
vi.mock('../../ConfirmationDialog.jsx', () => ({
  default: ({ opened, onClose, onConfirm, title, confirmLabel }) =>
    opened ? (
      <div data-testid="confirmation-dialog">
        <div data-testid="dialog-title">{title}</div>
        <button data-testid="dialog-confirm" onClick={onConfirm}>
          {confirmLabel || 'Confirm'}
        </button>
        <button data-testid="dialog-close" onClick={onClose}>
          Cancel
        </button>
      </div>
    ) : null,
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  KeyRound: () => <svg data-testid="icon-key-round" />,
  Plus: () => <svg data-testid="icon-plus" />,
  ShieldAlert: () => <svg data-testid="icon-shield-alert" />,
  ShieldCheck: () => <svg data-testid="icon-shield-check" />,
  Trash2: () => <svg data-testid="icon-trash-2" />,
}));

// ── @mantine/core ──────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  ActionIcon: ({ children, onClick, title, color, variant }) => (
    <button
      data-testid="action-icon"
      title={title}
      data-color={color}
      data-variant={variant}
      onClick={onClick}
    >
      {children}
    </button>
  ),
  Badge: ({ children, color, variant, leftSection }) => (
    <span data-testid="badge" data-color={color} data-variant={variant}>
      {leftSection}
      {children}
    </span>
  ),
  Box: ({ children }) => <div>{children}</div>,
  Button: ({
    children,
    onClick,
    loading,
    disabled,
    variant,
    color,
    leftSection,
  }) => (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      data-loading={loading}
      data-variant={variant}
      data-color={color}
    >
      {leftSection}
      {children}
    </button>
  ),
  Group: ({ children }) => <div>{children}</div>,
  Loader: ({ size }) => <div data-testid="loader" data-size={size} />,
  Modal: ({ children, opened, onClose, title }) =>
    opened ? (
      <div data-testid="modal">
        <div data-testid="modal-header">{title}</div>
        <button data-testid="modal-close" onClick={onClose}>
          ×
        </button>
        {children}
      </div>
    ) : null,
  NumberInput: ({ value, onChange, min, max, disabled }) => (
    <input
      type="number"
      data-testid="refresh-interval-input"
      value={value ?? ''}
      onChange={(e) => onChange(Number(e.target.value))}
      min={min}
      max={max}
      disabled={disabled}
    />
  ),
  Stack: ({ children }) => <div>{children}</div>,
  Text: ({ children, fw, size, c }) => (
    <span data-fw={fw} data-size={size} data-color={c}>
      {children}
    </span>
  ),
  Textarea: ({ value, onChange, placeholder, onFocus, onBlur }) => (
    <textarea
      data-testid="textarea"
      value={value ?? ''}
      onChange={onChange}
      placeholder={placeholder}
      onFocus={onFocus}
      onBlur={onBlur}
    />
  ),
  TextInput: ({ value, onChange, placeholder }) => (
    <input
      data-testid="repo-url-input"
      value={value ?? ''}
      onChange={onChange}
      placeholder={placeholder}
    />
  ),
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import ManageReposModal from '../ManageReposModal';
import { usePluginStore } from '../../../store/plugins.jsx';
import { showNotification } from '../../../utils/notificationUtils.js';
import {
  getPluginRepoSettings,
  previewPluginRepo,
  updatePluginRepoSettings,
} from '../../../utils/pages/PluginsUtils.js';

// ── Shared helpers ─────────────────────────────────────────────────────────────
const makeRepo = (overrides = {}) => ({
  id: 1,
  name: 'Main Repo',
  url: 'https://example.com/manifest.json',
  is_official: false,
  signature_verified: null,
  registry_url: null,
  last_fetched: null,
  last_fetch_status: null,
  plugin_count: null,
  public_key: '',
  ...overrides,
});

let mockFetchAvailablePlugins;
let mockRefreshRepo;
let mockAddRepo;
let mockRemoveRepo;
let mockUpdateRepo;

const setupStore = ({ repos = [], reposLoading = false } = {}) => {
  mockFetchAvailablePlugins = vi.fn().mockResolvedValue(undefined);
  mockRefreshRepo = vi.fn().mockResolvedValue(undefined);
  mockAddRepo = vi.fn().mockResolvedValue(undefined);
  mockRemoveRepo = vi.fn().mockResolvedValue(undefined);
  mockUpdateRepo = vi.fn().mockResolvedValue(undefined);

  vi.mocked(usePluginStore).mockImplementation((sel) =>
    sel({
      repos,
      reposLoading,
      fetchAvailablePlugins: mockFetchAvailablePlugins,
      refreshRepo: mockRefreshRepo,
      addRepo: mockAddRepo,
      removeRepo: mockRemoveRepo,
      updateRepo: mockUpdateRepo,
    })
  );
};

const defaultProps = (overrides = {}) => ({
  opened: true,
  onClose: vi.fn(),
  ...overrides,
});

// ──────────────────────────────────────────────────────────────────────────────

describe('ManageReposModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupStore();
    vi.mocked(getPluginRepoSettings).mockResolvedValue({
      refresh_interval_hours: 6,
    });
    vi.mocked(updatePluginRepoSettings).mockResolvedValue(undefined);
    vi.mocked(previewPluginRepo).mockResolvedValue(null);
  });

  // ── Visibility ─────────────────────────────────────────────────────────────

  describe('visibility', () => {
    it('renders the modal when opened is true', () => {
      render(<ManageReposModal {...defaultProps()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('does not render the modal when opened is false', () => {
      render(<ManageReposModal {...defaultProps({ opened: false })} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('calls onClose when the close button is clicked', () => {
      const onClose = vi.fn();
      render(<ManageReposModal {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
    });
  });

  // ── Settings load ──────────────────────────────────────────────────────────

  describe('settings load', () => {
    it('calls getPluginRepoSettings when opened', async () => {
      render(<ManageReposModal {...defaultProps()} />);
      await waitFor(() => {
        expect(getPluginRepoSettings).toHaveBeenCalledTimes(1);
      });
    });

    it('does not call getPluginRepoSettings when closed', async () => {
      render(<ManageReposModal {...defaultProps({ opened: false })} />);
      expect(getPluginRepoSettings).not.toHaveBeenCalled();
    });

    it('loads the refresh interval from settings', async () => {
      vi.mocked(getPluginRepoSettings).mockResolvedValue({
        refresh_interval_hours: 24,
      });
      render(<ManageReposModal {...defaultProps()} />);
      await waitFor(() => {
        expect(screen.getByTestId('refresh-interval-input')).toHaveValue(24);
      });
    });
  });

  // ── Repos list ─────────────────────────────────────────────────────────────

  describe('repos list', () => {
    it('renders a row for each repo', () => {
      setupStore({
        repos: [
          makeRepo({ id: 1, name: 'Repo A' }),
          makeRepo({ id: 2, name: 'Repo B' }),
        ],
      });
      render(<ManageReposModal {...defaultProps()} />);
      expect(screen.getByText('Repo A')).toBeInTheDocument();
      expect(screen.getByText('Repo B')).toBeInTheDocument();
    });

    it('shows loader when loading and no repos are present', () => {
      setupStore({ reposLoading: true, repos: [] });
      render(<ManageReposModal {...defaultProps()} />);
      expect(screen.getByTestId('loader')).toBeInTheDocument();
    });

    it('does not show loader when repos are present', () => {
      setupStore({ reposLoading: true, repos: [makeRepo()] });
      render(<ManageReposModal {...defaultProps()} />);
      expect(screen.queryByTestId('loader')).not.toBeInTheDocument();
    });

    it('shows "Official Repo" badge for official repos', () => {
      setupStore({ repos: [makeRepo({ is_official: true })] });
      render(<ManageReposModal {...defaultProps()} />);
      expect(screen.getByText('Official Repo')).toBeInTheDocument();
    });

    it('shows "Verified Signature" badge when signature_verified is true', () => {
      setupStore({ repos: [makeRepo({ signature_verified: true })] });
      render(<ManageReposModal {...defaultProps()} />);
      expect(screen.getByText('Verified Signature')).toBeInTheDocument();
    });

    it('shows "Invalid Signature" badge when signature_verified is false', () => {
      setupStore({ repos: [makeRepo({ signature_verified: false })] });
      render(<ManageReposModal {...defaultProps()} />);
      expect(screen.getByText('Invalid Signature')).toBeInTheDocument();
    });

    it('shows edit and delete buttons only for non-official repos', () => {
      setupStore({ repos: [makeRepo({ is_official: false })] });
      render(<ManageReposModal {...defaultProps()} />);
      expect(screen.getByTitle('Edit public key')).toBeInTheDocument();
      expect(screen.getByTitle('Remove repo')).toBeInTheDocument();
    });

    it('does not show edit and delete buttons for official repos', () => {
      setupStore({ repos: [makeRepo({ is_official: true })] });
      render(<ManageReposModal {...defaultProps()} />);
      expect(screen.queryByTitle('Edit public key')).not.toBeInTheDocument();
      expect(screen.queryByTitle('Remove repo')).not.toBeInTheDocument();
    });
  });

  // ── Refresh interval ───────────────────────────────────────────────────────

  describe('refresh interval', () => {
    it('calls updatePluginRepoSettings (debounced) when interval changes', async () => {
      vi.useFakeTimers();
      render(<ManageReposModal {...defaultProps()} />);
      await act(async () => {
        await vi.runAllTimersAsync(); // flush loadRepoSettings
      });

      fireEvent.change(screen.getByTestId('refresh-interval-input'), {
        target: { value: '12' },
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(900);
      });

      expect(updatePluginRepoSettings).toHaveBeenCalledWith({
        refresh_interval_hours: 12,
      });
      vi.useRealTimers();
    });

    it('does not call updatePluginRepoSettings before the debounce delay', async () => {
      vi.useFakeTimers();
      render(<ManageReposModal {...defaultProps()} />);
      await act(async () => {
        await vi.runAllTimersAsync();
      });

      fireEvent.change(screen.getByTestId('refresh-interval-input'), {
        target: { value: '12' },
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(400);
      });
      expect(updatePluginRepoSettings).not.toHaveBeenCalled();
      vi.useRealTimers();
    });
  });

  // ── Edit public key ────────────────────────────────────────────────────────

  describe('edit public key', () => {
    it('shows key editor when Edit button is clicked', () => {
      setupStore({ repos: [makeRepo({ id: 1 })] });
      render(<ManageReposModal {...defaultProps()} />);
      fireEvent.click(screen.getByTitle('Edit public key'));
      expect(screen.getByTestId('textarea')).toBeInTheDocument();
      expect(screen.getByText('Save Key')).toBeInTheDocument();
    });

    it('pre-fills key editor with existing public key', () => {
      setupStore({ repos: [makeRepo({ id: 1, public_key: 'existing-key' })] });
      render(<ManageReposModal {...defaultProps()} />);
      fireEvent.click(screen.getByTitle('Edit public key'));
      expect(screen.getByTestId('textarea')).toHaveValue('existing-key');
    });

    it('hides key editor when Cancel is clicked', () => {
      setupStore({ repos: [makeRepo({ id: 1 })] });
      render(<ManageReposModal {...defaultProps()} />);
      fireEvent.click(screen.getByTitle('Edit public key'));
      fireEvent.click(screen.getByText('Cancel'));
      expect(screen.queryByText('Save Key')).not.toBeInTheDocument();
    });

    it('calls updateRepo, refreshRepo, and fetchAvailablePlugins on Save Key', async () => {
      setupStore({ repos: [makeRepo({ id: 7 })] });
      render(<ManageReposModal {...defaultProps()} />);
      fireEvent.click(screen.getByTitle('Edit public key'));
      fireEvent.change(screen.getByTestId('textarea'), {
        target: { value: 'new-key' },
      });
      fireEvent.click(screen.getByText('Save Key'));
      await waitFor(() => {
        expect(mockUpdateRepo).toHaveBeenCalledWith(7, {
          public_key: 'new-key',
        });
        expect(mockRefreshRepo).toHaveBeenCalledWith(7);
        expect(mockFetchAvailablePlugins).toHaveBeenCalled();
      });
    });

    it('shows "Updated" notification after successful key save', async () => {
      setupStore({ repos: [makeRepo({ id: 1 })] });
      render(<ManageReposModal {...defaultProps()} />);
      fireEvent.click(screen.getByTitle('Edit public key'));
      fireEvent.click(screen.getByText('Save Key'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Updated', color: 'green' })
        );
      });
    });

    it('shows error notification when key save fails', async () => {
      mockUpdateRepo = vi.fn().mockRejectedValue(new Error('Network error'));
      vi.mocked(usePluginStore).mockImplementation((sel) =>
        sel({
          repos: [makeRepo({ id: 1 })],
          reposLoading: false,
          fetchAvailablePlugins: mockFetchAvailablePlugins,
          refreshRepo: mockRefreshRepo,
          addRepo: mockAddRepo,
          removeRepo: mockRemoveRepo,
          updateRepo: mockUpdateRepo,
        })
      );
      render(<ManageReposModal {...defaultProps()} />);
      fireEvent.click(screen.getByTitle('Edit public key'));
      fireEvent.click(screen.getByText('Save Key'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Error', color: 'red' })
        );
      });
    });

    it('closes key editor after successful save', async () => {
      setupStore({ repos: [makeRepo({ id: 1 })] });
      render(<ManageReposModal {...defaultProps()} />);
      fireEvent.click(screen.getByTitle('Edit public key'));
      fireEvent.click(screen.getByText('Save Key'));
      await waitFor(() => {
        expect(screen.queryByText('Save Key')).not.toBeInTheDocument();
      });
    });
  });

  // ── Delete repo ────────────────────────────────────────────────────────────

  describe('delete repo', () => {
    it('opens ConfirmationDialog when delete button is clicked', () => {
      setupStore({ repos: [makeRepo({ id: 1 })] });
      render(<ManageReposModal {...defaultProps()} />);
      fireEvent.click(screen.getByTitle('Remove repo'));
      expect(screen.getByTestId('confirmation-dialog')).toBeInTheDocument();
      expect(screen.getByTestId('dialog-title')).toHaveTextContent(
        'Remove Repository'
      );
    });

    it('closes ConfirmationDialog when cancelled', () => {
      setupStore({ repos: [makeRepo({ id: 1 })] });
      render(<ManageReposModal {...defaultProps()} />);
      fireEvent.click(screen.getByTitle('Remove repo'));
      fireEvent.click(screen.getByTestId('dialog-close'));
      expect(
        screen.queryByTestId('confirmation-dialog')
      ).not.toBeInTheDocument();
    });

    it('calls removeRepo and fetchAvailablePlugins when confirmed', async () => {
      setupStore({ repos: [makeRepo({ id: 5 })] });
      render(<ManageReposModal {...defaultProps()} />);
      fireEvent.click(screen.getByTitle('Remove repo'));
      fireEvent.click(screen.getByTestId('dialog-confirm'));
      await waitFor(() => {
        expect(mockRemoveRepo).toHaveBeenCalledWith(5);
        expect(mockFetchAvailablePlugins).toHaveBeenCalled();
      });
    });

    it('shows "Removed" notification after delete', async () => {
      setupStore({ repos: [makeRepo({ id: 1 })] });
      render(<ManageReposModal {...defaultProps()} />);
      fireEvent.click(screen.getByTitle('Remove repo'));
      fireEvent.click(screen.getByTestId('dialog-confirm'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Removed', color: 'green' })
        );
      });
    });
  });

  // ── Add repository ─────────────────────────────────────────────────────────

  describe('add repository', () => {
    it('shows "Add Repository" button initially', () => {
      render(<ManageReposModal {...defaultProps()} />);
      expect(screen.getByText('Add Repository')).toBeInTheDocument();
    });

    it('shows the add form when "Add Repository" is clicked', () => {
      render(<ManageReposModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Add Repository'));
      expect(screen.getByTestId('repo-url-input')).toBeInTheDocument();
      expect(screen.getByText('Add Repo')).toBeInTheDocument();
    });

    it('hides the form and resets when Cancel is clicked', () => {
      render(<ManageReposModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Add Repository'));
      fireEvent.click(screen.getByText('Cancel'));
      expect(screen.queryByTestId('repo-url-input')).not.toBeInTheDocument();
      expect(screen.getByText('Add Repository')).toBeInTheDocument();
    });

    it('"Add Repo" button is disabled when URL is empty', () => {
      render(<ManageReposModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Add Repository'));
      expect(screen.getByText('Add Repo')).toBeDisabled();
    });

    it('"Add Repo" button is enabled when URL is entered', () => {
      render(<ManageReposModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Add Repository'));
      fireEvent.change(screen.getByTestId('repo-url-input'), {
        target: { value: 'https://example.com/manifest.json' },
      });
      expect(screen.getByText('Add Repo')).not.toBeDisabled();
    });

    it('calls addRepo and fetchAvailablePlugins when submitted', async () => {
      render(<ManageReposModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Add Repository'));
      fireEvent.change(screen.getByTestId('repo-url-input'), {
        target: { value: 'https://example.com/manifest.json' },
      });
      fireEvent.click(screen.getByText('Add Repo'));
      await waitFor(() => {
        expect(mockAddRepo).toHaveBeenCalledWith(
          expect.objectContaining({ url: 'https://example.com/manifest.json' })
        );
        expect(mockFetchAvailablePlugins).toHaveBeenCalled();
      });
    });

    it('shows "Added" notification after successful add', async () => {
      render(<ManageReposModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Add Repository'));
      fireEvent.change(screen.getByTestId('repo-url-input'), {
        target: { value: 'https://example.com/manifest.json' },
      });
      fireEvent.click(screen.getByText('Add Repo'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Added', color: 'green' })
        );
      });
    });

    it('closes the form after a successful add', async () => {
      render(<ManageReposModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Add Repository'));
      fireEvent.change(screen.getByTestId('repo-url-input'), {
        target: { value: 'https://example.com/manifest.json' },
      });
      fireEvent.click(screen.getByText('Add Repo'));
      await waitFor(() => {
        expect(screen.queryByTestId('repo-url-input')).not.toBeInTheDocument();
      });
    });

    it('triggers previewPluginRepo (debounced) when a valid URL is entered', async () => {
      vi.useFakeTimers();
      render(<ManageReposModal {...defaultProps()} />);
      await act(async () => {
        await vi.runAllTimersAsync();
      });

      fireEvent.click(screen.getByText('Add Repository'));
      fireEvent.change(screen.getByTestId('repo-url-input'), {
        target: { value: 'https://example.com/manifest.json' },
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(700);
      });
      expect(previewPluginRepo).toHaveBeenCalledWith(
        'https://example.com/manifest.json',
        ''
      );
      vi.useRealTimers();
    });
  });
});
