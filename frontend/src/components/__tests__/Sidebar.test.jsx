import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import Sidebar from '../Sidebar';
import useChannelsStore from '../../store/channels';
import useSettingsStore from '../../store/settings';
import useAuthStore from '../../store/auth';
import { copyToClipboard } from '../../utils';
import { USER_LEVELS } from '../../constants';

// Mock stores
vi.mock('../../store/channels');
vi.mock('../../store/settings');
vi.mock('../../store/auth');
vi.mock('../../utils', () => ({
  copyToClipboard: vi.fn(),
}));

vi.mock('../NotificationCenter', () => ({
  default: () => (
    <div data-testid="notification-center">Notification Center</div>
  ),
}));

// Mock lucide-react icons
vi.mock('lucide-react', () => ({
  ListOrdered: ({ onClick }) => (
    <div data-testid="list-ordered-icon" onClick={onClick} />
  ),
  Play: ({ onClick }) => <div data-testid="play-icon" onClick={onClick} />,
  Database: ({ onClick }) => (
    <div data-testid="database-icon" onClick={onClick} />
  ),
  LayoutGrid: ({ onClick }) => (
    <div data-testid="layout-grid-icon" onClick={onClick} />
  ),
  Settings: ({ onClick }) => (
    <div data-testid="settings-icon" onClick={onClick} />
  ),
  Copy: ({ onClick }) => <div data-testid="copy-icon" onClick={onClick} />,
  ChartLine: ({ onClick }) => (
    <div data-testid="chart-line-icon" onClick={onClick} />
  ),
  Video: ({ onClick }) => <div data-testid="video-icon" onClick={onClick} />,
  PlugZap: ({ onClick }) => (
    <div data-testid="plug-zap-icon" onClick={onClick} />
  ),
  LogOut: ({ onClick }) => <div data-testid="logout-icon" onClick={onClick} />,
  User: ({ onClick }) => <div data-testid="user-icon" onClick={onClick} />,
  FileImage: ({ onClick }) => (
    <div data-testid="file-image-icon" onClick={onClick} />
  ),
  Webhook: () => <div data-testid="webhook-icon" />,
  Logs: () => <div data-testid="logs-icon" />,
  ChevronDown: () => <div data-testid="chevron-down-icon" />,
  ChevronRight: () => <div data-testid="chevron-right-icon" />,
  MonitorCog: () => <div data-testid="monitor-cog-icon" />,
  Blocks: () => <div data-testid="blocks-icon" />,
  Heart: () => <div data-testid="heart-icon" />,
}));

// Mock UserForm component
vi.mock('../forms/User', () => ({
  default: ({ isOpen, onClose, user }) =>
    isOpen ? (
      <div data-testid="user-form">
        User Form for {user?.username}
        <button onClick={onClose}>Close</button>
      </div>
    ) : null,
}));

vi.mock('@mantine/core', async () => {
  return {
    Avatar: ({ children }) => <div>{children}</div>,
    Group: ({ children, onClick, ...props }) => (
      <div onClick={onClick} {...props}>
        {children}
      </div>
    ),
    Stack: ({ children }) => <div>{children}</div>,
    Box: ({ children }) => <div>{children}</div>,
    Text: ({ children }) => <div>{children}</div>,
    UnstyledButton: ({ children, onClick, component, to, className }) => {
      const Component = component || 'button';
      return (
        <Component onClick={onClick} to={to} className={className}>
          {children}
        </Component>
      );
    },
    TextInput: ({ value, onChange, leftSection, rightSection, label }) => (
      <div>
        {label && <label>{label}</label>}
        {leftSection}
        <input value={value} onChange={onChange} />
        {rightSection}
      </div>
    ),
    ActionIcon: ({ children, onClick, ...props }) => (
      <button onClick={onClick} {...props}>
        {children}
      </button>
    ),
    AppShellNavbar: ({ children, style, width, ...props }) => (
      <nav
        style={{
          ...style,
          width:
            typeof width?.base === 'number' ? `${width.base}px` : width?.base,
        }}
        {...props}
      >
        {children}
      </nav>
    ),
    ScrollArea: ({ children }) => <div>{children}</div>,
    Tooltip: ({ children }) => <>{children}</>,
  };
});

const mockChannels = ['channel-1', 'channel-2', 'channel-3'];

const mockEnvironment = {
  public_ip: '192.168.1.1',
  country_code: 'US',
  country_name: 'United States',
};

const mockVersion = {
  version: '1.2.3',
  timestamp: '20240115',
};

const mockAdminUser = {
  id: 1,
  username: 'admin',
  first_name: 'Admin',
  user_level: USER_LEVELS.ADMIN,
};

const mockRegularUser = {
  id: 2,
  username: 'user',
  first_name: 'John',
  user_level: USER_LEVELS.USER,
};

const renderSidebar = (props = {}) => {
  const defaultProps = {
    collapsed: false,
    toggleDrawer: vi.fn(),
    drawerWidth: 250,
    miniDrawerWidth: 80,
  };

  return render(
    <BrowserRouter>
      <Sidebar {...defaultProps} {...props} />
    </BrowserRouter>
  );
};

describe('Sidebar', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    useChannelsStore.mockReturnValue(mockChannels);
    useSettingsStore.mockImplementation((selector) => {
      const state = {
        environment: mockEnvironment,
        version: mockVersion,
      };
      return selector(state);
    });
    useAuthStore.mockImplementation((selector) => {
      const state = {
        isAuthenticated: true,
        user: mockAdminUser,
        logout: vi.fn(),
        getNavOrder: () => null,
        getHiddenNav: () => [],
      };
      return selector(state);
    });
  });

  describe('Brand Section', () => {
    it('should render logo and brand name when expanded', () => {
      const { container } = renderSidebar();

      expect(screen.getByText('Dispatcharr')).toBeInTheDocument();
      const logo = container.querySelectorAll(
        'img[src="/src/images/logo.png"]'
      );
      expect(logo).toHaveLength(1);
    });

    it('should hide brand name when collapsed', () => {
      renderSidebar({ collapsed: true });
      expect(screen.queryByText('Dispatcharr')).not.toBeInTheDocument();
    });

    it('should toggle drawer when brand is clicked', () => {
      const toggleDrawer = vi.fn();
      renderSidebar({ toggleDrawer });

      const brand = screen.getByText('Dispatcharr').closest('div');
      fireEvent.click(brand);

      expect(toggleDrawer).toHaveBeenCalledTimes(1);
    });
  });

  describe('Navigation Links - Admin User', () => {
    it('should render all admin navigation items', async () => {
      renderSidebar();

      expect(screen.getByText('Channels')).toBeInTheDocument();
      expect(screen.getByText('VODs')).toBeInTheDocument();
      expect(screen.getByText('M3U & EPG Manager')).toBeInTheDocument();
      expect(screen.getByText('TV Guide')).toBeInTheDocument();
      expect(screen.getByText('DVR')).toBeInTheDocument();
      expect(screen.getByText('Stats')).toBeInTheDocument();
      expect(screen.getByText('Plugins')).toBeInTheDocument();

      // Expand System group to access Users
      const systemButton = screen.getByText('System');
      fireEvent.click(systemButton);

      await waitFor(() => {
        expect(screen.getByText('Users')).toBeInTheDocument();
        expect(screen.getByText('Logo Manager')).toBeInTheDocument();
        expect(screen.getByText('Settings')).toBeInTheDocument();
      });
    });

    it('should display channel count badge', () => {
      renderSidebar();
      expect(screen.getByText('(3)')).toBeInTheDocument();
    });

    it('should hide labels and badges when collapsed', () => {
      renderSidebar({ collapsed: true });

      expect(screen.queryByText('Channels')).not.toBeInTheDocument();
      expect(screen.queryByText('(3)')).not.toBeInTheDocument();
    });
  });

  describe('Navigation Links - Regular User', () => {
    beforeEach(() => {
      useAuthStore.mockImplementation((selector) => {
        const state = {
          isAuthenticated: true,
          user: mockRegularUser,
          logout: vi.fn(),
          getNavOrder: () => null,
          getHiddenNav: () => [],
        };
        return selector(state);
      });
    });

    it('should render limited navigation items for regular user', () => {
      renderSidebar();

      expect(screen.getByText('Channels')).toBeInTheDocument();
      expect(screen.getByText('TV Guide')).toBeInTheDocument();
      expect(screen.getByText('Settings')).toBeInTheDocument();

      expect(screen.queryByText('VODs')).not.toBeInTheDocument();
      expect(screen.queryByText('M3U & EPG Manager')).not.toBeInTheDocument();
      expect(screen.queryByText('DVR')).not.toBeInTheDocument();
      expect(screen.queryByText('Stats')).not.toBeInTheDocument();
      expect(screen.queryByText('Plugins')).not.toBeInTheDocument();
      expect(screen.queryByText('Users')).not.toBeInTheDocument();
      expect(screen.queryByText('Logo Manager')).not.toBeInTheDocument();
    });
  });

  describe('Profile Section - Authenticated', () => {
    it('should render public IP with country flag', () => {
      renderSidebar();

      const ipInput = screen.getByDisplayValue('192.168.1.1');
      expect(ipInput).toBeInTheDocument();

      const flag = screen.getByAltText('United States');
      expect(flag).toHaveAttribute('src', 'https://flagcdn.com/16x12/us.png');
    });

    it('should copy public IP to clipboard when copy button is clicked', async () => {
      copyToClipboard.mockResolvedValue();
      renderSidebar();

      const copyButton = screen.getByTestId('copy-icon').closest('button');
      fireEvent.click(copyButton);

      await waitFor(() => {
        expect(copyToClipboard).toHaveBeenCalledWith('192.168.1.1', {
          successTitle: 'Success',
          successMessage: 'Public IP copied to clipboard',
        });
      });
    });

    it('should render user avatar and name', () => {
      renderSidebar();

      expect(screen.getByText('Admin')).toBeInTheDocument();
    });

    it('should fallback to username if first_name is not set', () => {
      useAuthStore.mockImplementation((selector) => {
        const state = {
          isAuthenticated: true,
          user: { ...mockAdminUser, first_name: null },
          logout: vi.fn(),
          getNavOrder: () => null,
          getHiddenNav: () => [],
        };
        return selector(state);
      });

      renderSidebar();
      expect(screen.getByText('admin')).toBeInTheDocument();
    });

    it('should open user form when username is clicked', () => {
      renderSidebar();

      const nameButton = screen.getByText('Admin');
      fireEvent.click(nameButton);

      expect(screen.getByTestId('user-form')).toBeInTheDocument();
      expect(screen.getByText('User Form for admin')).toBeInTheDocument();
    });

    it('should close user form when close button is clicked', () => {
      renderSidebar();

      const nameButton = screen.getByText('Admin');
      fireEvent.click(nameButton);

      expect(screen.getByTestId('user-form')).toBeInTheDocument();

      const closeButton = screen.getByText('Close');
      fireEvent.click(closeButton);

      expect(screen.queryByTestId('user-form')).not.toBeInTheDocument();
    });

    it('should logout when logout button is clicked', () => {
      const mockLogout = vi.fn();
      useAuthStore.mockImplementation((selector) => {
        const state = {
          isAuthenticated: true,
          user: mockAdminUser,
          logout: mockLogout,
          getNavOrder: () => null,
          getHiddenNav: () => [],
        };
        return selector(state);
      });

      renderSidebar();

      const logoutIcon = screen.getByTestId('logout-icon');
      fireEvent.click(logoutIcon);

      expect(mockLogout).toHaveBeenCalledTimes(1);
    });

    it('should hide profile details when collapsed', () => {
      renderSidebar({ collapsed: true });

      expect(screen.queryByDisplayValue('192.168.1.1')).not.toBeInTheDocument();
      expect(screen.queryByText('Admin')).not.toBeInTheDocument();
    });
  });

  describe('Profile Section - Not Authenticated', () => {
    beforeEach(() => {
      useAuthStore.mockImplementation((selector) => {
        const state = {
          isAuthenticated: false,
          user: null,
          logout: vi.fn(),
          getNavOrder: () => null,
          getHiddenNav: () => [],
        };
        return selector(state);
      });
    });

    it('should not render profile section when not authenticated', () => {
      renderSidebar();

      expect(screen.queryByDisplayValue('192.168.1.1')).not.toBeInTheDocument();
      expect(screen.queryByText('Admin')).not.toBeInTheDocument();
    });
  });

  describe('Version Display', () => {
    it('should render version when expanded', () => {
      renderSidebar();
      expect(screen.getByText('v1.2.3-20240115')).toBeInTheDocument();
    });

    it('should render version without timestamp if not available', () => {
      useSettingsStore.mockImplementation((selector) => {
        const state = {
          environment: mockEnvironment,
          version: { version: '1.2.3' },
        };
        return selector(state);
      });

      renderSidebar();
      expect(screen.getByText('v1.2.3')).toBeInTheDocument();
    });

    it('should render default version if not loaded', () => {
      useSettingsStore.mockImplementation((selector) => {
        const state = {
          environment: mockEnvironment,
          version: null,
        };
        return selector(state);
      });

      renderSidebar();
      expect(screen.getByText('v0.0.0')).toBeInTheDocument();
    });

    it('should hide version when collapsed', () => {
      renderSidebar({ collapsed: true });
      expect(screen.queryByText(/v1.2.3-20240115/)).not.toBeInTheDocument();
    });
  });

  describe('Collapsed State', () => {
    it('should apply collapsed class to navigation links', () => {
      renderSidebar({ collapsed: true });

      const links = screen.getAllByRole('link');
      links.forEach((link) => {
        expect(link).toHaveClass('navlink-collapsed');
      });
    });

    it('should adjust width based on collapsed state', () => {
      const { rerender } = renderSidebar({
        collapsed: false,
        drawerWidth: 250,
      });
      const navbar = screen.getByRole('navigation');

      expect(navbar).toHaveStyle({ width: '250px' });

      rerender(
        <BrowserRouter>
          <Sidebar
            collapsed={true}
            drawerWidth={250}
            miniDrawerWidth={80}
            toggleDrawer={vi.fn()}
          />
        </BrowserRouter>
      );

      expect(navbar).toHaveStyle({ width: '80px' });
    });
  });

  describe('Environment Edge Cases', () => {
    it('should handle missing country code gracefully', () => {
      useSettingsStore.mockImplementation((selector) => {
        const state = {
          environment: { public_ip: '192.168.1.1' },
          version: mockVersion,
        };
        return selector(state);
      });

      renderSidebar();
      expect(screen.getByDisplayValue('192.168.1.1')).toBeInTheDocument();
      expect(
        screen.queryByRole('img', { name: /flag/i })
      ).not.toBeInTheDocument();
    });

    it('should use country code as alt text if country name is missing', () => {
      useSettingsStore.mockImplementation((selector) => {
        const state = {
          environment: {
            public_ip: '192.168.1.1',
            country_code: 'US',
          },
          version: mockVersion,
        };
        return selector(state);
      });

      renderSidebar();
      const flag = screen.getByAltText('US');
      expect(flag).toBeInTheDocument();
    });
  });

  describe('NavGroup Component', () => {
    it('should render Integrations group with children collapsed by default', () => {
      renderSidebar();

      expect(screen.getByText('Integrations')).toBeInTheDocument();
      expect(screen.queryByText('Connections')).not.toBeInTheDocument();
      expect(screen.queryByText('Logs')).not.toBeInTheDocument();
    });

    it('should expand Integrations group when clicked', async () => {
      renderSidebar();

      const integrationsGroup = screen
        .getByText('Integrations')
        .closest('button');
      fireEvent.click(integrationsGroup);

      await waitFor(() => {
        expect(screen.getByText('Connections')).toBeInTheDocument();
        expect(screen.getByText('Logs')).toBeInTheDocument();
      });
    });

    it('should collapse Integrations group when clicked again', async () => {
      renderSidebar();

      const integrationsGroup = screen
        .getByText('Integrations')
        .closest('button');

      // Expand
      fireEvent.click(integrationsGroup);
      await waitFor(() => {
        expect(screen.getByText('Connections')).toBeInTheDocument();
      });

      // Collapse
      fireEvent.click(integrationsGroup);
      await waitFor(() => {
        expect(screen.queryByText('Connections')).not.toBeInTheDocument();
        expect(screen.queryByText('Logs')).not.toBeInTheDocument();
      });
    });

    it('should render System group with children collapsed by default', () => {
      renderSidebar();

      expect(screen.getByText('System')).toBeInTheDocument();
      expect(screen.queryByText('Users')).not.toBeInTheDocument();
      expect(screen.queryByText('Logo Manager')).not.toBeInTheDocument();
    });

    it('should expand System group when clicked', async () => {
      renderSidebar();

      const systemGroup = screen.getByText('System').closest('button');
      fireEvent.click(systemGroup);

      await waitFor(() => {
        expect(screen.getByText('Users')).toBeInTheDocument();
        expect(screen.getByText('Logo Manager')).toBeInTheDocument();
        expect(screen.getByText('Settings')).toBeInTheDocument();
      });
    });

    it('should hide group label when collapsed sidebar', () => {
      renderSidebar({ collapsed: true });

      expect(screen.queryByText('Integrations')).not.toBeInTheDocument();
      expect(screen.queryByText('System')).not.toBeInTheDocument();
    });

    it('should not show multiple groups collapsed when both expanded', async () => {
      renderSidebar();

      const integrationsGroup = screen
        .getByText('Integrations')
        .closest('button');
      const systemGroup = screen.getByText('System').closest('button');

      // Expand Integrations
      fireEvent.click(integrationsGroup);
      await waitFor(() => {
        expect(screen.getByText('Connections')).toBeInTheDocument();
      });

      // Expand System (Integrations should remain expanded)
      fireEvent.click(systemGroup);
      await waitFor(() => {
        expect(screen.getByText('Users')).toBeInTheDocument();
        expect(screen.getByText('Connections')).toBeInTheDocument();
      });
    });
  });

  describe('NotificationCenter Integration', () => {
    it('should render NotificationCenter when authenticated and expanded', () => {
      renderSidebar();

      expect(screen.getByTestId('notification-center')).toBeInTheDocument();
    });

    it('should render NotificationCenter when authenticated and collapsed', () => {
      renderSidebar({ collapsed: true });

      expect(screen.getByTestId('notification-center')).toBeInTheDocument();
    });

    it('should not render NotificationCenter when not authenticated', () => {
      useAuthStore.mockImplementation((selector) => {
        const state = {
          isAuthenticated: false,
          user: null,
          logout: vi.fn(),
          getNavOrder: () => null,
          getHiddenNav: () => [],
        };
        return selector(state);
      });

      renderSidebar();

      expect(
        screen.queryByTestId('notification-center')
      ).not.toBeInTheDocument();
    });

    it('should not render NotificationCenter when not authenticated and collapsed', () => {
      useAuthStore.mockImplementation((selector) => {
        const state = {
          isAuthenticated: false,
          user: null,
          logout: vi.fn(),
          getNavOrder: () => null,
          getHiddenNav: () => [],
        };
        return selector(state);
      });

      renderSidebar({ collapsed: true });

      expect(
        screen.queryByTestId('notification-center')
      ).not.toBeInTheDocument();
    });
  });

  describe('Channel Count Badge', () => {
    it('should display 0 when no channels exist', () => {
      useChannelsStore.mockReturnValue({});

      renderSidebar();

      expect(screen.getByText('(0)')).toBeInTheDocument();
    });

    it('should handle null channelIds gracefully', () => {
      useChannelsStore.mockReturnValue(null);

      renderSidebar();

      expect(screen.getByText('(0)')).toBeInTheDocument();
    });

    it('should handle array of channel IDs', () => {
      useChannelsStore.mockReturnValue(['channel-1', 'channel-2', 'channel-3']);

      renderSidebar();

      expect(screen.getByText('(3)')).toBeInTheDocument();
    });
  });
});
