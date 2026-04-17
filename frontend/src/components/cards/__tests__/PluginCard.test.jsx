import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import PluginCard from '../PluginCard';
import * as notificationUtils from '../../../utils/notificationUtils';
import * as pluginCardUtils from '../../../utils/cards/PluginCardUtils';

// Mock the notification utils
vi.mock('../../../utils/notificationUtils', () => ({
  showNotification: vi.fn(),
}));

// Mock the plugin card utils
vi.mock('../../../utils/cards/PluginCardUtils', () => ({
  getConfirmationDetails: vi.fn(() => ({
    requireConfirm: false,
    confirmTitle: '',
    confirmMessage: '',
  })),
}));

vi.mock('../../Field', () => ({
  Field: ({ field, value, onChange }) => (
    <div data-testid={`field-${field.id}`}>
      <label>{field.label}</label>
      <input
        type={field.type || 'text'}
        value={value || ''}
        onChange={(e) => onChange(field.id, e.target.value)}
      />
    </div>
  ),
}));

vi.mock('@mantine/core', async () => {
  return {
    ActionIcon: ({ children, ...props }) => <button {...props}>{children}</button>,
    Anchor: ({ children, ...props }) => <a {...props}>{children}</a>,
    Box: ({ children, ...props }) => <div {...props}>{children}</div>,
    Avatar: ({ src, alt }) => <img src={src} alt={alt} />,
    Button: ({ children, ...props }) => <button {...props}>{children}</button>,
    Card: ({ children, ...props }) => <div {...props}>{children}</div>,
    Divider: () => <hr />,
    Group: ({ children, ...props }) => <div {...props}>{children}</div>,
    Stack: ({ children, ...props }) => <div {...props}>{children}</div>,
    Switch: ({ checked, onChange, disabled }) => (
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        disabled={disabled}
      />
    ),
    Text: ({ children, ...props }) => <span {...props}>{children}</span>,
    UnstyledButton: ({ children, ...props }) => <button {...props}>{children}</button>,
    Badge: ({ children, ...props }) => <span {...props}>{children}</span>,
    Loader: ({ size }) => <span data-testid="loader" data-size={size} />,
    Modal: ({ opened, onClose, title, children }) =>
      opened ? (
        <div data-testid="modal">
          <div data-testid="modal-title">{title}</div>
          <button onClick={onClose}>Close Modal</button>
          {children}
        </div>
      ) : null,
    Tabs: Object.assign(
      ({ children, value, onChange }) => (
        <div data-testid="tabs" data-value={value}>{children}</div>
      ),
      {
        List: ({ children }) => <div>{children}</div>,
        Tab: ({ children, value, leftSection }) => (
          <button data-value={value}>{leftSection}{children}</button>
        ),
        Panel: ({ children, value }) => (
          <div data-testid={`tab-panel-${value}`}>{children}</div>
        ),
      }
    ),
    Tooltip: ({ children, label }) => (
      <div title={label}>{children}</div>
    ),
  };
});

describe('PluginCard', () => {
  const mockPlugin = {
    key: 'test-plugin',
    name: 'Test Plugin',
    description: 'A test plugin',
    version: '1.0.0',
    enabled: true,
    ever_enabled: true,
    settings: { field1: 'value1' },
    fields: [
      {
        id: 'field1',
        label: 'Field 1',
        type: 'text',
      },
    ],
    actions: [
      {
        id: 'action1',
        label: 'Test Action',
        description: 'Test action description',
        button_label: 'Run Action',
      },
    ],
    author: 'Test Author',
    help_url: 'https://example.com/help',
    logo_url: 'https://example.com/logo.png',
  };

  const defaultProps = {
    plugin: mockPlugin,
    onSaveSettings: vi.fn(),
    onRunAction: vi.fn(),
    onToggleEnabled: vi.fn(),
    onRequireTrust: vi.fn(),
    onRequestDelete: vi.fn(),
    onRequestConfirm: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(pluginCardUtils.getConfirmationDetails).mockReturnValue({
      requireConfirm: false,
      confirmTitle: '',
      confirmMessage: '',
    });
  });

  describe('Rendering', () => {
    it('should render plugin card with basic information', () => {
      render(<PluginCard {...defaultProps} />);

      expect(screen.getByText('Test Plugin')).toBeInTheDocument();
      expect(screen.getByText('A test plugin')).toBeInTheDocument();
      expect(screen.getByText('v1.0.0')).toBeInTheDocument();
      expect(screen.getByText('Test Author')).toBeInTheDocument();
    });

    it('should render plugin logo when logo_url is provided', () => {
      render(<PluginCard {...defaultProps} />);

      const logo = screen.getByAltText('Test Plugin logo');
      expect(logo).toBeInTheDocument();
      expect(logo).toHaveAttribute('src', 'https://example.com/logo.png');
    });

    it('should render help link when help_url is provided', () => {
      render(<PluginCard {...defaultProps} />);

      const docsLink = screen.getByRole('link', { name: 'Docs' });
      expect(docsLink).toBeInTheDocument();
      expect(docsLink).toHaveAttribute('href', 'https://example.com/help');
      expect(docsLink).toHaveAttribute('target', '_blank');
    });

    it('should render switch as checked when plugin is enabled', () => {
      render(<PluginCard {...defaultProps} />);

      const switchElement = screen.getByRole('checkbox');
      expect(switchElement).toBeChecked();
    });

    it('should render switch as unchecked when plugin is disabled', () => {
      const disabledPlugin = { ...mockPlugin, enabled: false };
      render(<PluginCard {...defaultProps} plugin={disabledPlugin} />);

      const switchElement = screen.getByRole('checkbox');
      expect(switchElement).not.toBeChecked();
    });

    it('should show missing plugin warning when plugin is missing', () => {
      const missingPlugin = { ...mockPlugin, missing: true };
      render(<PluginCard {...defaultProps} plugin={missingPlugin} />);

      expect(
        screen.getByText('Missing plugin files. Re-import or delete this entry.')
      ).toBeInTheDocument();
    });

    it('should show legacy plugin warning', () => {
      const legacyPlugin = { ...mockPlugin, legacy: true };
      render(<PluginCard {...defaultProps} plugin={legacyPlugin} />);

      expect(
        screen.getByText('Please update or ask the developer to add plugin.json.')
      ).toBeInTheDocument();
    });
  });

  describe('Modal Behavior', () => {
    it('should open settings modal when Settings button is clicked', () => {
      render(<PluginCard {...defaultProps} />);

      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
      fireEvent.click(screen.getByText('Settings'));
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('should open actions modal when Actions button is clicked', () => {
      render(<PluginCard {...defaultProps} />);

      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
      fireEvent.click(screen.getByText('Actions'));
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('should not show Actions button when plugin is disabled', () => {
      const disabledPlugin = { ...mockPlugin, enabled: false };
      render(<PluginCard {...defaultProps} plugin={disabledPlugin} />);

      expect(screen.queryByText('Actions')).not.toBeInTheDocument();
    });
  });

  describe('Enable/Disable Toggle', () => {
    it('should call onToggleEnabled when switch is toggled', async () => {
      defaultProps.onToggleEnabled.mockResolvedValue({ success: true });
      render(<PluginCard {...defaultProps} />);

      const switchElement = screen.getByRole('checkbox');
      fireEvent.click(switchElement);

      await waitFor(() => {
        expect(defaultProps.onToggleEnabled).toHaveBeenCalledWith('test-plugin', false);
      });
    });

    it('should require trust for first-time enable', async () => {
      const firstTimePlugin = { ...mockPlugin, enabled: false, ever_enabled: false };
      defaultProps.onRequireTrust.mockResolvedValue(true);
      defaultProps.onToggleEnabled.mockResolvedValue({ success: true });

      render(<PluginCard {...defaultProps} plugin={firstTimePlugin} />);

      const switchElement = screen.getByRole('checkbox');
      fireEvent.click(switchElement);

      await waitFor(() => {
        expect(defaultProps.onRequireTrust).toHaveBeenCalledWith(firstTimePlugin);
        expect(defaultProps.onToggleEnabled).toHaveBeenCalledWith('test-plugin', true);
      });
    });

    it('should not enable if trust is denied', async () => {
      const firstTimePlugin = { ...mockPlugin, enabled: false, ever_enabled: false };
      defaultProps.onRequireTrust.mockResolvedValue(false);

      render(<PluginCard {...defaultProps} plugin={firstTimePlugin} />);

      const switchElement = screen.getByRole('checkbox');
      fireEvent.click(switchElement);

      await waitFor(() => {
        expect(defaultProps.onRequireTrust).toHaveBeenCalled();
        expect(defaultProps.onToggleEnabled).not.toHaveBeenCalled();
      });
    });

    it('should revert state if toggle fails', async () => {
      defaultProps.onToggleEnabled.mockResolvedValue({ success: false });
      render(<PluginCard {...defaultProps} />);

      const switchElement = screen.getByRole('checkbox');
      const initialState = switchElement.checked;

      fireEvent.click(switchElement);

      await waitFor(() => {
        expect(switchElement.checked).toBe(initialState);
      });
    });

    it('should be disabled when plugin is missing', () => {
      const missingPlugin = { ...mockPlugin, missing: true };
      render(<PluginCard {...defaultProps} plugin={missingPlugin} />);

      const switchElement = screen.getByRole('checkbox');
      expect(switchElement).toBeDisabled();
    });
  });

  describe('Settings Management', () => {
    it('should save settings when save button is clicked', async () => {
      defaultProps.onSaveSettings.mockResolvedValue(true);
      render(<PluginCard {...defaultProps} />);

      fireEvent.click(screen.getByText('Settings'));
      const saveButton = screen.getByText('Save');
      fireEvent.click(saveButton);

      await waitFor(() => {
        expect(defaultProps.onSaveSettings).toHaveBeenCalledWith(
          'test-plugin',
          { field1: 'value1' }
        );
        expect(notificationUtils.showNotification).toHaveBeenCalledWith({
          title: 'Saved',
          message: 'Test Plugin settings updated',
          color: 'green',
        });
      });
    });

    it('should show error notification when save fails', async () => {
      defaultProps.onSaveSettings.mockResolvedValue(false);
      render(<PluginCard {...defaultProps} />);

      fireEvent.click(screen.getByText('Settings'));
      const saveButton = screen.getByText('Save');
      fireEvent.click(saveButton);

      await waitFor(() => {
        expect(notificationUtils.showNotification).toHaveBeenCalledWith({
          title: 'Test Plugin error',
          message: 'Failed to update settings',
          color: 'red',
        });
      });
    });

    it('should handle save exception', async () => {
      const error = new Error('Network error');
      defaultProps.onSaveSettings.mockRejectedValue(error);
      render(<PluginCard {...defaultProps} />);

      fireEvent.click(screen.getByText('Settings'));
      const saveButton = screen.getByText('Save');
      fireEvent.click(saveButton);

      await waitFor(() => {
        expect(notificationUtils.showNotification).toHaveBeenCalledWith({
          title: 'Test Plugin error',
          message: 'Network error',
          color: 'red',
        });
      });
    });
  });

  describe('Actions', () => {
    it('should render action buttons', () => {
      render(<PluginCard {...defaultProps} />);

      fireEvent.click(screen.getByText('Actions'));
      expect(screen.getByText('Run Action')).toBeInTheDocument();
    });

    it('should run action when button is clicked', async () => {
      defaultProps.onSaveSettings.mockResolvedValue(true);
      defaultProps.onRunAction.mockResolvedValue({
        success: true,
        result: { message: 'Action completed' }
      });

      render(<PluginCard {...defaultProps} />);

      fireEvent.click(screen.getByText('Actions'));
      const actionButton = screen.getByText('Run Action');
      fireEvent.click(actionButton);

      await waitFor(() => {
        expect(defaultProps.onRunAction).toHaveBeenCalledWith('test-plugin', 'action1');
        expect(notificationUtils.showNotification).toHaveBeenCalledWith({
          title: 'Test Plugin',
          message: 'Action completed',
          color: 'green',
        });
      });
    });

    it('should show confirmation dialog when required', async () => {
      vi.mocked(pluginCardUtils.getConfirmationDetails).mockReturnValue({
        requireConfirm: true,
        confirmTitle: 'Confirm Action',
        confirmMessage: 'Are you sure?',
      });
      defaultProps.onRequestConfirm.mockResolvedValue(true);
      defaultProps.onSaveSettings.mockResolvedValue(true);
      defaultProps.onRunAction.mockResolvedValue({ success: true, result: {} });

      render(<PluginCard {...defaultProps} />);

      fireEvent.click(screen.getByText('Actions'));
      const actionButton = screen.getByText('Run Action');
      fireEvent.click(actionButton);

      await waitFor(() => {
        expect(defaultProps.onRequestConfirm).toHaveBeenCalledWith(
          'Confirm Action',
          'Are you sure?'
        );
        expect(defaultProps.onRunAction).toHaveBeenCalled();
      });
    });

    it('should not run action if confirmation is denied', async () => {
      vi.mocked(pluginCardUtils.getConfirmationDetails).mockReturnValue({
        requireConfirm: true,
        confirmTitle: 'Confirm Action',
        confirmMessage: 'Are you sure?',
      });
      defaultProps.onRequestConfirm.mockResolvedValue(false);

      render(<PluginCard {...defaultProps} />);

      fireEvent.click(screen.getByText('Actions'));
      const actionButton = screen.getByText('Run Action');
      fireEvent.click(actionButton);

      await waitFor(() => {
        expect(defaultProps.onRequestConfirm).toHaveBeenCalled();
        expect(defaultProps.onRunAction).not.toHaveBeenCalled();
      });
    });

    it('should show error notification when action fails', async () => {
      const errorProps = {
        ...defaultProps,
        onSaveSettings: vi.fn().mockResolvedValue(true),
        onRunAction: vi.fn().mockResolvedValue({
          success: false,
          error: 'Action failed',
        }),
      };

      render(<PluginCard {...errorProps} />);

      fireEvent.click(screen.getByText('Actions'));
      const actionButton = screen.getByText('Run Action');
      fireEvent.click(actionButton);

      await waitFor(() => {
        expect(notificationUtils.showNotification).toHaveBeenCalledWith({
          title: 'Test Plugin error',
          message: 'Action failed',
          color: 'red',
        });
      });
    });


    it('should render event triggers badges', () => {
      const pluginWithEvents = {
        ...mockPlugin,
        actions: [
          {
            id: 'action1',
            label: 'Test Action',
            events: ['SERIES_ADDED', 'EPISODE_DOWNLOADED'],
          },
        ],
      };

      render(<PluginCard {...defaultProps} plugin={pluginWithEvents} />);

      fireEvent.click(screen.getByText('Actions'));
      expect(screen.getByText('Event Triggers')).toBeInTheDocument();
    });
  });

  describe('Delete Plugin', () => {
    it('should call onRequestDelete when delete button is clicked', () => {
      render(<PluginCard {...defaultProps} />);

      const deleteButton = screen.getByText('Uninstall');
      fireEvent.click(deleteButton);

      expect(defaultProps.onRequestDelete).toHaveBeenCalledWith(mockPlugin);
    });
  });

  describe('Props Synchronization', () => {
    it('should sync enabled state with plugin prop changes', () => {
      const { rerender } = render(<PluginCard {...defaultProps} />);

      expect(screen.getByRole('checkbox')).toBeChecked();

      const disabledPlugin = { ...mockPlugin, enabled: false };
      rerender(<PluginCard {...defaultProps} plugin={disabledPlugin} />);

      expect(screen.getByRole('checkbox')).not.toBeChecked();
    });

    it('should sync settings when plugin key changes', () => {
      const { rerender } = render(<PluginCard {...defaultProps} />);

      const newPlugin = {
        ...mockPlugin,
        key: 'new-plugin',
        settings: { field1: 'new-value' },
      };
      rerender(<PluginCard {...defaultProps} plugin={newPlugin} />);

      // Settings button should still be present after key change
      expect(screen.getByText('Settings')).toBeInTheDocument();
    });
  });
});