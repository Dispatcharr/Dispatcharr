import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Module-level form state ────────────────────────────────────────────────────
const __form = { values: {}, resetSpy: null };

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/forms/OutputProfileUtils', () => ({
  BUILT_IN_COMMANDS: [
    { value: 'ffmpeg', label: 'FFmpeg' },
    { value: '__custom__', label: 'Custom…' },
  ],
  COMMAND_EXAMPLES: {
    ffmpeg: '-i pipe:0 -c:v libx264 -f mpegts pipe:1',
  },
  addOutputProfile: vi.fn(),
  updateOutputProfile: vi.fn(),
  getResolver: vi.fn(() => undefined),
  toCommandSelection: vi.fn((cmd) =>
    cmd === 'ffmpeg' ? 'ffmpeg' : '__custom__'
  ),
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
        onChange={(e) =>
          onChange({ currentTarget: { checked: e.target.checked } })
        }
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
  Select: ({ label, value, onChange, data, disabled }) => (
    <div>
      <label>{label}</label>
      <select
        data-testid={`select-${label?.replace(/\s+/g, '-').toLowerCase()}`}
        value={value ?? ''}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        {(data ?? []).map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  ),
  Stack: ({ children }) => <div>{children}</div>,
  Textarea: ({
    label,
    name,
    value,
    onChange,
    placeholder,
    description,
    disabled,
    ...rest
  }) => (
    <div>
      <label htmlFor={name}>{label}</label>
      {description && (
        <div data-testid={`desc-${label?.replace(/\s+/g, '-').toLowerCase()}`}>
          {description}
        </div>
      )}
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
import OutputProfile from '../OutputProfile';
import * as OutputProfileUtils from '../../../utils/forms/OutputProfileUtils';

// ── Shared helpers ─────────────────────────────────────────────────────────────
const makeProfile = (overrides = {}) => ({
  id: 1,
  name: 'HD Transcode',
  command: 'ffmpeg',
  parameters: '-i pipe:0 -c:v copy -f mpegts pipe:1',
  is_active: true,
  locked: false,
  ...overrides,
});

const defaultProps = (overrides = {}) => ({
  profile: null,
  isOpen: true,
  onClose: vi.fn(),
  ...overrides,
});

// ──────────────────────────────────────────────────────────────────────────────

describe('OutputProfile', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    __form.values = {};
    __form.resetSpy = null;
    vi.mocked(OutputProfileUtils.addOutputProfile).mockResolvedValue(undefined);
    vi.mocked(OutputProfileUtils.updateOutputProfile).mockResolvedValue(
      undefined
    );
    vi.mocked(OutputProfileUtils.getResolver).mockReturnValue(undefined);
    vi.mocked(OutputProfileUtils.toCommandSelection).mockImplementation(
      (cmd) => (cmd === 'ffmpeg' ? 'ffmpeg' : '__custom__')
    );
  });

  // ── Visibility ─────────────────────────────────────────────────────────────

  describe('visibility', () => {
    it('renders the modal when isOpen is true', () => {
      render(<OutputProfile {...defaultProps()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('does not render the modal when isOpen is false', () => {
      render(<OutputProfile {...defaultProps({ isOpen: false })} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('renders "Output Profile" as the modal title', () => {
      render(<OutputProfile {...defaultProps()} />);
      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'Output Profile'
      );
    });

    it('calls onClose when the modal close button is clicked', () => {
      const onClose = vi.fn();
      render(<OutputProfile {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
    });
  });

  // ── Form fields ────────────────────────────────────────────────────────────

  describe('form fields', () => {
    it('renders the Name input', () => {
      render(<OutputProfile {...defaultProps()} />);
      expect(screen.getByTestId('input-name')).toBeInTheDocument();
    });

    it('renders the Command select', () => {
      render(<OutputProfile {...defaultProps()} />);
      expect(screen.getByTestId('select-command')).toBeInTheDocument();
    });

    it('renders the Parameters textarea', () => {
      render(<OutputProfile {...defaultProps()} />);
      expect(screen.getByTestId('textarea-parameters')).toBeInTheDocument();
    });

    it('renders the Is Active checkbox', () => {
      render(<OutputProfile {...defaultProps()} />);
      expect(screen.getByTestId('checkbox-is-active')).toBeInTheDocument();
    });

    it('renders the Save button', () => {
      render(<OutputProfile {...defaultProps()} />);
      expect(screen.getByText('Save')).toBeInTheDocument();
    });

    it('populates the Command select with built-in options', () => {
      render(<OutputProfile {...defaultProps()} />);
      expect(screen.getByText('FFmpeg')).toBeInTheDocument();
      expect(screen.getAllByText('Custom…').length).toBeGreaterThan(0);
    });

    it('does not show Custom Command input when a built-in is selected', () => {
      render(<OutputProfile {...defaultProps()} />);
      expect(
        screen.queryByTestId('input-custom-command')
      ).not.toBeInTheDocument();
    });
  });

  // ── Default values ─────────────────────────────────────────────────────────

  describe('default values', () => {
    it('name field is empty for a new profile', () => {
      render(<OutputProfile {...defaultProps()} />);
      expect(screen.getByTestId('input-name')).toHaveValue('');
    });

    it('command select defaults to ffmpeg', () => {
      render(<OutputProfile {...defaultProps()} />);
      expect(screen.getByTestId('select-command')).toHaveValue('ffmpeg');
    });

    it('is_active checkbox is checked by default', () => {
      render(<OutputProfile {...defaultProps()} />);
      expect(screen.getByTestId('checkbox-is-active')).toBeChecked();
    });

    it('parameters field is empty for a new profile', () => {
      render(<OutputProfile {...defaultProps()} />);
      expect(screen.getByTestId('textarea-parameters')).toHaveValue('');
    });
  });

  // ── Profile pre-fill ───────────────────────────────────────────────────────

  describe('profile pre-fill', () => {
    it('pre-fills the name from the profile', () => {
      render(<OutputProfile {...defaultProps({ profile: makeProfile() })} />);
      expect(screen.getByTestId('input-name')).toHaveValue('HD Transcode');
    });

    it('pre-fills the parameters from the profile', () => {
      render(<OutputProfile {...defaultProps({ profile: makeProfile() })} />);
      expect(screen.getByTestId('textarea-parameters')).toHaveValue(
        '-i pipe:0 -c:v copy -f mpegts pipe:1'
      );
    });

    it('pre-selects the command from the profile', () => {
      render(<OutputProfile {...defaultProps({ profile: makeProfile() })} />);
      expect(screen.getByTestId('select-command')).toHaveValue('ffmpeg');
    });

    it('is_active checkbox is unchecked when profile has is_active: false', () => {
      render(
        <OutputProfile
          {...defaultProps({ profile: makeProfile({ is_active: false }) })}
        />
      );
      expect(screen.getByTestId('checkbox-is-active')).not.toBeChecked();
    });

    it('shows Custom Command input when profile has a custom command', () => {
      vi.mocked(OutputProfileUtils.toCommandSelection).mockReturnValue(
        '__custom__'
      );
      render(
        <OutputProfile
          {...defaultProps({
            profile: makeProfile({ command: '/usr/bin/mycmd' }),
          })}
        />
      );
      expect(screen.getByTestId('input-custom-command')).toBeInTheDocument();
    });
  });

  // ── Locked profile ─────────────────────────────────────────────────────────

  describe('locked profile', () => {
    it('disables the Name input when profile is locked', () => {
      render(
        <OutputProfile
          {...defaultProps({ profile: makeProfile({ locked: true }) })}
        />
      );
      expect(screen.getByTestId('input-name')).toBeDisabled();
    });

    it('disables the Command select when profile is locked', () => {
      render(
        <OutputProfile
          {...defaultProps({ profile: makeProfile({ locked: true }) })}
        />
      );
      expect(screen.getByTestId('select-command')).toBeDisabled();
    });

    it('disables the Parameters textarea when profile is locked', () => {
      render(
        <OutputProfile
          {...defaultProps({ profile: makeProfile({ locked: true }) })}
        />
      );
      expect(screen.getByTestId('textarea-parameters')).toBeDisabled();
    });

    it('does not disable inputs when profile is not locked', () => {
      render(
        <OutputProfile
          {...defaultProps({ profile: makeProfile({ locked: false }) })}
        />
      );
      expect(screen.getByTestId('input-name')).not.toBeDisabled();
      expect(screen.getByTestId('select-command')).not.toBeDisabled();
      expect(screen.getByTestId('textarea-parameters')).not.toBeDisabled();
    });
  });

  // ── Command selection ──────────────────────────────────────────────────────

  describe('command selection', () => {
    it('shows Custom Command input when Custom… is selected', () => {
      render(<OutputProfile {...defaultProps()} />);
      fireEvent.change(screen.getByTestId('select-command'), {
        target: { value: '__custom__' },
      });
      expect(screen.getByTestId('input-custom-command')).toBeInTheDocument();
    });

    it('hides Custom Command input when switching back to a built-in', () => {
      render(<OutputProfile {...defaultProps()} />);
      fireEvent.change(screen.getByTestId('select-command'), {
        target: { value: '__custom__' },
      });
      fireEvent.change(screen.getByTestId('select-command'), {
        target: { value: 'ffmpeg' },
      });
      expect(
        screen.queryByTestId('input-custom-command')
      ).not.toBeInTheDocument();
    });

    it('sets command form value when switching to a built-in', () => {
      render(<OutputProfile {...defaultProps()} />);
      fireEvent.change(screen.getByTestId('select-command'), {
        target: { value: 'ffmpeg' },
      });
      expect(__form.values.command).toBe('ffmpeg');
    });

    it('clears command form value when Custom… is selected', () => {
      render(<OutputProfile {...defaultProps({ profile: makeProfile() })} />);
      fireEvent.change(screen.getByTestId('select-command'), {
        target: { value: '__custom__' },
      });
      expect(__form.values.command).toBe('');
    });

    it('shows parameters example in the description for ffmpeg', () => {
      const { container } = render(
        <OutputProfile {...defaultProps({ profile: makeProfile() })} />
      );
      expect(container.textContent).toMatch(/-i pipe:0/);
    });
  });

  // ── Is Active checkbox ─────────────────────────────────────────────────────

  describe('Is Active checkbox', () => {
    it('toggles is_active to false when unchecked', () => {
      render(<OutputProfile {...defaultProps({ profile: makeProfile() })} />);
      fireEvent.click(screen.getByTestId('checkbox-is-active'));
      expect(__form.values.is_active).toBe(false);
    });

    it('toggles is_active to true when checked', () => {
      render(
        <OutputProfile
          {...defaultProps({ profile: makeProfile({ is_active: false }) })}
        />
      );
      fireEvent.click(screen.getByTestId('checkbox-is-active'));
      expect(__form.values.is_active).toBe(true);
    });
  });

  // ── Form submission ────────────────────────────────────────────────────────

  describe('form submission', () => {
    it('calls addOutputProfile when submitting a new profile', async () => {
      render(<OutputProfile {...defaultProps()} />);
      fireEvent.change(screen.getByTestId('input-name'), {
        target: { value: 'New Profile' },
      });
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => {
        expect(OutputProfileUtils.addOutputProfile).toHaveBeenCalledWith(
          expect.objectContaining({ name: 'New Profile', command: 'ffmpeg' })
        );
      });
    });

    it('does not call updateOutputProfile for a new profile', async () => {
      render(<OutputProfile {...defaultProps()} />);
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => {
        expect(OutputProfileUtils.addOutputProfile).toHaveBeenCalled();
      });
      expect(OutputProfileUtils.updateOutputProfile).not.toHaveBeenCalled();
    });

    it('calls updateOutputProfile when submitting an existing profile', async () => {
      render(<OutputProfile {...defaultProps({ profile: makeProfile() })} />);
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => {
        expect(OutputProfileUtils.updateOutputProfile).toHaveBeenCalledWith(
          expect.objectContaining({ id: 1, name: 'HD Transcode' })
        );
      });
    });

    it('does not call addOutputProfile for an existing profile', async () => {
      render(<OutputProfile {...defaultProps({ profile: makeProfile() })} />);
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => {
        expect(OutputProfileUtils.updateOutputProfile).toHaveBeenCalled();
      });
      expect(OutputProfileUtils.addOutputProfile).not.toHaveBeenCalled();
    });

    it('calls onClose after successful submission', async () => {
      const onClose = vi.fn();
      render(<OutputProfile {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });

    it('calls reset after successful submission', async () => {
      render(<OutputProfile {...defaultProps()} />);
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => {
        expect(__form.resetSpy).toHaveBeenCalled();
      });
    });

    it('passes is_active value to addOutputProfile', async () => {
      render(<OutputProfile {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('checkbox-is-active')); // uncheck → false
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => {
        expect(OutputProfileUtils.addOutputProfile).toHaveBeenCalledWith(
          expect.objectContaining({ is_active: false })
        );
      });
    });
  });
});
