import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Module-level form state ────────────────────────────────────────────────────
const __form = { values: {}, resetSpy: null };

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/forms/ServerGroupUtils', () => ({
  addServerGroup: vi.fn(),
  updateServerGroup: vi.fn(),
  getResolver: vi.fn(() => undefined),
}));

// ── react-hook-form ────────────────────────────────────────────────────────────
vi.mock('react-hook-form', async () => {
  const React = await import('react');
  return {
    useForm: vi.fn(({ defaultValues } = {}) => {
      const [_formValues, setFormValues] = React.useState(() => {
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
  TextInput: ({
    label,
    name,
    value,
    onChange,
    error,
    description,
    ...rest
  }) => (
    <div>
      <label htmlFor={name}>{label}</label>
      {description && <div>{description}</div>}
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
import ServerGroupForm from '../ServerGroup';
import * as ServerGroupUtils from '../../../utils/forms/ServerGroupUtils';

// ── Shared helpers ─────────────────────────────────────────────────────────────
const makeServerGroup = (overrides = {}) => ({
  id: 1,
  name: 'US East',
  ...overrides,
});

const defaultProps = (overrides = {}) => ({
  serverGroup: null,
  isOpen: true,
  onClose: vi.fn(),
  onSaved: vi.fn(),
  ...overrides,
});

// ──────────────────────────────────────────────────────────────────────────────

describe('ServerGroupForm', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    __form.values = {};
    __form.resetSpy = null;
    vi.mocked(ServerGroupUtils.addServerGroup).mockResolvedValue({
      id: 2,
      name: 'New Group',
    });
    vi.mocked(ServerGroupUtils.updateServerGroup).mockResolvedValue({
      id: 1,
      name: 'Updated',
    });
    vi.mocked(ServerGroupUtils.getResolver).mockReturnValue(undefined);
  });

  // ── Visibility ─────────────────────────────────────────────────────────────

  describe('visibility', () => {
    it('renders the form when isOpen is true', () => {
      render(<ServerGroupForm {...defaultProps()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('renders nothing when isOpen is false', () => {
      render(<ServerGroupForm {...defaultProps({ isOpen: false })} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('renders "Server Group" as the modal title', () => {
      render(<ServerGroupForm {...defaultProps()} />);
      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'Server Group'
      );
    });

    it('calls onClose when the modal close button is clicked', () => {
      const onClose = vi.fn();
      render(<ServerGroupForm {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
    });
  });

  // ── Form fields ────────────────────────────────────────────────────────────

  describe('form fields', () => {
    it('renders the Name input', () => {
      render(<ServerGroupForm {...defaultProps()} />);
      expect(screen.getByTestId('input-name')).toBeInTheDocument();
    });

    it('renders the Submit button', () => {
      render(<ServerGroupForm {...defaultProps()} />);
      expect(screen.getByText('Submit')).toBeInTheDocument();
    });
  });

  // ── Default values ─────────────────────────────────────────────────────────

  describe('default values', () => {
    it('name input is empty when no serverGroup is provided', () => {
      render(<ServerGroupForm {...defaultProps()} />);
      expect(screen.getByTestId('input-name')).toHaveValue('');
    });

    it('pre-fills the name from the serverGroup prop', () => {
      render(
        <ServerGroupForm
          {...defaultProps({
            serverGroup: makeServerGroup({ name: 'EU West' }),
          })}
        />
      );
      expect(screen.getByTestId('input-name')).toHaveValue('EU West');
    });
  });

  // ── Create (no id) ─────────────────────────────────────────────────────────

  describe('create (no serverGroup.id)', () => {
    it('calls addServerGroup with the form values', async () => {
      render(<ServerGroupForm {...defaultProps()} />);
      fireEvent.change(screen.getByTestId('input-name'), {
        target: { value: 'New Group' },
      });
      fireEvent.click(screen.getByText('Submit'));
      await waitFor(() => {
        expect(ServerGroupUtils.addServerGroup).toHaveBeenCalledWith(
          expect.objectContaining({ name: 'New Group' })
        );
      });
    });

    it('does not call updateServerGroup when creating', async () => {
      render(<ServerGroupForm {...defaultProps()} />);
      fireEvent.click(screen.getByText('Submit'));
      await waitFor(() => {
        expect(ServerGroupUtils.addServerGroup).toHaveBeenCalled();
      });
      expect(ServerGroupUtils.updateServerGroup).not.toHaveBeenCalled();
    });

    it('calls onSaved with the API response when response is truthy', async () => {
      const onSaved = vi.fn();
      const response = { id: 5, name: 'New Group' };
      vi.mocked(ServerGroupUtils.addServerGroup).mockResolvedValue(response);
      render(<ServerGroupForm {...defaultProps({ onSaved })} />);
      fireEvent.click(screen.getByText('Submit'));
      await waitFor(() => {
        expect(onSaved).toHaveBeenCalledWith(response);
      });
    });

    it('does not call onSaved when addServerGroup returns null', async () => {
      vi.mocked(ServerGroupUtils.addServerGroup).mockResolvedValue(null);
      const onSaved = vi.fn();
      render(<ServerGroupForm {...defaultProps({ onSaved })} />);
      fireEvent.click(screen.getByText('Submit'));
      await waitFor(() => {
        expect(ServerGroupUtils.addServerGroup).toHaveBeenCalled();
      });
      expect(onSaved).not.toHaveBeenCalled();
    });

    it('calls onClose after submission regardless of response', async () => {
      const onClose = vi.fn();
      render(<ServerGroupForm {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByText('Submit'));
      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });

    it('calls reset after submission', async () => {
      render(<ServerGroupForm {...defaultProps()} />);
      fireEvent.click(screen.getByText('Submit'));
      await waitFor(() => {
        expect(__form.resetSpy).toHaveBeenCalled();
      });
    });
  });

  // ── Update (with id) ───────────────────────────────────────────────────────

  describe('update (serverGroup with id)', () => {
    it('calls updateServerGroup with id and form values', async () => {
      render(
        <ServerGroupForm
          {...defaultProps({
            serverGroup: makeServerGroup({ id: 7, name: 'Old Name' }),
          })}
        />
      );
      fireEvent.change(screen.getByTestId('input-name'), {
        target: { value: 'New Name' },
      });
      fireEvent.click(screen.getByText('Submit'));
      await waitFor(() => {
        expect(ServerGroupUtils.updateServerGroup).toHaveBeenCalledWith(
          expect.objectContaining({ id: 7, name: 'New Name' })
        );
      });
    });

    it('does not call addServerGroup when updating', async () => {
      render(
        <ServerGroupForm
          {...defaultProps({ serverGroup: makeServerGroup() })}
        />
      );
      fireEvent.click(screen.getByText('Submit'));
      await waitFor(() => {
        expect(ServerGroupUtils.updateServerGroup).toHaveBeenCalled();
      });
      expect(ServerGroupUtils.addServerGroup).not.toHaveBeenCalled();
    });

    it('calls onSaved with the updated response', async () => {
      const updated = { id: 1, name: 'Updated Name' };
      vi.mocked(ServerGroupUtils.updateServerGroup).mockResolvedValue(updated);
      const onSaved = vi.fn();
      render(
        <ServerGroupForm
          {...defaultProps({ serverGroup: makeServerGroup(), onSaved })}
        />
      );
      fireEvent.click(screen.getByText('Submit'));
      await waitFor(() => {
        expect(onSaved).toHaveBeenCalledWith(updated);
      });
    });

    it('does not call onSaved when updateServerGroup returns null', async () => {
      vi.mocked(ServerGroupUtils.updateServerGroup).mockResolvedValue(null);
      const onSaved = vi.fn();
      render(
        <ServerGroupForm
          {...defaultProps({ serverGroup: makeServerGroup(), onSaved })}
        />
      );
      fireEvent.click(screen.getByText('Submit'));
      await waitFor(() => {
        expect(ServerGroupUtils.updateServerGroup).toHaveBeenCalled();
      });
      expect(onSaved).not.toHaveBeenCalled();
    });

    it('calls onClose after update regardless of response', async () => {
      const onClose = vi.fn();
      render(
        <ServerGroupForm
          {...defaultProps({ serverGroup: makeServerGroup(), onClose })}
        />
      );
      fireEvent.click(screen.getByText('Submit'));
      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });
  });

  // ── onSaved optional ───────────────────────────────────────────────────────

  describe('onSaved optional', () => {
    it('does not throw when onSaved is not provided and response is truthy', async () => {
      render(<ServerGroupForm isOpen={true} onClose={vi.fn()} />);
      fireEvent.click(screen.getByText('Submit'));
      await expect(
        waitFor(() =>
          expect(ServerGroupUtils.addServerGroup).toHaveBeenCalled()
        )
      ).resolves.not.toThrow();
    });
  });
});
