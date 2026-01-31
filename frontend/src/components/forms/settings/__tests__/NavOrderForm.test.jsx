import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import userEvent from '@testing-library/user-event';
import NavOrderForm from '../NavOrderForm';
import useAuthStore from '../../../../store/auth';
import { USER_LEVELS } from '../../../../constants';
import { DEFAULT_ADMIN_ORDER, DEFAULT_USER_ORDER } from '../../../../config/navigation';

// Mock dependencies
vi.mock('../../../../store/auth');
vi.mock('@mantine/notifications', () => ({
  notifications: {
    show: vi.fn(),
  },
}));

// Mock dnd-kit
vi.mock('@dnd-kit/core', () => ({
  DndContext: ({ children }) => <div data-testid="dnd-context">{children}</div>,
  closestCenter: vi.fn(),
  KeyboardSensor: vi.fn(),
  MouseSensor: vi.fn(),
  TouchSensor: vi.fn(),
  useSensor: vi.fn(),
  useSensors: vi.fn(() => []),
}));

vi.mock('@dnd-kit/sortable', () => ({
  SortableContext: ({ children }) => <div data-testid="sortable-context">{children}</div>,
  useSortable: () => ({
    transform: null,
    transition: null,
    setNodeRef: vi.fn(),
    isDragging: false,
    attributes: {},
    listeners: {},
  }),
  arrayMove: vi.fn((arr, from, to) => {
    const result = [...arr];
    const [removed] = result.splice(from, 1);
    result.splice(to, 0, removed);
    return result;
  }),
  verticalListSortingStrategy: vi.fn(),
}));

vi.mock('@dnd-kit/utilities', () => ({
  CSS: {
    Transform: {
      toString: vi.fn(() => ''),
    },
  },
}));

vi.mock('@dnd-kit/modifiers', () => ({
  restrictToVerticalAxis: vi.fn(),
}));

// Mock Mantine components
vi.mock('@mantine/core', () => ({
  Box: ({ children, ...props }) => <div {...props}>{children}</div>,
  Button: ({ children, onClick, disabled, ...props }) => (
    <button onClick={onClick} disabled={disabled} data-testid="reset-button">
      {children}
    </button>
  ),
  Text: ({ children }) => <span>{children}</span>,
  Group: ({ children }) => <div>{children}</div>,
  ActionIcon: ({ children, ...props }) => <button {...props}>{children}</button>,
  Stack: ({ children }) => <div>{children}</div>,
  useMantineTheme: () => ({}),
}));

describe('NavOrderForm', () => {
  const mockSetNavOrder = vi.fn();
  const mockGetNavOrder = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockSetNavOrder.mockResolvedValue({});
    mockGetNavOrder.mockReturnValue(null);
  });

  describe('Admin User', () => {
    beforeEach(() => {
      useAuthStore.mockImplementation((selector) => {
        const state = {
          user: { user_level: USER_LEVELS.ADMIN, custom_properties: {} },
          getNavOrder: mockGetNavOrder,
          setNavOrder: mockSetNavOrder,
        };
        return selector(state);
      });
    });

    it('renders all nav items for admin user', () => {
      render(<NavOrderForm active={true} />);

      expect(screen.getByText('Channels')).toBeInTheDocument();
      expect(screen.getByText('VODs')).toBeInTheDocument();
      expect(screen.getByText('M3U & EPG Manager')).toBeInTheDocument();
      expect(screen.getByText('TV Guide')).toBeInTheDocument();
      expect(screen.getByText('DVR')).toBeInTheDocument();
      expect(screen.getByText('Stats')).toBeInTheDocument();
      expect(screen.getByText('Plugins')).toBeInTheDocument();
      expect(screen.getByText('Users')).toBeInTheDocument();
      expect(screen.getByText('Logo Manager')).toBeInTheDocument();
      expect(screen.getByText('Settings')).toBeInTheDocument();
    });

    it('renders reset to default button', () => {
      render(<NavOrderForm active={true} />);

      expect(screen.getByTestId('reset-button')).toBeInTheDocument();
      expect(screen.getByText('Reset to Default')).toBeInTheDocument();
    });

    it('does not render when not active', () => {
      render(<NavOrderForm active={false} />);

      expect(screen.queryByText('Channels')).not.toBeInTheDocument();
    });

    it('calls setNavOrder when reset button is clicked', async () => {
      const user = userEvent.setup();
      render(<NavOrderForm active={true} />);

      const resetButton = screen.getByTestId('reset-button');
      await user.click(resetButton);

      await waitFor(() => {
        expect(mockSetNavOrder).toHaveBeenCalledWith(DEFAULT_ADMIN_ORDER);
      });
    });

    it('uses saved order when available', () => {
      const customOrder = ['settings', 'channels', 'vods', 'sources', 'guide', 'dvr', 'stats', 'plugins', 'users', 'logos'];
      mockGetNavOrder.mockReturnValue(customOrder);

      render(<NavOrderForm active={true} />);

      // The component should render with custom order
      expect(screen.getByText('Channels')).toBeInTheDocument();
      expect(screen.getByText('Settings')).toBeInTheDocument();
    });
  });

  describe('Non-Admin User', () => {
    beforeEach(() => {
      useAuthStore.mockImplementation((selector) => {
        const state = {
          user: { user_level: USER_LEVELS.USER, custom_properties: {} },
          getNavOrder: mockGetNavOrder,
          setNavOrder: mockSetNavOrder,
        };
        return selector(state);
      });
    });

    it('renders only non-admin nav items for regular user', () => {
      render(<NavOrderForm active={true} />);

      // Non-admin items should be visible
      expect(screen.getByText('Channels')).toBeInTheDocument();
      expect(screen.getByText('TV Guide')).toBeInTheDocument();
      expect(screen.getByText('Settings')).toBeInTheDocument();

      // Admin-only items should not be visible
      expect(screen.queryByText('VODs')).not.toBeInTheDocument();
      expect(screen.queryByText('M3U & EPG Manager')).not.toBeInTheDocument();
      expect(screen.queryByText('DVR')).not.toBeInTheDocument();
      expect(screen.queryByText('Stats')).not.toBeInTheDocument();
      expect(screen.queryByText('Plugins')).not.toBeInTheDocument();
      expect(screen.queryByText('Users')).not.toBeInTheDocument();
      expect(screen.queryByText('Logo Manager')).not.toBeInTheDocument();
    });

    it('calls setNavOrder with user default order when reset', async () => {
      const user = userEvent.setup();
      render(<NavOrderForm active={true} />);

      const resetButton = screen.getByTestId('reset-button');
      await user.click(resetButton);

      await waitFor(() => {
        expect(mockSetNavOrder).toHaveBeenCalledWith(DEFAULT_USER_ORDER);
      });
    });
  });
});
