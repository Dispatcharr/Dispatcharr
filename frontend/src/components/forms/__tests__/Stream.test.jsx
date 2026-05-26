import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Module-level form state (survives re-renders, accessible in beforeEach) ───
const __form = { values: {}, resetSpy: null };

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/streamProfiles.jsx', () => ({ default: vi.fn() }));
vi.mock('../../../store/channels.jsx', () => ({ default: vi.fn() }));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/forms/StreamUtils.js', () => ({
  addStream: vi.fn(),
  getResolver: vi.fn(() => undefined),
  updateStream: vi.fn(),
}));

// ── react-hook-form ────────────────────────────────────────────────────────────
vi.mock('react-hook-form', async () => {
  const React = await import('react');
  return {
    useForm: vi.fn(({ defaultValues } = {}) => {
      const [formValues, setFormValues] = React.useState(() => {
        const vals = defaultValues || {};
        Object.assign(__form.values, vals);
        return vals;
      });

      const updateField = (name, value) => {
        __form.values[name] = value;
        setFormValues((prev) => ({ ...prev, [name]: value }));
      };

      const register = (name) => ({
        name,
        value: __form.values[name] ?? '',
        onChange: (e) => updateField(name, e.target.value),
        onBlur: () => {},
      });

      const setValue = (name, value) => updateField(name, value);

      const watch = (name) => formValues[name];

      const handleSubmit = (onSubmit) => (e) => {
        e?.preventDefault?.();
        return onSubmit({ ...__form.values });
      };

      // Keep reset stable across re-renders so useEffect([defaultValues, reset])
      // in Stream.jsx does not fire on every render and cause an infinite loop.
      const resetImpl = React.useCallback((newValues) => {
        const vals = newValues || defaultValues || {};
        Object.assign(__form.values, vals);
        setFormValues({ ...vals });
      }, []); // eslint-disable-line react-hooks/exhaustive-deps

      const resetRef = React.useRef(null);
      if (!resetRef.current) {
        resetRef.current = vi.fn((...args) => resetImpl(...args));
        __form.resetSpy = resetRef.current;
      }
      const reset = resetRef.current;

      return {
        register,
        handleSubmit,
        formState: { errors: {}, isSubmitting: false },
        reset,
        setValue,
        watch,
      };
    }),
  };
});

// ── @mantine/core ──────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Button: ({ children, type, disabled }) => (
    <button type={type} disabled={disabled}>
      {children}
    </button>
  ),
  Flex: ({ children }) => <div>{children}</div>,
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
  Select: ({ label, value, onChange, data, placeholder, error }) => (
    <div>
      <label>{label}</label>
      <select
        data-testid={`select-${label?.replace(/\s+/g, '-').toLowerCase()}`}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value || null)}
      >
        <option value="">{placeholder ?? `-- ${label} --`}</option>
        {(data ?? []).map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      {error && <span data-testid={`error-${label}`}>{error}</span>}
    </div>
  ),
  TextInput: ({ label, name, value, onChange, error, ...rest }) => (
    <div>
      <label htmlFor={name}>{label}</label>
      <input
        id={name}
        name={name}
        data-testid={`input-${label?.replace(/\s+/g, '-').toLowerCase()}`}
        value={value ?? ''}
        onChange={onChange}
        {...rest}
      />
      {error && <span data-testid={`error-${label}`}>{error}</span>}
    </div>
  ),
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import Stream from '../Stream';
import useStreamProfilesStore from '../../../store/streamProfiles.jsx';
import useChannelsStore from '../../../store/channels.jsx';
import * as StreamUtils from '../../../utils/forms/StreamUtils.js';

// ── Shared test data ───────────────────────────────────────────────────────────
const mockProfiles = [
  { id: 1, name: 'Default' },
  { id: 2, name: 'HD Profile' },
];

const mockChannelGroups = {
  10: { id: 10, name: 'Sports' },
  20: { id: 20, name: 'News' },
};

const makeStream = (overrides = {}) => ({
  id: 'stream-1',
  name: 'Test Stream',
  url: 'http://example.com/stream',
  channel_group: 10,
  stream_profile_id: 1,
  ...overrides,
});

const setupMocks = () => {
  vi.mocked(useStreamProfilesStore).mockImplementation((sel) =>
    sel({ profiles: mockProfiles })
  );
  vi.mocked(useChannelsStore).mockImplementation((sel) =>
    sel({ channelGroups: mockChannelGroups })
  );
  vi.mocked(StreamUtils.addStream).mockResolvedValue(undefined);
  vi.mocked(StreamUtils.updateStream).mockResolvedValue(undefined);
};

const defaultProps = (overrides = {}) => ({
  stream: null,
  isOpen: true,
  onClose: vi.fn(),
  ...overrides,
});

// ─────────────────────────────────────────────────────────────────────────────

describe('Stream', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset module-level form state before each test
    __form.values = {};
    setupMocks();
  });

  // ── Visibility ─────────────────────────────────────────────────────────────

  describe('visibility', () => {
    it('renders the modal when isOpen is true', () => {
      render(<Stream {...defaultProps()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('does not render when isOpen is false', () => {
      render(<Stream {...defaultProps({ isOpen: false })} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('renders "Stream" as the modal title', () => {
      render(<Stream {...defaultProps()} />);
      expect(screen.getByTestId('modal-title')).toHaveTextContent('Stream');
    });

    it('calls onClose when modal close button is clicked', () => {
      const onClose = vi.fn();
      render(<Stream {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
    });
  });

  // ── Form fields ────────────────────────────────────────────────────────────

  describe('form fields', () => {
    it('renders Stream Name input', () => {
      render(<Stream {...defaultProps()} />);
      expect(screen.getByTestId('input-stream-name')).toBeInTheDocument();
    });

    it('renders Stream URL input', () => {
      render(<Stream {...defaultProps()} />);
      expect(screen.getByTestId('input-stream-url')).toBeInTheDocument();
    });

    it('renders Group select', () => {
      render(<Stream {...defaultProps()} />);
      expect(screen.getByTestId('select-group')).toBeInTheDocument();
    });

    it('renders Stream Profile select', () => {
      render(<Stream {...defaultProps()} />);
      expect(screen.getByTestId('select-stream-profile')).toBeInTheDocument();
    });

    it('renders Submit button', () => {
      render(<Stream {...defaultProps()} />);
      expect(screen.getByText('Submit')).toBeInTheDocument();
    });

    it('populates Group select with channel groups', () => {
      render(<Stream {...defaultProps()} />);
      expect(screen.getByText('Sports')).toBeInTheDocument();
      expect(screen.getByText('News')).toBeInTheDocument();
    });

    it('populates Stream Profile select with profiles', () => {
      render(<Stream {...defaultProps()} />);
      expect(screen.getByText('Default')).toBeInTheDocument();
      expect(screen.getByText('HD Profile')).toBeInTheDocument();
    });

    it('shows "Optional" placeholder for Stream Profile', () => {
      render(<Stream {...defaultProps()} />);
      expect(screen.getByText('Optional')).toBeInTheDocument();
    });
  });

  // ── Default values ─────────────────────────────────────────────────────────

  describe('default values', () => {
    it('pre-fills name from stream prop', () => {
      render(<Stream {...defaultProps({ stream: makeStream() })} />);
      expect(screen.getByTestId('input-stream-name')).toHaveValue('Test Stream');
    });

    it('pre-fills url from stream prop', () => {
      render(<Stream {...defaultProps({ stream: makeStream() })} />);
      expect(screen.getByTestId('input-stream-url')).toHaveValue(
        'http://example.com/stream'
      );
    });

    it('pre-selects group from stream prop', () => {
      render(<Stream {...defaultProps({ stream: makeStream() })} />);
      expect(screen.getByTestId('select-group')).toHaveValue('10');
    });

    it('pre-selects stream profile from stream prop', () => {
      render(<Stream {...defaultProps({ stream: makeStream() })} />);
      expect(screen.getByTestId('select-stream-profile')).toHaveValue('1');
    });

    it('renders empty name when no stream provided', () => {
      render(<Stream {...defaultProps()} />);
      expect(screen.getByTestId('input-stream-name')).toHaveValue('');
    });

    it('renders empty url when no stream provided', () => {
      render(<Stream {...defaultProps()} />);
      expect(screen.getByTestId('input-stream-url')).toHaveValue('');
    });

    it('renders empty group when stream has no channel_group', () => {
      render(
        <Stream {...defaultProps({ stream: makeStream({ channel_group: null }) })} />
      );
      expect(screen.getByTestId('select-group')).toHaveValue('');
    });

    it('renders empty profile when stream has no stream_profile_id', () => {
      render(
        <Stream
          {...defaultProps({ stream: makeStream({ stream_profile_id: null }) })}
        />
      );
      expect(screen.getByTestId('select-stream-profile')).toHaveValue('');
    });
  });

  // ── Create stream ──────────────────────────────────────────────────────────

  describe('create stream (no existing stream)', () => {
    it('calls addStream on submit when no stream id', async () => {
      render(<Stream {...defaultProps()} />);

      fireEvent.change(screen.getByTestId('input-stream-name'), {
        target: { value: 'New Stream' },
      });
      fireEvent.change(screen.getByTestId('input-stream-url'), {
        target: { value: 'http://new.stream/live' },
      });

      fireEvent.submit(screen.getByRole('button', { name: 'Submit' }).closest('form'));

      await waitFor(() => {
        expect(StreamUtils.addStream).toHaveBeenCalledWith(
          expect.objectContaining({
            name: 'New Stream',
            url: 'http://new.stream/live',
          })
        );
      });
    });

    it('does not call updateStream when creating', async () => {
      render(<Stream {...defaultProps()} />);

      fireEvent.change(screen.getByTestId('input-stream-name'), {
        target: { value: 'New Stream' },
      });
      fireEvent.change(screen.getByTestId('input-stream-url'), {
        target: { value: 'http://new.stream' },
      });

      fireEvent.submit(
        screen.getByRole('button', { name: 'Submit' }).closest('form')
      );

      await waitFor(() => {
        expect(StreamUtils.updateStream).not.toHaveBeenCalled();
      });
    });

    it('calls onClose after successful create', async () => {
      const onClose = vi.fn();
      render(<Stream {...defaultProps({ onClose })} />);

      fireEvent.change(screen.getByTestId('input-stream-name'), {
        target: { value: 'New Stream' },
      });
      fireEvent.change(screen.getByTestId('input-stream-url'), {
        target: { value: 'http://new.stream' },
      });

      fireEvent.submit(
        screen.getByRole('button', { name: 'Submit' }).closest('form')
      );

      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });

    it('converts channel_group string to integer in payload', async () => {
      render(<Stream {...defaultProps()} />);

      fireEvent.change(screen.getByTestId('input-stream-name'), {
        target: { value: 'S' },
      });
      fireEvent.change(screen.getByTestId('input-stream-url'), {
        target: { value: 'http://x.com' },
      });
      fireEvent.change(screen.getByTestId('select-group'), {
        target: { value: '10' },
      });

      fireEvent.submit(
        screen.getByRole('button', { name: 'Submit' }).closest('form')
      );

      await waitFor(() => {
        expect(StreamUtils.addStream).toHaveBeenCalledWith(
          expect.objectContaining({ channel_group: 10 })
        );
      });
    });

    it('sets channel_group to null when no group selected', async () => {
      render(<Stream {...defaultProps()} />);

      fireEvent.change(screen.getByTestId('input-stream-name'), {
        target: { value: 'S' },
      });
      fireEvent.change(screen.getByTestId('input-stream-url'), {
        target: { value: 'http://x.com' },
      });

      fireEvent.submit(
        screen.getByRole('button', { name: 'Submit' }).closest('form')
      );

      await waitFor(() => {
        const call = vi.mocked(StreamUtils.addStream).mock.calls[0][0];
        expect(call.channel_group).toBeNull();
      });
    });

    it('converts stream_profile_id string to integer in payload', async () => {
      render(<Stream {...defaultProps()} />);

      fireEvent.change(screen.getByTestId('input-stream-name'), {
        target: { value: 'S' },
      });
      fireEvent.change(screen.getByTestId('input-stream-url'), {
        target: { value: 'http://x.com' },
      });
      fireEvent.change(screen.getByTestId('select-stream-profile'), {
        target: { value: '2' },
      });

      fireEvent.submit(
        screen.getByRole('button', { name: 'Submit' }).closest('form')
      );

      await waitFor(() => {
        expect(StreamUtils.addStream).toHaveBeenCalledWith(
          expect.objectContaining({ stream_profile_id: 2 })
        );
      });
    });

    it('sets stream_profile_id to null when no profile selected', async () => {
      render(<Stream {...defaultProps()} />);

      fireEvent.change(screen.getByTestId('input-stream-name'), {
        target: { value: 'S' },
      });
      fireEvent.change(screen.getByTestId('input-stream-url'), {
        target: { value: 'http://x.com' },
      });

      fireEvent.submit(
        screen.getByRole('button', { name: 'Submit' }).closest('form')
      );

      await waitFor(() => {
        const call = vi.mocked(StreamUtils.addStream).mock.calls[0][0];
        expect(call.stream_profile_id).toBeNull();
      });
    });
  });

  // ── Update stream ──────────────────────────────────────────────────────────

  describe('update stream (existing stream)', () => {
    it('calls updateStream with the stream id on submit', async () => {
      render(<Stream {...defaultProps({ stream: makeStream() })} />);

      fireEvent.submit(
        screen.getByRole('button', { name: 'Submit' }).closest('form')
      );

      await waitFor(() => {
        expect(StreamUtils.updateStream).toHaveBeenCalledWith(
          'stream-1',
          expect.objectContaining({
            name: 'Test Stream',
            url: 'http://example.com/stream',
          })
        );
      });
    });

    it('does not call addStream when updating', async () => {
      render(<Stream {...defaultProps({ stream: makeStream() })} />);

      fireEvent.submit(
        screen.getByRole('button', { name: 'Submit' }).closest('form')
      );

      await waitFor(() => {
        expect(StreamUtils.addStream).not.toHaveBeenCalled();
      });
    });

    it('calls onClose after successful update', async () => {
      const onClose = vi.fn();
      render(<Stream {...defaultProps({ stream: makeStream(), onClose })} />);

      fireEvent.submit(
        screen.getByRole('button', { name: 'Submit' }).closest('form')
      );

      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });

    it('converts channel_group back to integer for update payload', async () => {
      render(<Stream {...defaultProps({ stream: makeStream() })} />);

      fireEvent.submit(
        screen.getByRole('button', { name: 'Submit' }).closest('form')
      );

      await waitFor(() => {
        expect(StreamUtils.updateStream).toHaveBeenCalledWith(
          'stream-1',
          expect.objectContaining({ channel_group: 10 })
        );
      });
    });

    it('converts stream_profile_id back to integer for update payload', async () => {
      render(<Stream {...defaultProps({ stream: makeStream() })} />);

      fireEvent.submit(
        screen.getByRole('button', { name: 'Submit' }).closest('form')
      );

      await waitFor(() => {
        expect(StreamUtils.updateStream).toHaveBeenCalledWith(
          'stream-1',
          expect.objectContaining({ stream_profile_id: 1 })
        );
      });
    });
  });

  // ── getResolver ────────────────────────────────────────────────────────────

  describe('getResolver', () => {
    it('calls getResolver on mount', () => {
      render(<Stream {...defaultProps()} />);
      expect(StreamUtils.getResolver).toHaveBeenCalled();
    });
  });

  // ── Form reset on stream change ────────────────────────────────────────────

  describe('form reset', () => {
    it('resets the form when stream prop changes', () => {
      const { rerender } = render(<Stream {...defaultProps()} />);

      rerender(<Stream {...defaultProps({ stream: makeStream() })} />);

      expect(__form.resetSpy).toHaveBeenCalled();
    });
  });

  // ── Submit button state ────────────────────────────────────────────────────

  describe('submit button', () => {
    it('Submit button is not disabled by default', () => {
      render(<Stream {...defaultProps()} />);
      expect(screen.getByText('Submit')).not.toBeDisabled();
    });
  });
});
