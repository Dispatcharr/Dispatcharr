import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { BrowserRouter } from 'react-router-dom';
import NotificationCenter from '../NotificationCenter';
import useNotificationsStore from '../../store/notifications';
import * as NotificationUtils from '../../utils/components/NotificationCenterUtils';

// Mock the notifications store
vi.mock('../../store/notifications');

// Mock the notification utils
vi.mock('../../utils/components/NotificationCenterUtils', () => ({
  getNotifications: vi.fn(),
  dismissNotification: vi.fn(),
  dismissAllNotifications: vi.fn(),
}));

// Mock react-router-dom
const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

// Mock Mantine components
vi.mock('@mantine/core', async () => {
  return {
    Popover: ({ children, opened }) => (
      <div data-testid="popover" data-opened={opened}>
        {children}
      </div>
    ),
    PopoverTarget: ({ children }) => (
      <div data-testid="popover-target">{children}</div>
    ),
    PopoverDropdown: ({ children }) => (
      <div data-testid="popover-dropdown">{children}</div>
    ),
    Indicator: ({ children, label, disabled, processing }) => (
      <div
        data-testid="indicator"
        data-label={label}
        data-disabled={disabled}
        data-processing={processing}
      >
        {children}
      </div>
    ),
    ActionIcon: ({ children, onClick, 'aria-label': ariaLabel, ...props }) => (
      <button
        onClick={onClick}
        aria-label={ariaLabel}
        data-testid={`action-icon-${ariaLabel}`}
        {...props}
      >
        {children}
      </button>
    ),
    ScrollAreaAutosize: ({ children }) => (
      <div data-testid="scroll-area">{children}</div>
    ),
    Badge: ({ children, ...props }) => (
      <span data-testid="badge" {...props}>
        {children}
      </span>
    ),
    Card: ({ children, ...props }) => (
      <div data-testid="notification-card" {...props}>
        {children}
      </div>
    ),
    ThemeIcon: ({ children, ...props }) => (
      <div data-testid="theme-icon" {...props}>
        {children}
      </div>
    ),
    Group: ({ children, ...props }) => (
      <div data-testid="group" {...props}>
        {children}
      </div>
    ),
    Stack: ({ children, ...props }) => (
      <div data-testid="stack" {...props}>
        {children}
      </div>
    ),
    Box: ({ children, ...props }) => (
      <div data-testid="box" {...props}>
        {children}
      </div>
    ),
    Text: ({ children, ...props }) => (
      <span data-testid="text" {...props}>
        {children}
      </span>
    ),
    Button: ({ children, onClick, ...props }) => (
      <button onClick={onClick} data-testid="button" {...props}>
        {children}
      </button>
    ),
    Divider: () => <hr data-testid="divider" />,
    Tooltip: ({ children, label }) => (
      <div data-testid="tooltip" title={label}>
        {children}
      </div>
    ),
    useMantineTheme: () => ({
      colors: {
        red: ['', '', '', '', '', '#fa5252', '', '', '', '#c92a2a'],
        orange: ['', '', '', '', '', '#fd7e14'],
        blue: ['', '', '', '', '', '#228be6'],
        gray: ['', '', '', '', '', '#adb5bd'],
        green: ['', '', '', '', '', '#51cf66'],
        violet: ['', '', '', '', '', '#7950f2'],
      },
    }),
  };
});

// Mock lucide-react icons
vi.mock('lucide-react', () => ({
  ListOrdered: () => <span data-testid="icon-list-ordered">ListOrdered</span>,
  Bell: () => <span data-testid="bell-icon">Bell</span>,
  Check: () => <span data-testid="check-icon">Check</span>,
  CheckCheck: () => <span data-testid="checkcheck-icon">CheckCheck</span>,
  Download: () => <span data-testid="download-icon">Download</span>,
  ExternalLink: () => (
    <span data-testid="external-link-icon">ExternalLink</span>
  ),
  Info: () => <span data-testid="info-icon">Info</span>,
  Settings: () => <span data-testid="settings-icon">Settings</span>,
  AlertTriangle: () => (
    <span data-testid="alert-triangle-icon">AlertTriangle</span>
  ),
  Megaphone: () => <span data-testid="megaphone-icon">Megaphone</span>,
  X: () => <span data-testid="x-icon">X</span>,
  Eye: () => <span data-testid="eye-icon">Eye</span>,
  EyeOff: () => <span data-testid="eyeoff-icon">EyeOff</span>,
  ArrowRight: () => <span data-testid="arrow-right-icon">ArrowRight</span>,
}));

const mockNotifications = [
  {
    id: 1,
    title: 'Version Update Available',
    message: 'Version 2.0 is available',
    notification_type: 'version_update',
    priority: 'high',
    is_dismissed: false,
    created_at: '2024-01-01T10:00:00Z',
    action_data: {
      release_url: 'https://github.com/releases/v2.0',
    },
  },
  {
    id: 2,
    title: 'Setting Recommendation',
    message: 'Enable dark mode for better experience',
    notification_type: 'setting_recommendation',
    priority: 'normal',
    is_dismissed: false,
    created_at: '2024-01-02T10:00:00Z',
    action_data: {},
  },
  {
    id: 3,
    title: 'System Announcement',
    message: 'Maintenance scheduled for tomorrow',
    notification_type: 'announcement',
    priority: 'normal',
    is_dismissed: true,
    created_at: '2024-01-03T10:00:00Z',
    action_data: {},
  },
  {
    id: 4,
    title: 'Critical Warning',
    message: 'System issue detected',
    notification_type: 'warning',
    priority: 'critical',
    is_dismissed: false,
    created_at: '2024-01-04T10:00:00Z',
    action_data: {},
  },
];

describe('NotificationCenter', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // vi.useFakeTimers();

    // Default store mock
    useNotificationsStore.mockImplementation((selector) => {
      const state = {
        notifications: mockNotifications,
        unreadCount: 3,
        getUnreadNotifications: vi.fn(() =>
          mockNotifications.filter((n) => !n.is_dismissed)
        ),
      };
      return selector ? selector(state) : state;
    });

    NotificationUtils.getNotifications.mockResolvedValue();
    NotificationUtils.dismissNotification.mockResolvedValue();
    NotificationUtils.dismissAllNotifications.mockResolvedValue();
  });

  afterEach(() => {
    vi.clearAllTimers();
  });

  const renderComponent = (props = {}) => {
    return render(
      <BrowserRouter>
        <NotificationCenter {...props} />
      </BrowserRouter>
    );
  };

  describe('Bell Icon and Indicator', () => {
    it('should render bell icon', () => {
      renderComponent();
      expect(screen.getByLabelText('Notifications')).toBeInTheDocument();
      expect(screen.getByTestId('bell-icon')).toBeInTheDocument();
    });

    it('should show unread count indicator when there are unread notifications', () => {
      renderComponent();
      const indicator = screen.getByTestId('indicator');
      expect(indicator).toHaveAttribute('data-label', '3');
      expect(indicator).toHaveAttribute('data-disabled', 'false');
      expect(indicator).toHaveAttribute('data-processing', 'true');
    });

    it('should not show indicator when unread count is zero', () => {
      useNotificationsStore.mockImplementation((selector) => {
        const state = {
          notifications: [],
          unreadCount: 0,
          getUnreadNotifications: vi.fn(() => []),
        };
        return selector ? selector(state) : state;
      });

      renderComponent();
      const indicator = screen.getByTestId('indicator');
      expect(indicator).toHaveAttribute('data-disabled', 'true');
    });

    it('should show "9+" when unread count exceeds 9', () => {
      useNotificationsStore.mockImplementation((selector) => {
        const state = {
          notifications: mockNotifications,
          unreadCount: 15,
          getUnreadNotifications: vi.fn(() => mockNotifications),
        };
        return selector ? selector(state) : state;
      });

      renderComponent();
      const indicator = screen.getByTestId('indicator');
      expect(indicator).toHaveAttribute('data-label', '9+');
    });
  });

  describe('Popover Toggle', () => {
    it('should open popover when bell icon is clicked', () => {
      renderComponent();
      const bellButton = screen.getByLabelText('Notifications');

      fireEvent.click(bellButton);

      const popover = screen.getByTestId('popover');
      expect(popover).toHaveAttribute('data-opened', 'true');
    });

    it('should close popover when bell icon is clicked again', () => {
      renderComponent();
      const bellButton = screen.getByLabelText('Notifications');

      fireEvent.click(bellButton);
      fireEvent.click(bellButton);

      const popover = screen.getByTestId('popover');
      expect(popover).toHaveAttribute('data-opened', 'false');
    });

    it('should display notification header with count', () => {
      renderComponent();
      fireEvent.click(screen.getByLabelText('Notifications'));

      expect(screen.getByText('Notifications')).toBeInTheDocument();
      expect(screen.getByText('3 new')).toBeInTheDocument();
    });
  });

  describe('API Calls', () => {
    it('should fetch notifications on mount', async () => {
      renderComponent();

      await waitFor(() => {
        expect(NotificationUtils.getNotifications).toHaveBeenCalledWith(false);
      });
    });

    it('should fetch notifications every 5 minutes', () => {
      vi.useFakeTimers();

      renderComponent();

      expect(NotificationUtils.getNotifications).toHaveBeenCalledTimes(1);

      vi.advanceTimersByTime(5 * 60 * 1000);

      expect(NotificationUtils.getNotifications).toHaveBeenCalledTimes(2);

      vi.useRealTimers();
    });

    it('should handle API errors gracefully', async () => {
      const consoleError = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      NotificationUtils.getNotifications.mockRejectedValue(
        new Error('Network error')
      );

      renderComponent();

      await waitFor(() => {
        expect(consoleError).toHaveBeenCalledWith(
          'Failed to fetch notifications:',
          expect.any(Error)
        );
      });

      consoleError.mockRestore();
    });
  });

  describe('Notification Display', () => {
    it('should display unread notifications by default', () => {
      renderComponent();
      fireEvent.click(screen.getByLabelText('Notifications'));

      expect(screen.getByText('Version Update Available')).toBeInTheDocument();
      expect(screen.getByText('Setting Recommendation')).toBeInTheDocument();
      expect(screen.getByText('Critical Warning')).toBeInTheDocument();
      expect(screen.queryByText('System Announcement')).not.toBeInTheDocument();
    });

    it('should display all notifications when show dismissed is toggled', () => {
      renderComponent();
      fireEvent.click(screen.getByLabelText('Notifications'));

      const eyeButtons = screen.getAllByTestId(/action-icon-/);
      const toggleButton = eyeButtons.find((btn) =>
        btn.querySelector('[data-testid="eye-icon"]')
      );
      fireEvent.click(toggleButton);

      expect(screen.getByText('System Announcement')).toBeInTheDocument();
    });

    it('should show empty state when no unread notifications', () => {
      useNotificationsStore.mockImplementation((selector) => {
        const state = {
          notifications: [],
          unreadCount: 0,
          getUnreadNotifications: vi.fn(() => []),
        };
        return selector ? selector(state) : state;
      });

      renderComponent();
      fireEvent.click(screen.getByLabelText('Notifications'));

      expect(screen.getByText('All caught up!')).toBeInTheDocument();
      expect(screen.getByText('No new notifications')).toBeInTheDocument();
    });

    it('should show dismissed count in footer', () => {
      renderComponent();
      fireEvent.click(screen.getByLabelText('Notifications'));

      expect(screen.getByText('1 dismissed notification')).toBeInTheDocument();
    });

    it('should show correct dismissed count with multiple dismissed notifications', () => {
      const notifications = [
        ...mockNotifications,
        { ...mockNotifications[2], id: 5, is_dismissed: true },
      ];

      useNotificationsStore.mockImplementation((selector) => {
        const state = {
          notifications,
          unreadCount: 3,
          getUnreadNotifications: vi.fn(() =>
            notifications.filter((n) => !n.is_dismissed)
          ),
        };
        return selector ? selector(state) : state;
      });

      renderComponent();
      fireEvent.click(screen.getByLabelText('Notifications'));

      expect(screen.getByText('2 dismissed notifications')).toBeInTheDocument();
    });
  });

  describe('Notification Actions', () => {
    it('should dismiss notification when X button is clicked', async () => {
      renderComponent();
      fireEvent.click(screen.getByLabelText('Notifications'));

      const xIcons = screen.getAllByTestId('x-icon');
      fireEvent.click(xIcons[0].closest('button'));

      await waitFor(() => {
        expect(NotificationUtils.dismissNotification).toHaveBeenCalledWith(
          1,
          'dismissed'
        );
      });
    });

    it('should dismiss all notifications when CheckCheck button is clicked', async () => {
      renderComponent();
      fireEvent.click(screen.getByLabelText('Notifications'));

      const checkCheckIcon = screen.getByTestId('checkcheck-icon');
      fireEvent.click(checkCheckIcon.closest('button'));

      await waitFor(() => {
        expect(NotificationUtils.dismissAllNotifications).toHaveBeenCalled();
      });
    });

    it('should open release URL for version update notification', () => {
      const windowOpen = vi.spyOn(window, 'open').mockImplementation(() => {});

      renderComponent();
      fireEvent.click(screen.getByLabelText('Notifications'));

      const viewReleaseButton = screen.getByText('View Release');
      fireEvent.click(viewReleaseButton);

      expect(windowOpen).toHaveBeenCalledWith(
        'https://github.com/releases/v2.0',
        '_blank'
      );

      windowOpen.mockRestore();
    });

    it('should navigate for notifications with action_url', () => {
      const notificationWithUrl = {
        ...mockNotifications[0],
        action_data: {
          action_url: '/settings',
          action_text: 'Go to Settings',
        },
      };

      useNotificationsStore.mockImplementation((selector) => {
        const state = {
          notifications: [notificationWithUrl],
          unreadCount: 1,
          getUnreadNotifications: vi.fn(() => [notificationWithUrl]),
        };
        return selector ? selector(state) : state;
      });

      renderComponent();
      fireEvent.click(screen.getByLabelText('Notifications'));

      const actionButton = screen.getByText('Go to Settings');
      fireEvent.click(actionButton);

      expect(mockNavigate).toHaveBeenCalledWith('/settings');
    });

    it('should call onSettingAction when applying setting recommendation', async () => {
      const onSettingAction = vi.fn();
      renderComponent({ onSettingAction });
      fireEvent.click(screen.getByLabelText('Notifications'));

      const applyButton = screen.getByText('Apply');
      fireEvent.click(applyButton);

      await waitFor(() => {
        expect(NotificationUtils.dismissNotification).toHaveBeenCalledWith(
          2,
          'applied'
        );
        expect(onSettingAction).toHaveBeenCalledWith(mockNotifications[1]);
      });
    });

    it('should dismiss setting recommendation when Ignore is clicked', async () => {
      renderComponent();
      fireEvent.click(screen.getByLabelText('Notifications'));

      const ignoreButton = screen.getByText('Ignore');
      fireEvent.click(ignoreButton);

      await waitFor(() => {
        expect(NotificationUtils.dismissNotification).toHaveBeenCalledWith(
          2,
          'dismissed'
        );
      });
    });

    it('should close popover when navigating with action_url', () => {
      const notificationWithUrl = {
        ...mockNotifications[0],
        action_data: {
          action_url: '/settings',
          action_text: 'Go to Settings',
        },
      };

      useNotificationsStore.mockImplementation((selector) => {
        const state = {
          notifications: [notificationWithUrl],
          unreadCount: 1,
          getUnreadNotifications: vi.fn(() => [notificationWithUrl]),
        };
        return selector ? selector(state) : state;
      });

      renderComponent();
      fireEvent.click(screen.getByLabelText('Notifications'));

      const actionButton = screen.getByText('Go to Settings');
      fireEvent.click(actionButton);

      const popover = screen.getByTestId('popover');
      expect(popover).toHaveAttribute('data-opened', 'false');
    });
  });

  describe('Notification Types and Icons', () => {
    it('should render correct icon for version_update', () => {
      renderComponent();
      fireEvent.click(screen.getByLabelText('Notifications'));

      expect(screen.getByTestId('download-icon')).toBeInTheDocument();
    });

    it('should render correct icon for setting_recommendation', () => {
      renderComponent();
      fireEvent.click(screen.getByLabelText('Notifications'));

      expect(screen.getByTestId('settings-icon')).toBeInTheDocument();
    });

    it('should render correct icon for announcement', () => {
      useNotificationsStore.mockImplementation((selector) => {
        const state = {
          notifications: [mockNotifications[2]],
          unreadCount: 0,
          getUnreadNotifications: vi.fn(() => []),
        };
        return selector ? selector(state) : state;
      });

      renderComponent();
      fireEvent.click(screen.getByLabelText('Notifications'));

      const eyeButtons = screen.getAllByTestId(/action-icon-/);
      const toggleButton = eyeButtons.find((btn) =>
        btn.querySelector('[data-testid="eye-icon"]')
      );
      fireEvent.click(toggleButton);

      expect(screen.getByTestId('megaphone-icon')).toBeInTheDocument();
    });

    it('should render correct icon for warning', () => {
      renderComponent();
      fireEvent.click(screen.getByLabelText('Notifications'));

      expect(screen.getByTestId('alert-triangle-icon')).toBeInTheDocument();
    });

    it('should render info icon for unknown type', () => {
      const unknownTypeNotification = {
        ...mockNotifications[0],
        notification_type: 'unknown',
        is_dismissed: false,
      };

      useNotificationsStore.mockImplementation((selector) => {
        const state = {
          notifications: [unknownTypeNotification],
          unreadCount: 1,
          getUnreadNotifications: vi.fn(() => [unknownTypeNotification]),
        };
        return selector ? selector(state) : state;
      });

      renderComponent();
      fireEvent.click(screen.getByLabelText('Notifications'));

      expect(screen.getByTestId('info-icon')).toBeInTheDocument();
    });
  });

  describe('Priority Badges', () => {
    it('should show priority badge for high priority notifications', () => {
      renderComponent();
      fireEvent.click(screen.getByLabelText('Notifications'));

      expect(screen.getByText('high')).toBeInTheDocument();
    });

    it('should show priority badge for critical priority notifications', () => {
      renderComponent();
      fireEvent.click(screen.getByLabelText('Notifications'));

      expect(screen.getByText('critical')).toBeInTheDocument();
    });

    it('should not show priority badge for normal priority', () => {
      const normalNotification = {
        ...mockNotifications[1],
        priority: 'normal',
      };

      useNotificationsStore.mockImplementation((selector) => {
        const state = {
          notifications: [normalNotification],
          unreadCount: 1,
          getUnreadNotifications: vi.fn(() => [normalNotification]),
        };
        return selector ? selector(state) : state;
      });

      renderComponent();
      fireEvent.click(screen.getByLabelText('Notifications'));

      expect(screen.queryByText('normal')).not.toBeInTheDocument();
    });

    it('should show dismissed badge for dismissed notifications', () => {
      renderComponent();
      fireEvent.click(screen.getByLabelText('Notifications'));

      const eyeButtons = screen.getAllByTestId(/action-icon-/);
      const toggleButton = eyeButtons.find((btn) =>
        btn.querySelector('[data-testid="eye-icon"]')
      );
      fireEvent.click(toggleButton);

      expect(screen.getByText('Dismissed')).toBeInTheDocument();
    });
  });

  describe('Error Handling', () => {
    it('should handle dismiss notification errors', async () => {
      const consoleError = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      NotificationUtils.dismissNotification.mockRejectedValue(
        new Error('API error')
      );

      renderComponent();
      fireEvent.click(screen.getByLabelText('Notifications'));

      const xIcons = screen.getAllByTestId('x-icon');
      fireEvent.click(xIcons[0].closest('button'));

      await waitFor(() => {
        expect(consoleError).toHaveBeenCalledWith(
          'Failed to dismiss notification:',
          expect.any(Error)
        );
      });

      consoleError.mockRestore();
    });

    it('should handle dismiss all notifications errors', async () => {
      const consoleError = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      NotificationUtils.dismissAllNotifications.mockRejectedValue(
        new Error('API error')
      );

      renderComponent();
      fireEvent.click(screen.getByLabelText('Notifications'));

      const checkCheckIcon = screen.getByTestId('checkcheck-icon');
      fireEvent.click(checkCheckIcon.closest('button'));

      await waitFor(() => {
        expect(consoleError).toHaveBeenCalledWith(
          'Failed to dismiss all notifications:',
          expect.any(Error)
        );
      });

      consoleError.mockRestore();
    });
  });

  describe('Date Display', () => {
    it('should display formatted date for notifications', () => {
      renderComponent();
      fireEvent.click(screen.getByLabelText('Notifications'));

      const expectedDate = new Date(
        '2024-01-01T10:00:00Z'
      ).toLocaleDateString();
      expect(screen.getByText(expectedDate)).toBeInTheDocument();
    });
  });
});
