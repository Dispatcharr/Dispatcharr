import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { MemoryRouter } from 'react-router-dom';
import PluginCard from '../PluginCard';
import useAuthStore from '../../../store/auth.jsx';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock('../../../store/auth.jsx');

vi.mock('@mantine/core', async () => {
  return {
    ActionIcon: ({ children, ...props }) => <a {...props}>{children}</a>,
    Avatar: ({ src, alt, onClick, children }) => (
      <img src={src} alt={alt} onClick={onClick} data-fallback={typeof children === 'string' ? children : undefined} />
    ),
    Anchor: ({ children, ...props }) => <a {...props}>{children}</a>,
    Box: ({ children, ...props }) => <div {...props}>{children}</div>,
    Button: ({ children, ...props }) => <button {...props}>{children}</button>,
    Card: ({ children, ...props }) => <div {...props}>{children}</div>,
    Group: ({ children, ...props }) => <div {...props}>{children}</div>,
    Stack: ({ children, ...props }) => <div {...props}>{children}</div>,
    Menu: Object.assign(({ children }) => <div>{children}</div>, {
      Target: ({ children }) => children,
      Dropdown: ({ children }) => <div>{children}</div>,
      Item: ({ children, leftSection, ...props }) => <button {...props}>{leftSection}{children}</button>,
    }),
    Text: ({ children, ...props }) => <span {...props}>{children}</span>,
    Badge: ({ children, ...props }) => <span {...props}>{children}</span>,
    Tooltip: ({ children, label }) => <div title={label}>{children}</div>,
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
    capabilities: [{ id: 'background_tasks', label: 'Run background tasks' }],
    acknowledged_capabilities: ['background_tasks'],
    author: 'Test Author',
    help_url: 'https://example.com/help',
    logo_url: 'https://example.com/logo.png',
  };

  const defaultProps = {
    plugin: mockPlugin,
    onToggleEnabled: vi.fn(),
    onRequireTrust: vi.fn(),
    onRequestDelete: vi.fn(),
  };

  const renderCard = (props = {}) =>
    render(
      <MemoryRouter>
        <PluginCard {...defaultProps} {...props} />
      </MemoryRouter>
    );

  let mockTogglePinnedPlugin;
  let pinnedKeys;

  beforeEach(() => {
    vi.clearAllMocks();
    pinnedKeys = [];
    mockTogglePinnedPlugin = vi.fn();
    useAuthStore.mockImplementation((selector) =>
      selector({
        user: { custom_properties: { pinnedPlugins: pinnedKeys } },
        togglePinnedPlugin: mockTogglePinnedPlugin,
      })
    );
  });

  it('renders plugin card with basic information', () => {
    renderCard();

    expect(screen.getByText('Test Plugin')).toBeInTheDocument();
    expect(screen.getByText('A test plugin')).toBeInTheDocument();
    expect(screen.getByText('v1.0.0')).toBeInTheDocument();
    expect(screen.getByText('Test Author')).toBeInTheDocument();
  });

  it('keeps the byline beside the logo without reserving switch space', () => {
    renderCard({ plugin: { ...mockPlugin, is_managed: true, source_repo_name: 'Example repository' } });
    const title = screen.getByText('Test Plugin');
    const author = screen.getByText('Test Author');
    const titleRow = title.parentElement.parentElement;
    expect(titleRow).toHaveStyle({ paddingRight: '24px' });
    expect(titleRow.parentElement).toContainElement(author);
    expect(author.closest('[style*="padding-right"]')).toBeNull();
    expect(screen.getByText('Example repository')).toBeInTheDocument();
  });

  it('renders plugin logo when logo_url is provided', () => {
    renderCard();

    const logo = screen.getByAltText('Test Plugin logo');
    expect(logo).toBeInTheDocument();
    expect(logo).toHaveAttribute('src', 'https://example.com/logo.png');
  });

  it('does not render a docs link on the card (moved to the detail page)', () => {
    renderCard();

    expect(screen.queryByRole('link', { name: 'Documentation' })).not.toBeInTheDocument();
  });

  it('shows the disable action for an enabled plugin', () => {
    renderCard();
    expect(screen.getByRole('button', { name: 'Disable plugin' })).toBeInTheDocument();
    expect(screen.queryByText('Disabled')).not.toBeInTheDocument();
  });

  it('shows a plain status and enable action for a disabled plugin', () => {
    renderCard({ plugin: { ...mockPlugin, enabled: false } });
    expect(screen.getByText('Disabled').tagName).toBe('SPAN');
    expect(screen.getByRole('button', { name: 'Enable plugin' })).toBeInTheDocument();
  });

  it('shows missing plugin warning when plugin is missing', () => {
    renderCard({ plugin: { ...mockPlugin, missing: true } });
    expect(
      screen.getByText('Missing plugin files. Re-import or delete this entry.')
    ).toBeInTheDocument();
  });

  it('shows legacy plugin warning', () => {
    renderCard({ plugin: { ...mockPlugin, legacy: true } });
    expect(
      screen.getByText('Please update or ask the developer to add plugin.json.')
    ).toBeInTheDocument();
  });

  it('navigates to the plugin detail page when Open is clicked', () => {
    renderCard();
    fireEvent.click(screen.getByText('Open'));
    expect(mockNavigate).toHaveBeenCalledWith('/plugins/test-plugin');
  });

  it('navigates to the plugin detail page when the name is clicked', () => {
    renderCard();
    fireEvent.click(screen.getByText('Test Plugin'));
    expect(mockNavigate).toHaveBeenCalledWith('/plugins/test-plugin');
  });

  it('calls onToggleEnabled when switch is toggled', async () => {
    defaultProps.onToggleEnabled.mockResolvedValue({ success: true });
    renderCard();

    fireEvent.click(screen.getByRole('button', { name: mockPlugin.enabled ? 'Disable plugin' : 'Enable plugin' }));

    await waitFor(() => {
      expect(defaultProps.onToggleEnabled).toHaveBeenCalledWith('test-plugin', false, []);
    });
  });

  it('requires trust for first-time enable', async () => {
    const firstTimePlugin = {
      ...mockPlugin,
      enabled: false,
      ever_enabled: false,
      acknowledged_capabilities: [],
    };
    defaultProps.onRequireTrust.mockResolvedValue(true);
    defaultProps.onToggleEnabled.mockResolvedValue({ success: true });

    renderCard({ plugin: firstTimePlugin });
    fireEvent.click(screen.getByRole('button', { name: 'Enable plugin' }));

    await waitFor(() => {
      expect(defaultProps.onRequireTrust).toHaveBeenCalledWith(firstTimePlugin);
      expect(defaultProps.onToggleEnabled).toHaveBeenCalledWith(
        'test-plugin',
        true,
        ['background_tasks']
      );
    });
  });

  it('does not enable if trust is denied', async () => {
    const firstTimePlugin = {
      ...mockPlugin,
      enabled: false,
      ever_enabled: false,
      acknowledged_capabilities: [],
    };
    defaultProps.onRequireTrust.mockResolvedValue(false);

    renderCard({ plugin: firstTimePlugin });
    fireEvent.click(screen.getByRole('button', { name: 'Enable plugin' }));

    await waitFor(() => {
      expect(defaultProps.onRequireTrust).toHaveBeenCalled();
      expect(defaultProps.onToggleEnabled).not.toHaveBeenCalled();
    });
  });

  it('requires trust again when an already-enabled plugin adds a capability', async () => {
    const updatedPlugin = {
      ...mockPlugin,
      enabled: false,
      ever_enabled: true,
      capabilities: [
        { id: 'background_tasks', label: 'Run background tasks' },
        { id: 'persistent_service', label: 'Run a persistent background service' },
      ],
      acknowledged_capabilities: ['background_tasks'],
    };
    defaultProps.onRequireTrust.mockResolvedValue(true);
    defaultProps.onToggleEnabled.mockResolvedValue({ success: true });

    renderCard({ plugin: updatedPlugin });
    fireEvent.click(screen.getByRole('button', { name: 'Enable plugin' }));

    await waitFor(() => {
      expect(defaultProps.onRequireTrust).toHaveBeenCalledWith(updatedPlugin);
      expect(defaultProps.onToggleEnabled).toHaveBeenCalledWith(
        'test-plugin',
        true,
        ['background_tasks', 'persistent_service']
      );
    });
  });

  it('reverts state if toggle fails', async () => {
    defaultProps.onToggleEnabled.mockResolvedValue({ success: false });
    renderCard();

    fireEvent.click(screen.getByRole('button', { name: 'Disable plugin' }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Disable plugin' })).toBeInTheDocument();
    });
  });

  it('is disabled when plugin is missing', () => {
    renderCard({ plugin: { ...mockPlugin, missing: true } });
    expect(screen.getByRole('button', { name: 'Enable plugin' })).toBeDisabled();
  });

  it('calls onRequestDelete when Uninstall is clicked', () => {
    renderCard();
    fireEvent.click(screen.getByText('Uninstall'));
    expect(defaultProps.onRequestDelete).toHaveBeenCalledWith(mockPlugin);
  });

  it('shows the pin toggle as "Pin to sidebar" when not pinned', () => {
    renderCard();
    expect(screen.getByRole('button', { name: 'Pin to sidebar' })).toBeInTheDocument();
  });

  it('shows the pin toggle as "Unpin from sidebar" when already pinned', () => {
    pinnedKeys = ['test-plugin'];
    renderCard();
    expect(screen.getByRole('button', { name: 'Unpin from sidebar' })).toBeInTheDocument();
  });

  it('toggles pinning when the pin button is clicked', () => {
    renderCard();
    fireEvent.click(screen.getByRole('button', { name: 'Pin to sidebar' }));
    expect(mockTogglePinnedPlugin).toHaveBeenCalledWith('test-plugin');
  });

  it('syncs enabled state with plugin prop changes', () => {
    const { rerender } = render(
      <MemoryRouter>
        <PluginCard {...defaultProps} />
      </MemoryRouter>
    );
    expect(screen.getByRole('button', { name: 'Disable plugin' })).toBeInTheDocument();

    rerender(
      <MemoryRouter>
        <PluginCard {...defaultProps} plugin={{ ...mockPlugin, enabled: false }} />
      </MemoryRouter>
    );
    expect(screen.getByRole('button', { name: 'Enable plugin' })).toBeInTheDocument();
  });
});
