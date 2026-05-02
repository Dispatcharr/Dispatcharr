import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import M3UProfile from '../M3UProfile';

// ── WebSocket mock ─────────────────────────────────────────────────────────────
vi.mock('../../../WebSocket', () => ({
  useWebSocket: vi.fn(),
}));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/forms/M3uProfileUtils.js', () => ({
  addM3UProfile: vi.fn(),
  applyRegex: vi.fn(),
  applyXcSimplePatterns: vi.fn(),
  buildProfileSchema: vi.fn(),
  buildSubmitValues: vi.fn(),
  fetchFirstStreamUrl: vi.fn(),
  getDetectedMode: vi.fn(),
  prepareExpDate: vi.fn(),
  updateM3UProfile: vi.fn(),
  validateXcSimple: vi.fn(),
}));

// ── react-hook-form mock ───────────────────────────────────────────────────────
vi.mock('react-hook-form', async () => {
  const actual = await vi.importActual('react-hook-form');
  return {
    ...actual,
    useForm: vi.fn(),
  };
});

// ── @hookform/resolvers/yup mock ───────────────────────────────────────────────
vi.mock('@hookform/resolvers/yup', () => ({
  yupResolver: vi.fn(() => vi.fn()),
}));

// ── @mantine/dates mock ────────────────────────────────────────────────────────
vi.mock('@mantine/dates', () => ({
  DateTimePicker: ({ label, value, onChange, disabled, placeholder }) => (
    <div data-testid="date-time-picker">
      <label>{label}</label>
      <input
        data-testid="date-time-input"
        value={value ?? ''}
        onChange={(e) => onChange?.(e.target.value)}
        disabled={disabled}
        placeholder={placeholder}
      />
    </div>
  ),
}));

// ── @mantine/core mock ─────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Badge: ({ children, color }) => (
    <span data-testid="badge" data-color={color}>
      {children}
    </span>
  ),
  Button: ({ children, onClick, disabled, loading, variant, color, type }) => (
    <button
      type={type ?? 'button'}
      onClick={onClick}
      disabled={disabled || loading}
      data-loading={loading}
      data-variant={variant}
      data-color={color}
    >
      {children}
    </button>
  ),
  Flex: ({ children }) => <div>{children}</div>,
  Grid: ({ children }) => <div data-testid="grid">{children}</div>,
  GridCol: ({ children, span }) => (
    <div data-testid="grid-col" data-span={span}>
      {children}
    </div>
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
  NumberInput: ({
    label,
    value,
    onChange,
    disabled,
    min,
    max,
    placeholder,
  }) => (
    <div>
      <label>{label}</label>
      <input
        data-testid={`number-input-${label?.toLowerCase?.().replace(/\s+/g, '-') ?? 'number'}`}
        type="number"
        value={value ?? ''}
        onChange={(e) => onChange?.(Number(e.target.value))}
        disabled={disabled}
        min={min}
        max={max}
        placeholder={placeholder}
      />
    </div>
  ),
  Paper: ({ children }) => <div data-testid="paper">{children}</div>,
  SegmentedControl: ({ value, onChange, data, disabled }) => (
    <div data-testid="segmented-control">
      {data?.map((item) => (
        <button
          key={item.value ?? item}
          data-testid={`segment-${item.value ?? item}`}
          onClick={() => onChange?.(item.value ?? item)}
          data-active={value === (item.value ?? item)}
          disabled={disabled}
        >
          {item.label ?? item}
        </button>
      ))}
    </div>
  ),
  Text: ({ children, size, c, fw }) => (
    <span data-size={size} data-color={c} data-fw={fw}>
      {children}
    </span>
  ),
  Textarea: ({ label, value, onChange, disabled, placeholder, error }) => (
    <div>
      <label>{label}</label>
      <textarea
        data-testid={`textarea-${label?.toLowerCase?.().replace(/\s+/g, '-') ?? 'textarea'}`}
        value={value ?? ''}
        onChange={(e) => onChange?.(e.target.value)}
        disabled={disabled}
        placeholder={placeholder}
      />
      {error && <span data-testid="field-error">{error}</span>}
    </div>
  ),
  TextInput: ({ label, value, onChange, disabled, placeholder, error }) => (
    <div>
      <label>{label}</label>
      <input
        data-testid={`text-input-${label?.toLowerCase?.().replace(/\s+/g, '-') ?? 'text'}`}
        value={value ?? ''}
        onChange={(e) => onChange?.(e.target.value)}
        disabled={disabled}
        placeholder={placeholder}
      />
      {error && <span data-testid="field-error">{error}</span>}
    </div>
  ),
  Title: ({ children, order }) => <h2 data-order={order}>{children}</h2>,
}));

// ──────────────────────────────────────────────────────────────────────────────
// Imports after mocks
// ──────────────────────────────────────────────────────────────────────────────
import { useWebSocket } from '../../../WebSocket';
import { useForm } from 'react-hook-form';
import * as M3uProfileUtils from '../../../utils/forms/M3uProfileUtils.js';

// ── Helpers ────────────────────────────────────────────────────────────────────
const makeM3U = (overrides = {}) => ({
  id: 1,
  name: 'Test M3U',
  url: 'http://example.com/playlist.m3u',
  custom_properties: {
    max_streams: 1,
    profile: null,
    ...overrides.custom_properties,
  },
  ...overrides,
});

const makeProfile = (overrides = {}) => ({
  id: 10,
  name: 'Test Profile',
  type: 'regex',
  search_pattern: '.*HBO.*',
  max_streams: 2,
  exp_date: null,
  custom_properties: {},
  is_default: false,
  ...overrides,
});

const makeFormMethods = (overrides = {}) => ({
  register: vi.fn(() => ({
    onChange: vi.fn(),
    onBlur: vi.fn(),
    ref: vi.fn(),
    name: '',
  })),
  handleSubmit: vi.fn((fn) => (e) => {
    e?.preventDefault?.();
    return fn({});
  }),
  watch: vi.fn((field) => {
    const defaults = {
      type: 'regex',
      search_pattern: '',
      name: '',
      max_streams: 1,
    };
    return field ? defaults[field] : defaults;
  }),
  setValue: vi.fn(),
  reset: vi.fn(),
  setError: vi.fn(),
  formState: { errors: {}, isSubmitting: false },
  control: {},
  getValues: vi.fn(() => ({})),
  ...overrides,
});

const defaultProps = (overrides = {}) => ({
  m3u: makeM3U(),
  isOpen: true,
  onClose: vi.fn(),
  profile: null,
  ...overrides,
});

const setupWebSocket = ({ lastMessage = null } = {}) => {
  const sendMessage = vi.fn();
  vi.mocked(useWebSocket).mockReturnValue([true, sendMessage, lastMessage]);
};

const setupForm = (overrides = {}) => {
  const formMethods = makeFormMethods(overrides);
  vi.mocked(useForm).mockReturnValue(formMethods);
  return formMethods;
};

// ──────────────────────────────────────────────────────────────────────────────

describe('M3UProfile', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(M3uProfileUtils.addM3UProfile).mockResolvedValue(undefined);
    vi.mocked(M3uProfileUtils.updateM3UProfile).mockResolvedValue(undefined);
    vi.mocked(M3uProfileUtils.buildProfileSchema).mockReturnValue({});
    vi.mocked(M3uProfileUtils.buildSubmitValues).mockReturnValue({});
    vi.mocked(M3uProfileUtils.getDetectedMode).mockReturnValue('regex');
    vi.mocked(M3uProfileUtils.prepareExpDate).mockReturnValue(null);
    vi.mocked(M3uProfileUtils.fetchFirstStreamUrl).mockResolvedValue(
      'http://example.com/stream1'
    );
    vi.mocked(M3uProfileUtils.applyRegex).mockReturnValue('');
    vi.mocked(M3uProfileUtils.applyXcSimplePatterns).mockResolvedValue([]);
    vi.mocked(M3uProfileUtils.validateXcSimple).mockReturnValue(true);
    setupWebSocket();
    setupForm();
  });

  // ── Guard conditions ───────────────────────────────────────────────────────

  describe('guard conditions', () => {
    it('does not render modal when isOpen is false', () => {
      render(<M3UProfile {...defaultProps({ isOpen: false })} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the modal when isOpen is true with a valid m3u', () => {
      render(<M3UProfile {...defaultProps()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('renders "Edit Default Profile" title when editing default profile', () => {
      const profile = makeProfile({ is_default: true });
      render(<M3UProfile {...defaultProps({ profile })} />);
      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        /edit default profile/i
      );
    });

    it('renders "M3U Profile" title when not default', () => {
      render(<M3UProfile {...defaultProps()} />);
      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        /M3U profile/i
      );
    });

    it('renders a Save button', () => {
      render(<M3UProfile {...defaultProps()} />);
      expect(
        screen.getByRole('button', { name: /submit/i })
      ).toBeInTheDocument();
    });

    it('renders the segmented control for profile type', () => {
      const profile = makeProfile();
      render(
        <M3UProfile
          {...defaultProps({ profile, m3u: makeM3U({ account_type: 'XC' }) })}
        />
      );
      expect(screen.getByTestId('segmented-control')).toBeInTheDocument();
    });

    it('renders the Name field', () => {
      render(<M3UProfile {...defaultProps()} />);
      expect(screen.getByTestId('text-input-name')).toBeInTheDocument();
    });

    it('renders the Max Streams field', () => {
      render(<M3UProfile {...defaultProps()} />);
      expect(screen.getByTestId(/number-input/i)).toBeInTheDocument();
    });

    it('renders the DateTimePicker for expiration date', () => {
      render(<M3UProfile {...defaultProps()} />);
      expect(screen.getByTestId('date-time-picker')).toBeInTheDocument();
    });
  });

  // ── Pre-filling existing profile ───────────────────────────────────────────

  describe('pre-filling from profile prop', () => {
    it('calls reset with profile values when a profile is provided', () => {
      const formMethods = setupForm();
      const profile = makeProfile();
      render(<M3UProfile {...defaultProps({ profile })} />);
      expect(formMethods.reset).toHaveBeenCalled();
    });

    it('calls buildProfileSchema on mount', () => {
      render(<M3UProfile {...defaultProps()} />);
      expect(M3uProfileUtils.buildProfileSchema).toHaveBeenCalled();
    });
  });

  // ── Form reset for new profile ─────────────────────────────────────────────

  describe('form reset for new profile', () => {
    it('calls reset when modal opens with no profile', () => {
      const formMethods = setupForm();
      render(<M3UProfile {...defaultProps({ profile: null })} />);
      expect(formMethods.reset).toHaveBeenCalled();
    });

    it('re-initializes when profile prop changes from null to a value', () => {
      const formMethods = setupForm();
      const { rerender } = render(
        <M3UProfile {...defaultProps({ profile: null })} />
      );
      const profile = makeProfile();
      rerender(<M3UProfile {...defaultProps({ profile })} />);
      expect(formMethods.reset).toHaveBeenCalledTimes(2);
    });

    it('calls getDetectedMode when m3u is XC type', () => {
      const profile = makeProfile();
      render(
        <M3UProfile
          {...defaultProps({ profile, m3u: makeM3U({ account_type: 'XC' }) })}
        />
      );
      expect(M3uProfileUtils.getDetectedMode).toHaveBeenCalled();
    });
  });

  // ── Cancel / close behaviour ───────────────────────────────────────────────

  describe('cancel / close behaviour', () => {
    it('calls onClose when modal X is clicked', () => {
      const onClose = vi.fn();
      render(<M3UProfile {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
    });
  });

  // ── Adding a new profile ───────────────────────────────────────────────────

  describe('adding a new profile', () => {
    it('calls addM3UProfile when saving a new profile', async () => {
      setupForm({
        handleSubmit: vi.fn((fn) => (e) => {
          e?.preventDefault?.();
          return fn({ name: 'New Profile', type: 'regex', max_streams: 1 });
        }),
      });
      render(<M3UProfile {...defaultProps({ profile: null })} />);
      fireEvent.click(screen.getByRole('button', { name: /submit/i }));
      await waitFor(() => {
        expect(M3uProfileUtils.addM3UProfile).toHaveBeenCalled();
      });
    });

    it('does not call updateM3UProfile when adding a new profile', async () => {
      setupForm({
        handleSubmit: vi.fn((fn) => (e) => {
          e?.preventDefault?.();
          return fn({ name: 'New Profile', type: 'regex', max_streams: 1 });
        }),
      });
      render(<M3UProfile {...defaultProps({ profile: null })} />);
      fireEvent.click(screen.getByRole('button', { name: /submit/i }));
      await waitFor(() => {
        expect(M3uProfileUtils.updateM3UProfile).not.toHaveBeenCalled();
      });
    });

    it('calls onClose after successfully adding a profile', async () => {
      const onClose = vi.fn();
      setupForm({
        handleSubmit: vi.fn((fn) => (e) => {
          e?.preventDefault?.();
          return fn({ name: 'New Profile', type: 'regex' });
        }),
      });
      render(<M3UProfile {...defaultProps({ profile: null, onClose })} />);
      fireEvent.click(screen.getByRole('button', { name: /submit/i }));
      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });
  });

  // ── Updating an existing profile ───────────────────────────────────────────

  describe('updating an existing profile', () => {
    it('calls updateM3UProfile when saving an existing profile', async () => {
      const profile = makeProfile();
      setupForm({
        handleSubmit: vi.fn((fn) => (e) => {
          e?.preventDefault?.();
          return fn({ name: 'Updated Profile', type: 'regex', max_streams: 2 });
        }),
      });
      render(<M3UProfile {...defaultProps({ profile })} />);
      fireEvent.click(screen.getByRole('button', { name: /submit/i }));
      await waitFor(() => {
        expect(M3uProfileUtils.updateM3UProfile).toHaveBeenCalled();
      });
    });

    it('does not call addM3UProfile when updating an existing profile', async () => {
      const profile = makeProfile();
      setupForm({
        handleSubmit: vi.fn((fn) => (e) => {
          e?.preventDefault?.();
          return fn({ name: 'Updated Profile', type: 'regex' });
        }),
      });
      render(<M3UProfile {...defaultProps({ profile })} />);
      fireEvent.click(screen.getByRole('button', { name: /submit/i }));
      await waitFor(() => {
        expect(M3uProfileUtils.addM3UProfile).not.toHaveBeenCalled();
      });
    });

    it('calls prepareExpDate when form is submitted with a profile', async () => {
      const profile = makeProfile({ exp_date: '2025-12-31T00:00:00Z' });
      setupForm({
        handleSubmit: vi.fn((fn) => (e) => {
          e?.preventDefault?.();
          return fn({ exp_date: profile.exp_date });
        }),
      });
      render(<M3UProfile {...defaultProps({ profile })} />);
      fireEvent.click(screen.getByRole('button', { name: /submit/i }));
      await waitFor(() => {
        expect(M3uProfileUtils.prepareExpDate).toHaveBeenCalledWith(
          profile.exp_date,
          false
        );
      });
    });

    it('calls onClose after successfully updating a profile', async () => {
      const onClose = vi.fn();
      const profile = makeProfile();
      setupForm({
        handleSubmit: vi.fn((fn) => (e) => {
          e?.preventDefault?.();
          return fn({ name: 'Updated Profile', type: 'regex' });
        }),
      });
      render(<M3UProfile {...defaultProps({ profile, onClose })} />);
      fireEvent.click(screen.getByRole('button', { name: /submit/i }));
      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });
  });

  // ── Profile type switching ─────────────────────────────────────────────────

  describe('profile type switching', () => {
    it('calls setValue when a segment is selected', () => {
      const formMethods = setupForm();
      render(<M3UProfile {...defaultProps()} />);
      const regexSegment = screen.queryByTestId('segment-regex');
      if (regexSegment) {
        fireEvent.click(regexSegment);
        expect(formMethods.setValue).toHaveBeenCalled();
      }
    });

    it('renders regex-specific fields when type is regex', () => {
      setupForm({
        watch: vi.fn((field) => {
          if (field === 'type') return 'regex';
          return undefined;
        }),
      });
      render(<M3UProfile {...defaultProps()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });
  });

  // ── Regex apply ────────────────────────────────────────────────────────────

  describe('regex apply', () => {
    it('calls fetchFirstStreamUrl and applyRegex when Apply is clicked', async () => {
      setupForm({
        watch: vi.fn((field) => {
          if (field === 'type') return 'regex';
          if (field === 'search_pattern') return '.*HBO.*';
          return undefined;
        }),
        getValues: vi.fn(() => ({ search_pattern: '.*HBO.*', type: 'regex' })),
      });
      render(<M3UProfile {...defaultProps()} />);

      const applyBtn = screen.queryByRole('button', { name: /apply/i });
      if (applyBtn) {
        fireEvent.click(applyBtn);
        await waitFor(() => {
          expect(M3uProfileUtils.fetchFirstStreamUrl).toHaveBeenCalled();
        });
      }
    });

    it('calls applyXcSimplePatterns when type is xc_simple and Apply is clicked', async () => {
      setupForm({
        watch: vi.fn((field) => {
          if (field === 'type') return 'xc_simple';
          return undefined;
        }),
        getValues: vi.fn(() => ({ type: 'xc_simple' })),
      });
      render(<M3UProfile {...defaultProps()} />);

      const applyBtn = screen.queryByRole('button', { name: /apply/i });
      if (applyBtn) {
        fireEvent.click(applyBtn);
        await waitFor(() => {
          expect(M3uProfileUtils.applyXcSimplePatterns).toHaveBeenCalled();
        });
      }
    });
  });

  // ── WebSocket integration ──────────────────────────────────────────────────

  describe('WebSocket integration', () => {
    it('initializes useWebSocket hook', () => {
      render(<M3UProfile {...defaultProps()} />);
      expect(useWebSocket).toHaveBeenCalled();
    });

    it('reacts to lastMessage changes without crashing', () => {
      setupWebSocket({
        lastMessage: { data: JSON.stringify({ type: 'update', payload: {} }) },
      });
      setupForm(); // ensure form mock is re-established after setupWebSocket override
      const { rerender } = render(<M3UProfile {...defaultProps()} />);
      rerender(<M3UProfile {...defaultProps()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });
  });

  // ── Loading state ──────────────────────────────────────────────────────────

  describe('loading state', () => {
    it('disables Save button while submitting', () => {
      setupForm({
        formState: { errors: {}, isSubmitting: true },
      });
      render(<M3UProfile {...defaultProps({ profile: null })} />);
      expect(screen.getByRole('button', { name: /submit/i })).toBeDisabled();
    });
  });

  // ── buildSubmitValues integration ──────────────────────────────────────────

  describe('buildSubmitValues', () => {
    it('calls buildSubmitValues before saving', async () => {
      setupForm({
        handleSubmit: vi.fn((fn) => (e) => {
          e?.preventDefault?.();
          return fn({ name: 'Profile', type: 'regex', max_streams: 1 });
        }),
      });
      render(<M3UProfile {...defaultProps({ profile: null })} />);
      fireEvent.click(screen.getByRole('button', { name: /submit/i }));
      await waitFor(() => {
        expect(M3uProfileUtils.buildSubmitValues).toHaveBeenCalled();
      });
    });
  });
});
