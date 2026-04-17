import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import AssignChannelNumbers from '../AssignChannelNumbers';

// ── API mock ───────────────────────────────────────────────────────────────────
vi.mock('../../../api', () => ({
  default: {
    assignChannelNumbers: vi.fn(),
    requeryChannels: vi.fn(),
  },
}));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

// ── Mantine form ───────────────────────────────────────────────────────────────
vi.mock('@mantine/form', () => ({
  useForm: vi.fn(() => ({
    getValues: vi.fn(() => ({ starting_number: 1 })),
    getInputProps: vi.fn(() => ({})),
    onSubmit: vi.fn((fn) => fn),
  })),
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Button: ({
    children,
    onClick,
    disabled,
    loading,
    variant,
    color,
    leftSection,
  }) => (
    <button
      data-testid="button"
      onClick={onClick}
      disabled={disabled || loading}
      data-variant={variant}
      data-color={color}
      data-loading={loading}
    >
      {leftSection}
      {children}
    </button>
  ),
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
  Text: ({ children }) => <span>{children}</span>,
  Group: ({ children }) => <div>{children}</div>,
  Flex: ({ children }) => <div>{children}</div>,
  NumberInput: ({ label, value, onChange, min }) => (
    <input
      data-testid="number-input"
      type="number"
      aria-label={label}
      value={value ?? ''}
      min={min}
      onChange={(e) => onChange?.(Number(e.target.value))}
    />
  ),
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  ListOrdered: () => <svg data-testid="icon-list-ordered" />,
}));

// ──────────────────────────────────────────────────────────────────────────────
// Imports after mocks
// ──────────────────────────────────────────────────────────────────────────────
import API from '../../../api';
import { showNotification } from '../../../utils/notificationUtils.js';
import { useForm } from '@mantine/form';

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────
const defaultProps = (overrides = {}) => ({
  channelIds: ['ch-1', 'ch-2', 'ch-3'],
  isOpen: true,
  onClose: vi.fn(),
  ...overrides,
});

const setupMocks = ({ startingNumber = 1, getValues } = {}) => {
  vi.mocked(useForm).mockReturnValue({
    getValues: getValues ?? vi.fn(() => ({ starting_number: startingNumber })),
    getInputProps: vi.fn(() => ({})),
    onSubmit: vi.fn((fn) => fn),
    key: vi.fn(),
  });
  vi.mocked(API.assignChannelNumbers).mockResolvedValue({
    message: 'Channels assigned successfully',
  });
  vi.mocked(API.requeryChannels).mockReturnValue(undefined);
};

// ──────────────────────────────────────────────────────────────────────────────
// Tests
// ──────────────────────────────────────────────────────────────────────────────
describe('AssignChannelNumbers', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Visibility ─────────────────────────────────────────────────────────────

  describe('visibility', () => {
    it('renders the modal when isOpen is true', () => {
      setupMocks();
      render(<AssignChannelNumbers {...defaultProps()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('does not render the modal when isOpen is false', () => {
      setupMocks();
      render(<AssignChannelNumbers {...defaultProps({ isOpen: false })} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('calls onClose when modal close button is clicked', () => {
      setupMocks();
      const onClose = vi.fn();
      render(<AssignChannelNumbers {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
    });
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the modal title', () => {
      setupMocks();
      render(<AssignChannelNumbers {...defaultProps()} />);
      expect(screen.getByTestId('modal-title')).toBeInTheDocument();
    });

    it('renders the number input', () => {
      setupMocks();
      render(<AssignChannelNumbers {...defaultProps()} />);
      expect(screen.getByTestId('number-input')).toBeInTheDocument();
    });

    it('renders the submit button', () => {
      setupMocks();
      render(<AssignChannelNumbers {...defaultProps()} />);
      expect(screen.getByTestId('button')).toBeInTheDocument();
    });

    it('renders the ListOrdered icon', () => {
      setupMocks();
      render(<AssignChannelNumbers {...defaultProps()} />);
      expect(screen.getByTestId('icon-list-ordered')).toBeInTheDocument();
    });
  });

  // ── Form submission ────────────────────────────────────────────────────────

  describe('form submission', () => {
    it('calls assignChannelNumbers with channelIds and starting_number on submit', async () => {
      setupMocks({ startingNumber: 5 });
      render(<AssignChannelNumbers {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('button'));
      await waitFor(() => {
        expect(API.assignChannelNumbers).toHaveBeenCalledWith(
          ['ch-1', 'ch-2', 'ch-3'],
          5
        );
      });
    });

    it('calls assignChannelNumbers with default starting_number of 1', async () => {
      setupMocks({ startingNumber: 1 });
      render(<AssignChannelNumbers {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('button'));
      await waitFor(() => {
        expect(API.assignChannelNumbers).toHaveBeenCalledWith(
          ['ch-1', 'ch-2', 'ch-3'],
          1
        );
      });
    });

    it('calls requeryChannels after successful assignment', async () => {
      setupMocks();
      render(<AssignChannelNumbers {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('button'));
      await waitFor(() => {
        expect(API.requeryChannels).toHaveBeenCalled();
      });
    });

    it('calls onClose after successful assignment', async () => {
      setupMocks();
      const onClose = vi.fn();
      render(<AssignChannelNumbers {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByTestId('button'));
      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });

    it('calls assignChannelNumbers exactly once per submit', async () => {
      setupMocks();
      render(<AssignChannelNumbers {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('button'));
      await waitFor(() => {
        expect(API.assignChannelNumbers).toHaveBeenCalledTimes(1);
      });
    });
  });

  // ── Notifications ──────────────────────────────────────────────────────────

  describe('notifications', () => {
    it('shows success notification with API message on success', async () => {
      setupMocks();
      vi.mocked(API.assignChannelNumbers).mockResolvedValue({
        message: 'Channels assigned successfully',
      });
      render(<AssignChannelNumbers {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('button'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Channels assigned successfully',
            color: 'green.5',
          })
        );
      });
    });

    it('shows fallback "Channels assigned" notification when message is absent', async () => {
      setupMocks();
      vi.mocked(API.assignChannelNumbers).mockResolvedValue({});
      render(<AssignChannelNumbers {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('button'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Channels assigned',
            color: 'green.5',
          })
        );
      });
    });

    it('shows error notification when assignChannelNumbers throws', async () => {
      setupMocks();
      vi.mocked(API.assignChannelNumbers).mockRejectedValue(
        new Error('Server error')
      );
      render(<AssignChannelNumbers {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('button'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'red.5' })
        );
      });
    });

    it('does not show success notification when assignChannelNumbers throws', async () => {
      setupMocks();
      vi.mocked(API.assignChannelNumbers).mockRejectedValue(new Error('fail'));
      render(<AssignChannelNumbers {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('button'));
      await waitFor(() => {
        expect(showNotification).not.toHaveBeenCalledWith(
          expect.objectContaining({ color: 'green.5' })
        );
      });
    });
  });

  // ── Error handling ─────────────────────────────────────────────────────────

  describe('error handling', () => {
    it('does not call requeryChannels when assignChannelNumbers throws', async () => {
      setupMocks();
      vi.mocked(API.assignChannelNumbers).mockRejectedValue(new Error('fail'));
      render(<AssignChannelNumbers {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('button'));
      await waitFor(() => {
        expect(API.requeryChannels).not.toHaveBeenCalled();
      });
    });

    it('does not call onClose when assignChannelNumbers throws', async () => {
      setupMocks();
      const onClose = vi.fn();
      vi.mocked(API.assignChannelNumbers).mockRejectedValue(new Error('fail'));
      render(<AssignChannelNumbers {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByTestId('button'));
      await waitFor(() => {
        expect(onClose).not.toHaveBeenCalled();
      });
    });

    it('does not throw when channelIds is an empty array', async () => {
      setupMocks();
      render(<AssignChannelNumbers {...defaultProps({ channelIds: [] })} />);
      fireEvent.click(screen.getByTestId('button'));
      await waitFor(() => {
        expect(API.assignChannelNumbers).toHaveBeenCalledWith([], 1);
      });
    });
  });

  // ── channelIds prop ────────────────────────────────────────────────────────

  describe('channelIds prop', () => {
    it('passes a single channelId correctly', async () => {
      setupMocks();
      render(
        <AssignChannelNumbers {...defaultProps({ channelIds: ['ch-99'] })} />
      );
      fireEvent.click(screen.getByTestId('button'));
      await waitFor(() => {
        expect(API.assignChannelNumbers).toHaveBeenCalledWith(['ch-99'], 1);
      });
    });

    it('passes all channelIds to assignChannelNumbers', async () => {
      setupMocks();
      const channelIds = ['ch-1', 'ch-2', 'ch-3', 'ch-4', 'ch-5'];
      render(<AssignChannelNumbers {...defaultProps({ channelIds })} />);
      fireEvent.click(screen.getByTestId('button'));
      await waitFor(() => {
        expect(API.assignChannelNumbers).toHaveBeenCalledWith(channelIds, 1);
      });
    });
  });
});
