import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import M3UFilter from '../M3UFilter';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/playlists', () => ({ default: vi.fn() }));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/forms/M3uFilterUtils.js', () => ({
  addM3UFilter: vi.fn(),
  updateM3UFilter: vi.fn(),
}));

vi.mock('../../../utils', () => ({
  setCustomProperty: vi.fn((obj, key, value) => ({ ...obj, [key]: value })),
}));

// ── Constants mock ─────────────────────────────────────────────────────────────
vi.mock('../../../constants', () => ({
  M3U_FILTER_TYPES: [
    { value: 'include', label: 'Include' },
    { value: 'exclude', label: 'Exclude' },
  ],
}));

// ── Mantine form ───────────────────────────────────────────────────────────────
vi.mock('@mantine/form', () => {
  let _values = null;

  return {
    isNotEmpty: vi.fn(() => (val) => (val ? null : 'Required')),
    __resetFormState: () => {
      _values = null;
    },
    useForm: vi.fn(({ initialValues = {} } = {}) => {
      if (_values === null) {
        _values = { ...initialValues };
      }

      return {
        key: vi.fn((field) => field),
        getValues: () => ({ ..._values }),
        setValues: (v) => {
          Object.assign(_values, v);
        },
        setFieldValue: (field, val) => {
          _values[field] = val;
        },
        reset: () => {
          _values = { ...initialValues };
        },
        submitting: false,
        onSubmit: vi.fn((handler) => (e) => {
          e?.preventDefault?.();
          handler();
        }),
        getInputProps: vi.fn((field, options = {}) => {
          const isCheckbox = options?.type === 'checkbox';
          return {
            ...(isCheckbox
              ? { checked: !!_values?.[field] }
              : { value: _values?.[field] ?? '' }),
            onChange: vi.fn((e) => {
              const val = isCheckbox
                ? (e?.target?.checked ?? e)
                : (e?.target?.value ?? e);
              if (_values) _values[field] = val;
            }),
            error: null,
          };
        }),
      };
    }),
  };
});

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Box: ({ children }) => <div>{children}</div>,
  Button: ({ children, onClick, type, loading, disabled, variant, color }) => (
    <button
      type={type || 'button'}
      onClick={onClick}
      disabled={disabled || loading}
      data-variant={variant}
      data-color={color}
      data-loading={String(loading)}
    >
      {children}
    </button>
  ),
  Flex: ({ children }) => <div>{children}</div>,
  Group: ({ children }) => <div>{children}</div>,
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
  Select: ({ label, placeholder, value, onChange, data, error, disabled }) => (
    <div>
      <label>
        {label}
        <select
          aria-label={label}
          value={value ?? ''}
          onChange={(e) => onChange?.(e.target.value)}
          disabled={disabled}
        >
          <option value="">{placeholder}</option>
          {(data ?? []).map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </label>
      {error && <span data-testid="select-error">{error}</span>}
    </div>
  ),
  Stack: ({ children }) => <div>{children}</div>,
  Switch: ({ id, label, checked, onChange, disabled }) => (
    <label>
      <input
        data-testid={id}
        type="checkbox"
        aria-label={label}
        checked={!!checked}
        onChange={(e) => onChange?.(e)}
        disabled={disabled}
      />
      {label}
    </label>
  ),
  TextInput: ({
    label,
    placeholder,
    value,
    onChange,
    onBlur,
    error,
    disabled,
  }) => (
    <div>
      <label>
        {label}
        <input
          aria-label={label}
          placeholder={placeholder}
          value={value ?? ''}
          onChange={onChange}
          onBlur={onBlur}
          disabled={disabled}
        />
      </label>
      {error && <span data-testid="input-error">{error}</span>}
    </div>
  ),
}));

// ──────────────────────────────────────────────────────────────────────────────
// Imports after mocks
// ──────────────────────────────────────────────────────────────────────────────
import usePlaylistsStore from '../../../store/playlists';
import * as M3uFilterUtils from '../../../utils/forms/M3uFilterUtils.js';
import * as mantineForm from '@mantine/form';

// ── Helpers ────────────────────────────────────────────────────────────────────
const makeM3U = (overrides = {}) => ({
  id: 1,
  name: 'Test Playlist',
  custom_properties: {},
  filters: [],
  ...overrides,
});

const makeFilter = (overrides = {}) => ({
  id: 10,
  filter_type: 'include',
  regex_pattern: 'HBO.*',
  exclude: false,
  custom_properties: { case_sensitive: false },
  ...overrides,
});

const defaultProps = (overrides = {}) => ({
  filter: null,
  m3u: makeM3U(),
  isOpen: true,
  onClose: vi.fn(),
  ...overrides,
});

const setupStores = ({
  fetchPlaylist = vi.fn().mockResolvedValue(undefined),
} = {}) => {
  vi.mocked(usePlaylistsStore).mockImplementation((sel) =>
    sel({ fetchPlaylist })
  );
  return { fetchPlaylist };
};

// ──────────────────────────────────────────────────────────────────────────────

describe('M3UFilter', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mantineForm.__resetFormState();
    vi.mocked(M3uFilterUtils.addM3UFilter).mockResolvedValue({ id: 99 });
    vi.mocked(M3uFilterUtils.updateM3UFilter).mockResolvedValue({});
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the modal when isOpen is true', () => {
      setupStores();
      render(<M3UFilter {...defaultProps()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('does not render when isOpen is false', () => {
      setupStores();
      render(<M3UFilter {...defaultProps({ isOpen: false })} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('renders modal title as "Filter"', () => {
      setupStores();
      render(<M3UFilter {...defaultProps()} />);
      expect(screen.getByTestId('modal-title')).toHaveTextContent('Filter');
    });

    it('renders filter type Select', () => {
      setupStores();
      render(<M3UFilter {...defaultProps()} />);
      expect(screen.getByRole('combobox')).toBeInTheDocument();
    });

    it('renders filter type options from M3U_FILTER_TYPES', () => {
      setupStores();
      render(<M3UFilter {...defaultProps()} />);
      expect(
        screen.getByRole('option', { name: 'Include' })
      ).toBeInTheDocument();
      expect(
        screen.getByRole('option', { name: 'Exclude' })
      ).toBeInTheDocument();
    });

    it('renders a text input for the pattern', () => {
      setupStores();
      render(<M3UFilter {...defaultProps()} />);
      expect(screen.getByLabelText('Regex Pattern')).toBeInTheDocument();
    });

    it('renders the exclusion switch', () => {
      setupStores();
      render(<M3UFilter {...defaultProps()} />);
      expect(screen.getByTestId('exclude')).toBeInTheDocument();
    });

    it('renders the case sensitivity switch', () => {
      setupStores();
      render(<M3UFilter {...defaultProps()} />);
      expect(screen.getByTestId('case_sensitive')).toBeInTheDocument();
    });

    it('renders a submit button', () => {
      setupStores();
      render(<M3UFilter {...defaultProps()} />);
      expect(
        screen.getByRole('button', { name: /add|save|submit/i })
      ).toBeInTheDocument();
    });
  });

  // ── Form reset on open/filter change ──────────────────────────────────────

  describe('form reset behaviour', () => {
    it('shows empty pattern field for a new filter', () => {
      setupStores();
      render(<M3UFilter {...defaultProps({ filter: null })} />);
      expect(screen.getByRole('textbox')).toHaveValue('');
    });
  });

  // ── Cancel behaviour ───────────────────────────────────────────────────────

  describe('cancel behaviour', () => {
    it('calls onClose when modal X is clicked', () => {
      const onClose = vi.fn();
      setupStores();
      render(<M3UFilter {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
    });
  });

  // ── Adding a filter ────────────────────────────────────────────────────────

  describe('adding a new filter', () => {
    const fillForm = () => {
      fireEvent.change(screen.getByRole('combobox'), {
        target: { value: 'include' },
      });
      fireEvent.change(screen.getByRole('textbox'), {
        target: { value: 'Sports.*' },
      });
    };

    it('calls addM3UFilter on submit for a new filter', async () => {
      setupStores();
      render(<M3UFilter {...defaultProps({ filter: null })} />);
      fillForm();
      fireEvent.click(screen.getByRole('button', { name: /add|save|submit/i }));
      await waitFor(() => {
        expect(M3uFilterUtils.addM3UFilter).toHaveBeenCalled();
      });
    });

    it('does not call updateM3UFilter when adding', async () => {
      setupStores();
      render(<M3UFilter {...defaultProps({ filter: null })} />);
      fillForm();
      fireEvent.click(screen.getByRole('button', { name: /add|save|submit/i }));
      await waitFor(() => {
        expect(M3uFilterUtils.addM3UFilter).toHaveBeenCalled();
      });
      expect(M3uFilterUtils.updateM3UFilter).not.toHaveBeenCalled();
    });

    it('calls fetchPlaylist after successful add', async () => {
      const { fetchPlaylist } = setupStores();
      render(<M3UFilter {...defaultProps({ filter: null })} />);
      fillForm();
      fireEvent.click(screen.getByRole('button', { name: /add|save|submit/i }));
      await waitFor(() => {
        expect(fetchPlaylist).toHaveBeenCalledWith(makeM3U().id);
      });
    });

    it('calls onClose after successful add', async () => {
      const onClose = vi.fn();
      setupStores();
      render(<M3UFilter {...defaultProps({ filter: null, onClose })} />);
      fillForm();
      fireEvent.click(screen.getByRole('button', { name: /add|save|submit/i }));
      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });
  });

  // ── Updating a filter ──────────────────────────────────────────────────────

  describe('updating an existing filter', () => {
    it('calls updateM3UFilter on submit for an existing filter', async () => {
      setupStores();
      render(<M3UFilter {...defaultProps({ filter: makeFilter() })} />);
      fireEvent.click(
        screen.getByRole('button', { name: /add|save|update|submit/i })
      );
      await waitFor(() => {
        expect(M3uFilterUtils.updateM3UFilter).toHaveBeenCalled();
      });
    });

    it('does not call addM3UFilter when updating', async () => {
      setupStores();
      render(<M3UFilter {...defaultProps({ filter: makeFilter() })} />);
      fireEvent.click(
        screen.getByRole('button', { name: /add|save|update|submit/i })
      );
      await waitFor(() => {
        expect(M3uFilterUtils.updateM3UFilter).toHaveBeenCalled();
      });
      expect(M3uFilterUtils.addM3UFilter).not.toHaveBeenCalled();
    });

    it('calls fetchPlaylist after successful update', async () => {
      const { fetchPlaylist } = setupStores();
      render(<M3UFilter {...defaultProps({ filter: makeFilter() })} />);
      fireEvent.click(
        screen.getByRole('button', { name: /add|save|update|submit/i })
      );
      await waitFor(() => {
        expect(fetchPlaylist).toHaveBeenCalledWith(makeM3U().id);
      });
    });

    it('calls onClose after successful update', async () => {
      const onClose = vi.fn();
      setupStores();
      render(
        <M3UFilter {...defaultProps({ filter: makeFilter(), onClose })} />
      );
      fireEvent.click(
        screen.getByRole('button', { name: /add|save|update|submit/i })
      );
      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });
  });
});
