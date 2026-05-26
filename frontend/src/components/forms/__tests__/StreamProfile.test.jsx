import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Module-level form state ────────────────────────────────────────────────────
const __form = { values: {}, resetSpy: null };

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/userAgents', () => ({ default: vi.fn() }));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/forms/StreamProfileUtils.js', () => ({
  addStreamProfile: vi.fn(),
  updateStreamProfile: vi.fn(),
  getResolver: vi.fn(() => undefined),
  toCommandSelection: vi.fn((cmd) => {
    const builtins = ['ffmpeg', 'streamlink', 'cvlc', 'yt-dlp'];
    return builtins.includes(cmd) ? cmd : '__custom__';
  }),
  BUILT_IN_COMMANDS: [
    { value: 'ffmpeg', label: 'FFmpeg' },
    { value: 'streamlink', label: 'Streamlink' },
    { value: 'cvlc', label: 'VLC' },
    { value: 'yt-dlp', label: 'yt-dlp' },
    { value: '__custom__', label: 'Custom…' },
  ],
  COMMAND_EXAMPLES: {
    ffmpeg: '-user_agent {userAgent} -i {streamUrl} -c copy -f mpegts pipe:1',
    streamlink: '{streamUrl} --http-header User-Agent={userAgent} best --stdout',
  },
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

      return {
        register,
        handleSubmit,
        formState: { errors: {}, isSubmitting: false },
        reset: resetRef.current,
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
  Checkbox: ({ label, checked, onChange }) => (
    <div>
      <label htmlFor="checkbox-is-active">{label}</label>
      <input
        id="checkbox-is-active"
        data-testid="checkbox-is-active"
        type="checkbox"
        checked={checked ?? false}
        onChange={(e) => onChange({ currentTarget: { checked: e.target.checked } })}
      />
    </div>
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
  Select: ({ label, value, onChange, data, placeholder, error, clearable, disabled, description }) => (
    <div>
      <label>{label}</label>
      {description && <div>{description}</div>}
      <select
        data-testid={`select-${label?.replace(/\s+/g, '-').toLowerCase()}`}
        value={value ?? ''}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value || (clearable ? null : ''))}
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
  Stack: ({ children }) => <div>{children}</div>,
  Textarea: ({ label, name, value, onChange, error, placeholder, description, disabled, ...rest }) => (
    <div>
      <label htmlFor={name}>{label}</label>
      {description && <div data-testid={`desc-${label?.replace(/\s+/g, '-').toLowerCase()}`}>{description}</div>}
      <textarea
        id={name}
        name={name}
        data-testid={`textarea-${label?.replace(/\s+/g, '-').toLowerCase()}`}
        value={value ?? ''}
        placeholder={placeholder}
        onChange={onChange}
        disabled={disabled}
        {...rest}
      />
      {error && <span data-testid={`error-${label}`}>{error}</span>}
    </div>
  ),
  TextInput: ({ label, name, value, onChange, error, disabled, ...rest }) => (
    <div>
      <label htmlFor={name}>{label}</label>
      <input
        id={name}
        name={name}
        data-testid={`input-${label?.replace(/\s+/g, '-').toLowerCase()}`}
        value={value ?? ''}
        onChange={onChange}
        disabled={disabled}
        {...rest}
      />
      {error && <span data-testid={`error-${label}`}>{error}</span>}
    </div>
  ),
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import StreamProfile from '../StreamProfile';
import useUserAgentsStore from '../../../store/userAgents';
import * as StreamProfileUtils from '../../../utils/forms/StreamProfileUtils.js';

// ── Shared test data ───────────────────────────────────────────────────────────
const mockUserAgents = [
  { id: 1, name: 'Chrome' },
  { id: 2, name: 'Firefox' },
];

const makeProfile = (overrides = {}) => ({
  id: 'sp-1',
  name: 'My Profile',
  command: 'ffmpeg',
  parameters: '-i {streamUrl}',
  is_active: true,
  user_agent: '1',
  locked: false,
  ...overrides,
});

const setupMocks = () => {
  vi.mocked(useUserAgentsStore).mockImplementation((sel) =>
    sel({ userAgents: mockUserAgents })
  );
  vi.mocked(StreamProfileUtils.addStreamProfile).mockResolvedValue(undefined);
  vi.mocked(StreamProfileUtils.updateStreamProfile).mockResolvedValue(undefined);
  vi.mocked(StreamProfileUtils.getResolver).mockReturnValue(undefined);
  vi.mocked(StreamProfileUtils.toCommandSelection).mockImplementation((cmd) => {
    const builtins = ['ffmpeg', 'streamlink', 'cvlc', 'yt-dlp'];
    return builtins.includes(cmd) ? cmd : '__custom__';
  });
};

const defaultProps = (overrides = {}) => ({
  profile: null,
  isOpen: true,
  onClose: vi.fn(),
  ...overrides,
});

describe('StreamProfile', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    __form.values = {};
    __form.resetSpy = null;
    setupMocks();
  });

  // ── Visibility ──────────────────────────────────────────────────────────────

  describe('visibility', () => {
    it('renders the modal when isOpen is true', () => {
      render(<StreamProfile {...defaultProps()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('does not render the modal when isOpen is false', () => {
      render(<StreamProfile {...defaultProps({ isOpen: false })} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('renders "Stream Profile" as the modal title', () => {
      render(<StreamProfile {...defaultProps()} />);
      expect(screen.getByTestId('modal-title')).toHaveTextContent('Stream Profile');
    });

    it('calls onClose when modal close button is clicked', () => {
      const onClose = vi.fn();
      render(<StreamProfile {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
    });
  });

  // ── Form fields ─────────────────────────────────────────────────────────────

  describe('form fields', () => {
    it('renders Name input', () => {
      render(<StreamProfile {...defaultProps()} />);
      expect(screen.getByTestId('input-name')).toBeInTheDocument();
    });

    it('renders Command select', () => {
      render(<StreamProfile {...defaultProps()} />);
      expect(screen.getByTestId('select-command')).toBeInTheDocument();
    });

    it('renders Parameters textarea', () => {
      render(<StreamProfile {...defaultProps()} />);
      expect(screen.getByTestId('textarea-parameters')).toBeInTheDocument();
    });

    it('renders User-Agent select', () => {
      render(<StreamProfile {...defaultProps()} />);
      expect(screen.getByTestId('select-user-agent')).toBeInTheDocument();
    });

    it('renders Is Active checkbox', () => {
      render(<StreamProfile {...defaultProps()} />);
      expect(screen.getByTestId('checkbox-is-active')).toBeInTheDocument();
    });

    it('renders Save button', () => {
      render(<StreamProfile {...defaultProps()} />);
      expect(screen.getByText('Save')).toBeInTheDocument();
    });

    it('populates Command select with built-in options', () => {
      render(<StreamProfile {...defaultProps()} />);
      expect(screen.getByText('FFmpeg')).toBeInTheDocument();
      expect(screen.getByText('Streamlink')).toBeInTheDocument();
      expect(screen.getAllByText('Custom…').length).toBeGreaterThan(0);
    });

    it('populates User-Agent select with user agents', () => {
      render(<StreamProfile {...defaultProps()} />);
      expect(screen.getByText('Chrome')).toBeInTheDocument();
      expect(screen.getByText('Firefox')).toBeInTheDocument();
    });
  });

  // ── Default values ──────────────────────────────────────────────────────────

  describe('default values', () => {
    it('pre-fills name from profile prop', () => {
      render(<StreamProfile {...defaultProps({ profile: makeProfile() })} />);
      expect(screen.getByTestId('input-name')).toHaveValue('My Profile');
    });

    it('pre-fills parameters from profile prop', () => {
      render(<StreamProfile {...defaultProps({ profile: makeProfile() })} />);
      expect(screen.getByTestId('textarea-parameters')).toHaveValue('-i {streamUrl}');
    });

    it('pre-selects command from profile prop', () => {
      render(<StreamProfile {...defaultProps({ profile: makeProfile() })} />);
      expect(screen.getByTestId('select-command')).toHaveValue('ffmpeg');
    });

    it('pre-selects user-agent from profile prop', () => {
      render(<StreamProfile {...defaultProps({ profile: makeProfile() })} />);
      expect(screen.getByTestId('select-user-agent')).toHaveValue('1');
    });

    it('checkbox is checked when is_active is true', () => {
      render(<StreamProfile {...defaultProps({ profile: makeProfile() })} />);
      expect(screen.getByTestId('checkbox-is-active')).toBeChecked();
    });

    it('checkbox is unchecked when is_active is false', () => {
      render(
        <StreamProfile
          {...defaultProps({ profile: makeProfile({ is_active: false }) })}
        />
      );
      expect(screen.getByTestId('checkbox-is-active')).not.toBeChecked();
    });

    it('defaults name to empty string when no profile', () => {
      render(<StreamProfile {...defaultProps()} />);
      expect(screen.getByTestId('input-name')).toHaveValue('');
    });

    it('defaults parameters to empty string when no profile', () => {
      render(<StreamProfile {...defaultProps()} />);
      expect(screen.getByTestId('textarea-parameters')).toHaveValue('');
    });
  });

  // ── Command selection ───────────────────────────────────────────────────────

  describe('command selection', () => {
    it('does not show Custom Command input when a built-in is selected', () => {
      render(<StreamProfile {...defaultProps({ profile: makeProfile() })} />);
      expect(screen.queryByTestId('input-custom-command')).not.toBeInTheDocument();
    });

    it('shows Custom Command input when Custom… is selected', () => {
      render(<StreamProfile {...defaultProps()} />);
      fireEvent.change(screen.getByTestId('select-command'), {
        target: { value: '__custom__' },
      });
      expect(screen.getByTestId('input-custom-command')).toBeInTheDocument();
    });

    it('hides Custom Command input when switching from custom back to built-in', () => {
      render(<StreamProfile {...defaultProps()} />);
      fireEvent.change(screen.getByTestId('select-command'), {
        target: { value: '__custom__' },
      });
      fireEvent.change(screen.getByTestId('select-command'), {
        target: { value: 'ffmpeg' },
      });
      expect(screen.queryByTestId('input-custom-command')).not.toBeInTheDocument();
    });

    it('shows Custom Command input when profile has a custom command', () => {
      vi.mocked(StreamProfileUtils.toCommandSelection).mockReturnValue('__custom__');
      render(
        <StreamProfile
          {...defaultProps({ profile: makeProfile({ command: '/usr/bin/mycmd' }) })}
        />
      );
      expect(screen.getByTestId('input-custom-command')).toBeInTheDocument();
    });

    it('sets command form value when built-in is selected', () => {
      render(<StreamProfile {...defaultProps()} />);
      fireEvent.change(screen.getByTestId('select-command'), {
        target: { value: 'streamlink' },
      });
      expect(__form.values.command).toBe('streamlink');
    });

    it('clears command form value when Custom… is selected', () => {
      render(<StreamProfile {...defaultProps({ profile: makeProfile() })} />);
      fireEvent.change(screen.getByTestId('select-command'), {
        target: { value: '__custom__' },
      });
      expect(__form.values.command).toBe('');
    });

    it('shows parameters example hint for ffmpeg', () => {
      const { container } = render(
        <StreamProfile {...defaultProps({ profile: makeProfile() })} />
      );
      expect(container.textContent).toMatch(/-user_agent \{userAgent\}/);
    });
  });

  // ── Is Active checkbox ──────────────────────────────────────────────────────

  describe('Is Active checkbox', () => {
    it('toggles is_active to false when unchecked', () => {
      render(<StreamProfile {...defaultProps({ profile: makeProfile() })} />);
      fireEvent.click(screen.getByTestId('checkbox-is-active'));
      expect(__form.values.is_active).toBe(false);
    });

    it('toggles is_active to true when checked', () => {
      render(
        <StreamProfile
          {...defaultProps({ profile: makeProfile({ is_active: false }) })}
        />
      );
      fireEvent.click(screen.getByTestId('checkbox-is-active'));
      expect(__form.values.is_active).toBe(true);
    });
  });

  // ── User-Agent select ───────────────────────────────────────────────────────

  describe('User-Agent select', () => {
    it('updates user_agent form value when changed', () => {
      render(<StreamProfile {...defaultProps()} />);
      fireEvent.change(screen.getByTestId('select-user-agent'), {
        target: { value: '2' },
      });
      expect(__form.values.user_agent).toBe('2');
    });

    it('sets user_agent to empty string when cleared', () => {
      render(<StreamProfile {...defaultProps({ profile: makeProfile() })} />);
      fireEvent.change(screen.getByTestId('select-user-agent'), {
        target: { value: '' },
      });
      expect(__form.values.user_agent).toBe('');
    });
  });

  // ── Locked profile ──────────────────────────────────────────────────────────

  describe('locked profile', () => {
    it('disables Name input when profile is locked', () => {
      render(
        <StreamProfile
          {...defaultProps({ profile: makeProfile({ locked: true }) })}
        />
      );
      expect(screen.getByTestId('input-name')).toBeDisabled();
    });

    it('disables Command select when profile is locked', () => {
      render(
        <StreamProfile
          {...defaultProps({ profile: makeProfile({ locked: true }) })}
        />
      );
      expect(screen.getByTestId('select-command')).toBeDisabled();
    });

    it('disables Parameters textarea when profile is locked', () => {
      render(
        <StreamProfile
          {...defaultProps({ profile: makeProfile({ locked: true }) })}
        />
      );
      expect(screen.getByTestId('textarea-parameters')).toBeDisabled();
    });

    it('does not disable inputs when profile is not locked', () => {
      render(<StreamProfile {...defaultProps({ profile: makeProfile() })} />);
      expect(screen.getByTestId('input-name')).not.toBeDisabled();
    });

    it('does not disable inputs when no profile is provided', () => {
      render(<StreamProfile {...defaultProps()} />);
      expect(screen.getByTestId('input-name')).not.toBeDisabled();
    });
  });

  // ── Create profile ──────────────────────────────────────────────────────────

  describe('create profile (no existing profile)', () => {
    it('calls addStreamProfile on submit when no profile id', async () => {
      render(<StreamProfile {...defaultProps()} />);

      fireEvent.change(screen.getByTestId('input-name'), {
        target: { value: 'New Profile' },
      });
      fireEvent.change(screen.getByTestId('select-command'), {
        target: { value: 'ffmpeg' },
      });

      fireEvent.submit(screen.getByText('Save').closest('form'));

      await waitFor(() => {
        expect(StreamProfileUtils.addStreamProfile).toHaveBeenCalledWith(
          expect.objectContaining({ name: 'New Profile' })
        );
      });
    });

    it('does not call updateStreamProfile when creating', async () => {
      render(<StreamProfile {...defaultProps()} />);

      fireEvent.change(screen.getByTestId('input-name'), {
        target: { value: 'New Profile' },
      });

      fireEvent.submit(screen.getByText('Save').closest('form'));

      await waitFor(() => {
        expect(StreamProfileUtils.updateStreamProfile).not.toHaveBeenCalled();
      });
    });

    it('calls onClose after successful create', async () => {
      const onClose = vi.fn();
      render(<StreamProfile {...defaultProps({ onClose })} />);

      fireEvent.change(screen.getByTestId('input-name'), {
        target: { value: 'New Profile' },
      });
      fireEvent.submit(screen.getByText('Save').closest('form'));

      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });
  });

  // ── Update profile ──────────────────────────────────────────────────────────

  describe('update profile (existing profile)', () => {
    it('calls updateStreamProfile with the profile id on submit', async () => {
      render(<StreamProfile {...defaultProps({ profile: makeProfile() })} />);

      fireEvent.submit(screen.getByText('Save').closest('form'));

      await waitFor(() => {
        expect(StreamProfileUtils.updateStreamProfile).toHaveBeenCalledWith(
          'sp-1',
          expect.objectContaining({ name: 'My Profile' })
        );
      });
    });

    it('does not call addStreamProfile when updating', async () => {
      render(<StreamProfile {...defaultProps({ profile: makeProfile() })} />);

      fireEvent.submit(screen.getByText('Save').closest('form'));

      await waitFor(() => {
        expect(StreamProfileUtils.addStreamProfile).not.toHaveBeenCalled();
      });
    });

    it('calls onClose after successful update', async () => {
      const onClose = vi.fn();
      render(
        <StreamProfile {...defaultProps({ profile: makeProfile(), onClose })} />
      );

      fireEvent.submit(screen.getByText('Save').closest('form'));

      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });
  });

  // ── Form reset ──────────────────────────────────────────────────────────────

  describe('form reset', () => {
    it('resets the form when profile prop changes', () => {
      const { rerender } = render(<StreamProfile {...defaultProps()} />);

      rerender(<StreamProfile {...defaultProps({ profile: makeProfile() })} />);

      expect(__form.resetSpy).toHaveBeenCalled();
    });

    it('calls reset after successful submit', async () => {
      render(<StreamProfile {...defaultProps()} />);

      fireEvent.submit(screen.getByText('Save').closest('form'));

      await waitFor(() => {
        expect(__form.resetSpy).toHaveBeenCalled();
      });
    });
  });

  // ── getResolver ─────────────────────────────────────────────────────────────

  describe('getResolver', () => {
    it('calls getResolver on mount', () => {
      render(<StreamProfile {...defaultProps()} />);
      expect(StreamProfileUtils.getResolver).toHaveBeenCalled();
    });
  });
});

