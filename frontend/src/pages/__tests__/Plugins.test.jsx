import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import PluginsPage from '../Plugins';
import { showNotification, updateNotification } from '../../utils/notificationUtils.js';
import {
  deletePluginByKey,
  importPlugin,
  setPluginEnabled,
  updatePluginSettings,
} from '../../utils/pages/PluginsUtils';
import { usePluginStore } from '../../store/plugins';

vi.mock('../../store/plugins');

vi.mock('../../utils/pages/PluginsUtils', () => ({
  deletePluginByKey: vi.fn(),
  importPlugin: vi.fn(),
  setPluginEnabled: vi.fn(),
  updatePluginSettings: vi.fn(),
  runPluginAction: vi.fn(),
}));
vi.mock('../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
  updateNotification: vi.fn(),
}));

vi.mock('@mantine/core', async () => {
  return {
    AppShellMain: ({ children }) => <div>{children}</div>,
    Box: ({ children, style }) => <div style={style}>{children}</div>,
    Stack: ({ children, gap }) => <div data-gap={gap}>{children}</div>,
    Group: ({ children, justify, mb }) => (
      <div data-justify={justify} data-mb={mb}>
        {children}
      </div>
    ),
    Alert: ({ children, color, title }) => (
      <div data-testid="alert" data-color={color}>
        {title && <div>{title}</div>}
        {children}
      </div>
    ),
    Text: ({ children, size, fw, c }) => (
      <span data-size={size} data-fw={fw} data-color={c}>
        {children}
      </span>
    ),
    Button: ({ children, onClick, leftSection, variant, color, loading, disabled, fullWidth }) => (
      <button
        onClick={onClick}
        disabled={loading || disabled}
        data-variant={variant}
        data-color={color}
        data-full-width={fullWidth}
      >
        {leftSection}
        {children}
      </button>
    ),
    Loader: () => <div data-testid="loader">Loading...</div>,
    Switch: ({ checked, onChange, label, description }) => (
      <label>
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e)}
        />
        {label}
        {description && <span>{description}</span>}
      </label>
    ),
    Divider: ({ my }) => <hr data-my={my} />,
    ActionIcon: ({ children, onClick, color, variant, title }) => (
      <button onClick={onClick} data-color={color} data-variant={variant} title={title}>
        {children}
      </button>
    ),
    SimpleGrid: ({ children, cols }) => (
      <div data-cols={cols}>{children}</div>
    ),
    Modal: ({ opened, onClose, title, children, size, centered }) =>
      opened ? (
        <div data-testid="modal" data-size={size} data-centered={centered}>
          <div data-testid="modal-title">{title}</div>
          <button onClick={onClose}>Close Modal</button>
          {children}
        </div>
      ) : null,
    FileInput: ({ value, onChange, label, placeholder, accept }) => (
      <div>
        {label && <label>{label}</label>}
        <input
          type="file"
          onChange={(e) => onChange?.(e.target.files[0])}
          placeholder={placeholder}
          accept={accept}
          aria-label={label}
        />
      </div>
    ),
  };
});
vi.mock('@mantine/dropzone', () => ({
  Dropzone: ({ children, onDrop, accept, maxSize }) => (
    <div
      data-testid="dropzone"
      data-accept={accept}
      data-max-size={maxSize}
      onClick={() => {
        const file = new File(['content'], 'plugin.zip', { type: 'application/zip' });
        onDrop([file]);
      }}
    >
      <div>Drop files</div>
      {children}
    </div>
  ),
}));

vi.mock('../../components/cards/PluginCard.jsx', () => ({
  default: ({ plugin }) => (
    <div>
      <h2>{plugin.name}</h2>
      <p>{plugin.description}</p>
    </div>
  ),
}));

describe('PluginsPage', () => {
  const mockPlugins = [
    {
      key: 'plugin1',
      name: 'Test Plugin 1',
      description: 'Description 1',
      enabled: true,
      ever_enabled: true,
    },
    {
      key: 'plugin2',
      name: 'Test Plugin 2',
      description: 'Description 2',
      enabled: false,
      ever_enabled: false,
    },
  ];

  const mockPluginStoreState = {
    plugins: mockPlugins,
    loading: false,
    fetchPlugins: vi.fn(),
    updatePlugin: vi.fn(),
    removePlugin: vi.fn(),
    invalidatePlugins: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
    usePluginStore.mockImplementation((selector) => {
      return selector ? selector(mockPluginStoreState) : mockPluginStoreState;
    });
    usePluginStore.getState = vi.fn(() => mockPluginStoreState);
  });

  describe('Rendering', () => {
    it('renders the page with plugins list', async () => {
      render(<PluginsPage />);

      await waitFor(() => {
        expect(screen.getByText('Plugins')).toBeInTheDocument();
        expect(screen.getByText('Test Plugin 1')).toBeInTheDocument();
        expect(screen.getByText('Test Plugin 2')).toBeInTheDocument();
      });
    });

    it('renders import button', () => {
      render(<PluginsPage />);

      expect(screen.getByText('Import Plugin')).toBeInTheDocument();
    });

    it('renders reload button', () => {
      render(<PluginsPage />);

      const reloadButton = screen.getByTitle('Reload');
      expect(reloadButton).toBeInTheDocument();
    });

    it('shows loader when loading and no plugins', () => {
      const loadingState = { plugins: [], loading: true, fetchPlugins: vi.fn() };
      usePluginStore.mockImplementation((selector) => {
        return selector ? selector(loadingState) : loadingState;
      });
      usePluginStore.getState = vi.fn(() => loadingState);

      render(<PluginsPage />);

      expect(screen.getByTestId('loader')).toBeInTheDocument();
    });

    it('shows empty state when no plugins', () => {
      const emptyState = { plugins: [], loading: false, fetchPlugins: vi.fn() };
      usePluginStore.mockImplementation((selector) => {
        return selector ? selector(emptyState) : emptyState;
      });
      usePluginStore.getState = vi.fn(() => emptyState);

      render(<PluginsPage />);

      expect(screen.getByText(/No plugins found/)).toBeInTheDocument();
    });
  });

  describe('Import Plugin', () => {
    it('opens import modal when import button is clicked', () => {
      render(<PluginsPage />);

      fireEvent.click(screen.getByText('Import Plugin'));

      expect(screen.getByTestId('modal')).toBeInTheDocument();
      expect(screen.getByTestId('modal-title')).toHaveTextContent('Import Plugin');
    });

    it('shows dropzone and file input in import modal', () => {
      render(<PluginsPage />);

      fireEvent.click(screen.getByText('Import Plugin'));

      expect(screen.getByTestId('dropzone')).toBeInTheDocument();
      expect(screen.getByPlaceholderText('Select plugin .zip')).toBeInTheDocument();
    });

    it('closes import modal when close button is clicked', () => {
      render(<PluginsPage />);

      fireEvent.click(screen.getByText('Import Plugin'));
      expect(screen.getByTestId('modal')).toBeInTheDocument();

      fireEvent.click(screen.getByText('Close Modal'));

      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('handles file upload via dropzone', async () => {
      importPlugin.mockResolvedValue({
        success: true,
        plugin: { key: 'new-plugin', name: 'New Plugin', description: 'New Description' },
      });

      render(<PluginsPage />);

      fireEvent.click(screen.getByText('Import Plugin'));
      const dropzone = screen.getByTestId('dropzone');
      fireEvent.click(dropzone);

      await waitFor(() => {
        const uploadButton = screen.getAllByText('Upload').find(btn =>
          btn.tagName === 'BUTTON'
        );
        expect(uploadButton).not.toBeDisabled();
      });
    });

    it('uploads plugin successfully', async () => {
      const mockPlugin = {
        key: 'new-plugin',
        name: 'New Plugin',
        description: 'New Description',
        ever_enabled: false,
      };
      importPlugin.mockResolvedValue({
        success: true,
        plugin: mockPlugin,
      });

      render(<PluginsPage />);

      fireEvent.click(screen.getByText('Import Plugin'));

      const fileInput = screen.getByPlaceholderText('Select plugin .zip');
      const file = new File(['content'], 'plugin.zip', { type: 'application/zip' });
      fireEvent.change(fileInput, { target: { files: [file] } });

      const uploadButton = screen.getAllByText('Upload').find(btn =>
        btn.tagName === 'BUTTON'
      );
      fireEvent.click(uploadButton);

      await waitFor(() => {
        expect(importPlugin).toHaveBeenCalledWith(file);
        expect(showNotification).toHaveBeenCalled();
        expect(updateNotification).toHaveBeenCalled();
      });
    });

    it('handles upload failure', async () => {
      importPlugin.mockResolvedValue({
        success: false,
        error: 'Upload failed',
      });

      render(<PluginsPage />);

      fireEvent.click(screen.getByText('Import Plugin'));

      const fileInput = screen.getByPlaceholderText('Select plugin .zip');
      const file = new File(['content'], 'plugin.zip', { type: 'application/zip' });
      fireEvent.change(fileInput, { target: { files: [file] } });

      const uploadButton = screen.getAllByText('Upload').find(btn =>
        btn.tagName === 'BUTTON'
      );
      fireEvent.click(uploadButton);

      await waitFor(() => {
        expect(updateNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            color: 'red',
            title: 'Import failed',
          })
        );
      });
    });

    it('shows enable switch after successful import', async () => {
      const mockPlugin = {
        key: 'new-plugin',
        name: 'New Plugin',
        description: 'New Description',
        ever_enabled: false,
      };
      importPlugin.mockResolvedValue({
        success: true,
        plugin: mockPlugin,
      });

      render(<PluginsPage />);

      fireEvent.click(screen.getByText('Import Plugin'));

      const fileInput = screen.getByPlaceholderText('Select plugin .zip');
      const file = new File(['content'], 'plugin.zip', { type: 'application/zip' });
      fireEvent.change(fileInput, { target: { files: [file] } });

      const uploadButton = screen.getAllByText('Upload').find(btn =>
        btn.tagName === 'BUTTON'
      );
      fireEvent.click(uploadButton);

      await waitFor(() => {
        expect(screen.getByText('New Plugin')).toBeInTheDocument();
        expect(screen.getByText('Enable now')).toBeInTheDocument();
      });
    });

    it('enables plugin after import when switch is toggled', async () => {
      const mockPlugin = {
        key: 'new-plugin',
        name: 'New Plugin',
        description: 'New Description',
        ever_enabled: true,
      };
      importPlugin.mockResolvedValue({
        success: true,
        plugin: mockPlugin,
      });
      setPluginEnabled.mockResolvedValue({ success: true });

      render(<PluginsPage />);

      fireEvent.click(screen.getByText('Import Plugin'));

      const fileInput = screen.getByPlaceholderText('Select plugin .zip');
      const file = new File(['content'], 'plugin.zip', { type: 'application/zip' });
      fireEvent.change(fileInput, { target: { files: [file] } });

      const uploadButton = screen.getAllByText('Upload').find(btn =>
        btn.tagName === 'BUTTON'
      );
      fireEvent.click(uploadButton);

      await waitFor(() => {
        expect(screen.getByText('Enable now')).toBeInTheDocument();
      });

      const enableSwitch = screen.getByRole('checkbox');
      fireEvent.click(enableSwitch);

      const enableButton = screen.getAllByText('Enable').find(btn =>
        btn.tagName === 'BUTTON'
      );
      fireEvent.click(enableButton);

      await waitFor(() => {
        expect(setPluginEnabled).toHaveBeenCalledWith('new-plugin', true);
      });
    });
  });

  describe('Trust Warning', () => {
    it('shows trust warning for untrusted plugins', async () => {
      const mockPlugin = {
        key: 'new-plugin',
        name: 'New Plugin',
        description: 'New Description',
        ever_enabled: false,
      };
      importPlugin.mockResolvedValue({
        success: true,
        plugin: mockPlugin,
      });
      setPluginEnabled.mockResolvedValue({ success: true, ever_enabled: true });

      render(<PluginsPage />);

      fireEvent.click(screen.getByText('Import Plugin'));

      const fileInput = screen.getByPlaceholderText('Select plugin .zip');
      const file = new File(['content'], 'plugin.zip', { type: 'application/zip' });
      fireEvent.change(fileInput, { target: { files: [file] } });

      const uploadButton = screen.getAllByText('Upload').find(btn =>
        btn.tagName === 'BUTTON'
      );
      fireEvent.click(uploadButton);

      await waitFor(() => {
        expect(screen.getByText('Enable now')).toBeInTheDocument();
      });

      const enableSwitch = screen.getByRole('checkbox');
      fireEvent.click(enableSwitch);

      const enableButton = screen.getAllByText('Enable').find(btn =>
        btn.tagName === 'BUTTON'
      );
      fireEvent.click(enableButton);

      await waitFor(() => {
        expect(screen.getByText('Enable third-party plugins?')).toBeInTheDocument();
      });
    });

    it('enables plugin when trust is confirmed', async () => {
      const mockPlugin = {
        key: 'new-plugin',
        name: 'New Plugin',
        description: 'New Description',
        ever_enabled: false,
      };
      importPlugin.mockResolvedValue({
        success: true,
        plugin: mockPlugin,
      });
      setPluginEnabled.mockResolvedValue({ success: true, ever_enabled: true });

      render(<PluginsPage />);

      fireEvent.click(screen.getByText('Import Plugin'));

      const fileInput = screen.getByPlaceholderText('Select plugin .zip');
      const file = new File(['content'], 'plugin.zip', { type: 'application/zip' });
      fireEvent.change(fileInput, { target: { files: [file] } });

      const uploadButton = screen.getAllByText('Upload').find(btn =>
        btn.tagName === 'BUTTON'
      );
      fireEvent.click(uploadButton);

      await waitFor(() => {
        expect(screen.getByText('Enable now')).toBeInTheDocument();
      });

      const enableSwitch = screen.getByRole('checkbox');
      fireEvent.click(enableSwitch);

      const enableButton = screen.getAllByText('Enable').find(btn =>
        btn.tagName === 'BUTTON'
      );
      fireEvent.click(enableButton);

      await waitFor(() => {
        expect(screen.getByText('I understand, enable')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('I understand, enable'));

      await waitFor(() => {
        expect(setPluginEnabled).toHaveBeenCalledWith('new-plugin', true);
      });
    });

    it('cancels enable when trust is denied', async () => {
      const mockPlugin = {
        key: 'new-plugin',
        name: 'New Plugin',
        description: 'New Description',
        ever_enabled: false,
      };
      importPlugin.mockResolvedValue({
        success: true,
        plugin: mockPlugin,
      });

      render(<PluginsPage />);

      fireEvent.click(screen.getByText('Import Plugin'));

      const fileInput = screen.getByPlaceholderText('Select plugin .zip');
      const file = new File(['content'], 'plugin.zip', { type: 'application/zip' });
      fireEvent.change(fileInput, { target: { files: [file] } });

      const uploadButton = screen.getAllByText('Upload').find(btn =>
        btn.tagName === 'BUTTON'
      );
      fireEvent.click(uploadButton);

      await waitFor(() => {
        expect(screen.getByText('Enable now')).toBeInTheDocument();
      });

      const enableSwitch = screen.getByRole('checkbox');
      fireEvent.click(enableSwitch);

      const enableButton = screen.getAllByText('Enable').find(btn =>
        btn.tagName === 'BUTTON'
      );
      fireEvent.click(enableButton);

      await waitFor(() => {
        const cancelButtons = screen.getAllByText('Cancel');
        expect(cancelButtons.length).toBeGreaterThan(0);
      });

      const cancelButtons = screen.getAllByText('Cancel');
      fireEvent.click(cancelButtons[cancelButtons.length - 1]);

      await waitFor(() => {
        expect(setPluginEnabled).not.toHaveBeenCalled();
      });
    });
  });

  describe('Reload', () => {
    it('reloads plugins when reload button is clicked', async () => {
      const invalidatePlugins = vi.fn();
      usePluginStore.getState = vi.fn(() => ({
        ...mockPluginStoreState,
        invalidatePlugins,
      }));

      render(<PluginsPage />);

      const reloadButton = screen.getByTitle('Reload');
      fireEvent.click(reloadButton);

      await waitFor(() => {
        expect(invalidatePlugins).toHaveBeenCalled();
      });
    });
  });
});
