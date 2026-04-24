import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ChannelGroup from '../ChannelGroup';
import API from '../../../api';
import useChannelsStore from '../../../store/channels';
import { showNotification } from '../../../utils/notificationUtils.js';
import { useForm } from '@mantine/form';

// ── API mock ───────────────────────────────────────────────────────────────────
vi.mock('../../../api', () => ({
  default: {
    addChannelGroup: vi.fn(),
    updateChannelGroup: vi.fn(),
  },
}));

// ── Store mock ─────────────────────────────────────────────────────────────────
vi.mock('../../../store/channels', () => ({ default: vi.fn() }));

// ── Notification util mock ─────────────────────────────────────────────────────
vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

// ── Mantine form mock ──────────────────────────────────────────────────────────
vi.mock('@mantine/form', () => ({
  isNotEmpty: vi.fn(() => (value) => (value ? null : 'Specify a name')),
  useForm: vi.fn(),
}));

// ── Mantine core mock ──────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
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
  TextInput: ({ label, disabled, value, onChange, id }) => (
    <input
      data-testid="name-input"
      id={id}
      aria-label={label}
      disabled={disabled}
      value={value ?? ''}
      onChange={onChange}
    />
  ),
  Button: ({ children, onClick, type, disabled }) => (
    <button
      data-testid="submit-button"
      type={type}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  ),
  Flex: ({ children }) => <div>{children}</div>,
  Alert: ({ children, color }) => (
    <div data-testid="alert" data-color={color}>
      {children}
    </div>
  ),
}));

// ── Helpers ────────────────────────────────────────────────────────────────────

const makeGroup = (overrides = {}) => ({
  id: 1,
  name: 'Sports',
  ...overrides,
});

/**
 * Build a minimal useForm mock.
 * @param {string} nameValue - current value of the name field
 * @param {object} overrides  - override any form property
 */
const makeFormMock = (nameValue = 'Sports', overrides = {}) => {
  const submitHandlers = [];

  return {
    getValues: vi.fn(() => ({ name: nameValue })),
    reset: vi.fn(),
    key: vi.fn((k) => k),
    submitting: false,
    getInputProps: vi.fn(() => ({ value: nameValue, onChange: vi.fn() })),
    onSubmit: vi.fn((handler) => {
      submitHandlers.push(handler);
      // Return the event handler that <form onSubmit={}> receives
      return (e) => {
        e?.preventDefault?.();
        handler();
      };
    }),
    _submitHandlers: submitHandlers,
    ...overrides,
  };
};

const setupMocks = ({ canEdit = true } = {}) => {
  vi.mocked(useChannelsStore).mockImplementation((sel) =>
    sel({ canEditChannelGroup: vi.fn(() => canEdit) })
  );
};

const renderForm = (props = {}) => {
  const defaults = {
    isOpen: true,
    onClose: vi.fn(),
    channelGroup: null,
  };
  return render(<ChannelGroup {...defaults} {...props} />);
};

// ──────────────────────────────────────────────────────────────────────────────
// Tests
// ──────────────────────────────────────────────────────────────────────────────

describe('ChannelGroup', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Visibility ─────────────────────────────────────────────────────────────

  describe('visibility', () => {
    it('renders nothing when isOpen is false', () => {
      setupMocks();
      const form = makeFormMock('');
      vi.mocked(useForm).mockReturnValue(form);

      renderForm({ isOpen: false });

      expect(screen.queryByTestId('modal')).toBeNull();
    });

    it('renders the modal when isOpen is true', () => {
      setupMocks();
      vi.mocked(useForm).mockReturnValue(makeFormMock(''));

      renderForm({ isOpen: true });

      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('renders "Channel Group" as the modal title', () => {
      setupMocks();
      vi.mocked(useForm).mockReturnValue(makeFormMock(''));

      renderForm();

      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'Channel Group'
      );
    });
  });

  // ── Add new group ──────────────────────────────────────────────────────────

  describe('adding a new group', () => {
    it('renders the name input', () => {
      setupMocks();
      vi.mocked(useForm).mockReturnValue(makeFormMock(''));

      renderForm();

      expect(screen.getByTestId('name-input')).toBeInTheDocument();
    });

    it('renders the Submit button', () => {
      setupMocks();
      vi.mocked(useForm).mockReturnValue(makeFormMock(''));

      renderForm();

      expect(screen.getByTestId('submit-button')).toBeInTheDocument();
    });

    it('does not show the alert for a new group', () => {
      setupMocks();
      vi.mocked(useForm).mockReturnValue(makeFormMock(''));

      renderForm({ channelGroup: null });

      expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
    });

    it('calls addChannelGroup with form values on submit', async () => {
      setupMocks();
      const newGroup = { id: 99, name: 'NewGroup' };
      vi.mocked(API.addChannelGroup).mockResolvedValue(newGroup);

      const form = makeFormMock('NewGroup');
      vi.mocked(useForm).mockReturnValue(form);

      const onClose = vi.fn();
      renderForm({ channelGroup: null, onClose });

      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));

      await waitFor(() => {
        expect(API.addChannelGroup).toHaveBeenCalledWith({ name: 'NewGroup' });
      });
    });

    it('calls onClose with the new group after successful add', async () => {
      setupMocks();
      const newGroup = { id: 99, name: 'NewGroup' };
      vi.mocked(API.addChannelGroup).mockResolvedValue(newGroup);

      const form = makeFormMock('NewGroup');
      vi.mocked(useForm).mockReturnValue(form);

      const onClose = vi.fn();
      renderForm({ channelGroup: null, onClose });

      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));

      await waitFor(() => {
        expect(onClose).toHaveBeenCalledWith(newGroup);
      });
    });

    it('resets the form after successful add', async () => {
      setupMocks();
      vi.mocked(API.addChannelGroup).mockResolvedValue({
        id: 99,
        name: 'NewGroup',
      });

      const form = makeFormMock('NewGroup');
      vi.mocked(useForm).mockReturnValue(form);

      renderForm({ channelGroup: null });

      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));

      await waitFor(() => {
        expect(form.reset).toHaveBeenCalled();
      });
    });
  });

  // ── Edit existing group ────────────────────────────────────────────────────

  describe('editing an existing group', () => {
    it('calls updateChannelGroup with the group id and form values on submit', async () => {
      setupMocks({ canEdit: true });
      const group = makeGroup({ id: 1, name: 'Sports' });
      const updated = { id: 1, name: 'Sports Updated' };
      vi.mocked(API.updateChannelGroup).mockResolvedValue(updated);

      const form = makeFormMock('Sports Updated');
      vi.mocked(useForm).mockReturnValue(form);

      const onClose = vi.fn();
      renderForm({ channelGroup: group, onClose });

      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));

      await waitFor(() => {
        expect(API.updateChannelGroup).toHaveBeenCalledWith({
          id: 1,
          name: 'Sports Updated',
        });
      });
    });

    it('calls onClose with the updated group', async () => {
      setupMocks({ canEdit: true });
      const group = makeGroup();
      const updated = { id: 1, name: 'Sports Updated' };
      vi.mocked(API.updateChannelGroup).mockResolvedValue(updated);

      const form = makeFormMock('Sports Updated');
      vi.mocked(useForm).mockReturnValue(form);

      const onClose = vi.fn();
      renderForm({ channelGroup: group, onClose });

      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));

      await waitFor(() => {
        expect(onClose).toHaveBeenCalledWith(updated);
      });
    });

    it('does not show the alert when group is editable', () => {
      setupMocks({ canEdit: true });
      vi.mocked(useForm).mockReturnValue(makeFormMock('Sports'));

      renderForm({ channelGroup: makeGroup() });

      expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
    });
  });

  // ── Non-editable group ─────────────────────────────────────────────────────

  describe('non-editable group (M3U associations)', () => {
    it('shows the alert warning when group cannot be edited', () => {
      setupMocks({ canEdit: false });
      vi.mocked(useForm).mockReturnValue(makeFormMock('Sports'));

      renderForm({ channelGroup: makeGroup() });

      expect(screen.getByTestId('alert')).toBeInTheDocument();
      expect(screen.getByTestId('alert')).toHaveTextContent(
        'This group cannot be edited because it has M3U account associations.'
      );
    });

    it('shows the alert with yellow color', () => {
      setupMocks({ canEdit: false });
      vi.mocked(useForm).mockReturnValue(makeFormMock('Sports'));

      renderForm({ channelGroup: makeGroup() });

      expect(screen.getByTestId('alert')).toHaveAttribute(
        'data-color',
        'yellow'
      );
    });

    it('disables the name input for non-editable group', () => {
      setupMocks({ canEdit: false });
      vi.mocked(useForm).mockReturnValue(makeFormMock('Sports'));

      renderForm({ channelGroup: makeGroup() });

      expect(screen.getByTestId('name-input')).toBeDisabled();
    });

    it('disables the submit button for non-editable group', () => {
      setupMocks({ canEdit: false });
      vi.mocked(useForm).mockReturnValue(makeFormMock('Sports'));

      renderForm({ channelGroup: makeGroup() });

      expect(screen.getByTestId('submit-button')).toBeDisabled();
    });

    it('shows error notification and does not call API on submit for non-editable group', async () => {
      setupMocks({ canEdit: false });
      vi.mocked(useForm).mockReturnValue(makeFormMock('Sports'));

      renderForm({ channelGroup: makeGroup() });

      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Error',
            message: 'Cannot edit group with M3U account associations',
            color: 'red',
          })
        );
      });

      expect(API.updateChannelGroup).not.toHaveBeenCalled();
      expect(API.addChannelGroup).not.toHaveBeenCalled();
    });

    it('does not call onClose when editing is blocked', async () => {
      setupMocks({ canEdit: false });
      vi.mocked(useForm).mockReturnValue(makeFormMock('Sports'));

      const onClose = vi.fn();
      renderForm({ channelGroup: makeGroup(), onClose });

      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalled();
      });

      expect(onClose).not.toHaveBeenCalled();
    });
  });

  // ── onClose passthrough ────────────────────────────────────────────────────

  describe('modal close', () => {
    it('calls onClose when the modal X button is clicked', () => {
      setupMocks();
      vi.mocked(useForm).mockReturnValue(makeFormMock(''));

      const onClose = vi.fn();
      renderForm({ onClose });

      fireEvent.click(screen.getByTestId('modal-close'));

      expect(onClose).toHaveBeenCalled();
    });
  });
});
