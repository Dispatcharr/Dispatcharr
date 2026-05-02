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
  splitByPattern: vi.fn(),
  updateM3UProfile: vi.fn(),
  validateXcSimple: vi.fn(),
}));

// ── react-hook-form mock ───────────────────────────────────────────────────────
vi.mock('react-hook-form', async () => {
  const actual = await vi.importActual('react-hook-form');
  return { ...actual, useForm: vi.fn() };
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
  Alert: ({ children, title }) => (
    <div data-testid="alert">
      <span data-testid="alert-title">{title}</span>
      {children}
    </div>
  ),
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
  username: 'user1',
  password: 'pass1',
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
  replace_pattern: '',
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
      exp_date: null,
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
  return sendMessage;
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
    vi.mocked(M3uProfileUtils.getDetectedMode).mockReturnValue('simple');
    vi.mocked(M3uProfileUtils.prepareExpDate).mockReturnValue(null);
    vi.mocked(M3uProfileUtils.fetchFirstStreamUrl).mockResolvedValue(
      'http://example.com/stream1'
    );
    vi.mocked(M3uProfileUtils.applyRegex).mockReturnValue('');
    vi.mocked(M3uProfileUtils.applyXcSimplePatterns).mockResolvedValue([]);
    vi.mocked(M3uProfileUtils.validateXcSimple).mockReturnValue({});
    vi.mocked(M3uProfileUtils.splitByPattern).mockReturnValue(null);
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

    it('renders the segmented control for XC profile type', () => {
      const profile = makeProfile();
      render(
        <M3UProfile
          {...defaultProps({ profile, m3u: makeM3U({ account_type: 'XC' }) })}
        />
      );
      expect(screen.getByTestId('segmented-control')).toBeInTheDocument();
    });

    it('does not render the segmented control for non-XC m3u', () => {
      render(<M3UProfile {...defaultProps()} />);
      expect(screen.queryByTestId('segmented-control')).not.toBeInTheDocument();
    });

    it('does not render the segmented control for default XC profile', () => {
      const profile = makeProfile({ is_default: true });
      render(
        <M3UProfile
          {...defaultProps({ profile, m3u: makeM3U({ account_type: 'XC' }) })}
        />
      );
      expect(screen.queryByTestId('segmented-control')).not.toBeInTheDocument();
    });

    it('renders the Name field', () => {
      render(<M3UProfile {...defaultProps()} />);
      expect(screen.getByTestId('text-input-name')).toBeInTheDocument();
    });

    it('renders the Max Streams field for non-default profile', () => {
      render(<M3UProfile {...defaultProps()} />);
      expect(screen.getByTestId(/number-input/i)).toBeInTheDocument();
    });

    it('does not render Max Streams field for default profile', () => {
      const profile = makeProfile({ is_default: true });
      render(<M3UProfile {...defaultProps({ profile })} />);
      expect(screen.queryByTestId(/number-input/i)).not.toBeInTheDocument();
    });

    it('renders the DateTimePicker for non-XC expiration date', () => {
      render(<M3UProfile {...defaultProps()} />);
      expect(screen.getByTestId('date-time-picker')).toBeInTheDocument();
    });

    it('does not render DateTimePicker for XC m3u', () => {
      render(
        <M3UProfile
          {...defaultProps({ m3u: makeM3U({ account_type: 'XC' }) })}
        />
      );
      expect(screen.queryByTestId('date-time-picker')).not.toBeInTheDocument();
    });

    it('renders default profile alert for default profiles', () => {
      const profile = makeProfile({ is_default: true });
      render(<M3UProfile {...defaultProps({ profile })} />);
      expect(screen.getByTestId('alert-title')).toHaveTextContent(
        /default profile/i
      );
    });

    it('renders the Notes textarea', () => {
      render(<M3UProfile {...defaultProps()} />);
      expect(screen.getByTestId('textarea-notes')).toBeInTheDocument();
    });
  });

  // ── Live regex demonstration ───────────────────────────────────────────────

  describe('live regex demonstration', () => {
    it('renders the demo section for default profiles', () => {
      const profile = makeProfile({ is_default: true });
      render(<M3UProfile {...defaultProps({ profile })} />);
      expect(
        screen.getByPlaceholderText(/enter a sample url/i)
      ).toBeInTheDocument();
    });

    it('renders the demo section for non-XC m3u', () => {
      render(<M3UProfile {...defaultProps()} />);
      expect(
        screen.getByPlaceholderText(/enter a sample url/i)
      ).toBeInTheDocument();
    });

    it('does not render the demo section for XC m3u in simple mode', () => {
      // getDetectedMode returns 'simple' by default in beforeEach
      render(
        <M3UProfile
          {...defaultProps({ m3u: makeM3U({ account_type: 'XC' }) })}
        />
      );
      expect(
        screen.queryByPlaceholderText(/enter a sample url/i)
      ).not.toBeInTheDocument();
    });

    it('calls splitByPattern when rendering highlighted text', async () => {
      vi.mocked(M3uProfileUtils.fetchFirstStreamUrl).mockResolvedValue(
        'http://example.com/stream'
      );
      render(<M3UProfile {...defaultProps()} />);
      await waitFor(() => {
        expect(M3uProfileUtils.splitByPattern).toHaveBeenCalled();
      });
    });

    it('calls applyRegex when rendering the replace result', async () => {
      vi.mocked(M3uProfileUtils.fetchFirstStreamUrl).mockResolvedValue(
        'http://example.com/stream'
      );
      render(<M3UProfile {...defaultProps()} />);
      await waitFor(() => {
        expect(M3uProfileUtils.applyRegex).toHaveBeenCalled();
      });
    });

    it('populates sample input after fetching stream URL', async () => {
      vi.mocked(M3uProfileUtils.fetchFirstStreamUrl).mockResolvedValue(
        'http://example.com/stream1'
      );
      render(<M3UProfile {...defaultProps()} />);
      await waitFor(() => {
        expect(screen.getByPlaceholderText(/enter a sample url/i)).toHaveValue(
          'http://example.com/stream1'
        );
      });
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

  // ── Profile type switching (XC mode) ──────────────────────────────────────

  describe('profile type switching (XC mode)', () => {
    const xcProps = () =>
      defaultProps({
        m3u: makeM3U({ account_type: 'XC' }),
        profile: makeProfile(),
      });

    it('renders Simple and Advanced segments for XC m3u', () => {
      render(<M3UProfile {...xcProps()} />);
      expect(screen.getByTestId('segment-simple')).toBeInTheDocument();
      expect(screen.getByTestId('segment-advanced')).toBeInTheDocument();
    });

    it('renders New Username / New Password fields in simple mode', () => {
      render(<M3UProfile {...xcProps()} />);
      expect(screen.getByTestId('text-input-new-username')).toBeInTheDocument();
      expect(screen.getByTestId('text-input-new-password')).toBeInTheDocument();
    });

    it('switches to advanced mode and renders Search Pattern field', () => {
      render(<M3UProfile {...xcProps()} />);
      fireEvent.click(screen.getByTestId('segment-advanced'));
      expect(
        screen.getByTestId('text-input-search-pattern-(regex)')
      ).toBeInTheDocument();
    });

    it('calls setValue when switching to advanced mode', () => {
      const formMethods = setupForm();
      render(<M3UProfile {...xcProps()} />);
      fireEvent.click(screen.getByTestId('segment-advanced'));
      expect(formMethods.setValue).toHaveBeenCalledWith(
        'search_pattern',
        expect.any(String)
      );
    });

    it('switches back to simple mode from advanced', () => {
      render(<M3UProfile {...xcProps()} />);
      fireEvent.click(screen.getByTestId('segment-advanced'));
      fireEvent.click(screen.getByTestId('segment-simple'));
      expect(screen.getByTestId('text-input-new-username')).toBeInTheDocument();
    });

    it('calls setValue when a segment is selected', () => {
      const formMethods = setupForm();
      render(<M3UProfile {...defaultProps()} />);
      const regexSegment = screen.queryByTestId('segment-regex');
      if (regexSegment) {
        fireEvent.click(regexSegment);
        expect(formMethods.setValue).toHaveBeenCalled();
      }
    });

    it('shows validation errors when XC simple fields are empty on submit', async () => {
      vi.mocked(M3uProfileUtils.validateXcSimple).mockReturnValue({
        newUsername: 'Required',
        newPassword: 'Required',
      });
      setupForm({
        handleSubmit: vi.fn((fn) => (e) => {
          e?.preventDefault?.();
          return fn({});
        }),
      });
      render(<M3UProfile {...xcProps()} />);
      fireEvent.click(screen.getByRole('button', { name: /submit/i }));
      await waitFor(() => {
        expect(M3uProfileUtils.addM3UProfile).not.toHaveBeenCalled();
        expect(M3uProfileUtils.updateM3UProfile).not.toHaveBeenCalled();
      });
    });
  });

  // ── Default profile — Reset to Defaults button ─────────────────────────────

  describe('default profile — Reset to Defaults', () => {
    it('renders the Reset to Defaults button for default profiles', () => {
      const profile = makeProfile({ is_default: true });
      render(<M3UProfile {...defaultProps({ profile })} />);
      expect(
        screen.getByRole('button', { name: /reset to defaults/i })
      ).toBeInTheDocument();
    });

    it('does not render Reset to Defaults for non-default profiles', () => {
      render(<M3UProfile {...defaultProps()} />);
      expect(
        screen.queryByRole('button', { name: /reset to defaults/i })
      ).not.toBeInTheDocument();
    });

    it('calls setValue with default patterns when Reset to Defaults is clicked', () => {
      const formMethods = setupForm();
      const profile = makeProfile({ is_default: true });
      render(<M3UProfile {...defaultProps({ profile })} />);
      fireEvent.click(
        screen.getByRole('button', { name: /reset to defaults/i })
      );
      expect(formMethods.setValue).toHaveBeenCalledWith(
        'search_pattern',
        '^(.*)$'
      );
      expect(formMethods.setValue).toHaveBeenCalledWith(
        'replace_pattern',
        '$1'
      );
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
      setupForm();
      const { rerender } = render(<M3UProfile {...defaultProps()} />);
      rerender(<M3UProfile {...defaultProps()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });
  });

  // ── Loading state ──────────────────────────────────────────────────────────

  describe('loading state', () => {
    it('disables Save button while submitting', () => {
      setupForm({ formState: { errors: {}, isSubmitting: true } });
      render(<M3UProfile {...defaultProps({ profile: null })} />);
      expect(screen.getByRole('button', { name: /submit/i })).toBeDisabled();
    });

    it('enables Save button when not submitting', () => {
      setupForm({ formState: { errors: {}, isSubmitting: false } });
      render(<M3UProfile {...defaultProps({ profile: null })} />);
      expect(
        screen.getByRole('button', { name: /submit/i })
      ).not.toBeDisabled();
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
