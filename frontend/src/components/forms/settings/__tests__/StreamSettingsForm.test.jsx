import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import StreamSettingsForm from '../StreamSettingsForm';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../../store/settings.jsx', () => ({ default: vi.fn() }));
vi.mock('../../../../store/warnings.jsx', () => ({ default: vi.fn() }));
vi.mock('../../../../store/userAgents.jsx', () => ({ default: vi.fn() }));
vi.mock('../../../../store/streamProfiles.jsx', () => ({ default: vi.fn() }));

// ── Constants mock ─────────────────────────────────────────────────────────────
vi.mock('../../../../constants.js', () => ({
  REGION_CHOICES: [
    { label: 'US', value: 'us' },
    { label: 'EU', value: 'eu' },
  ],
}));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../../utils/pages/SettingsUtils.js', () => ({
  getChangedSettings: vi.fn(),
  parseSettings: vi.fn(),
  rehashStreams: vi.fn(),
  saveChangedSettings: vi.fn(),
}));

vi.mock('../../../../utils/forms/settings/StreamSettingsFormUtils.js', () => ({
  getStreamSettingsFormInitialValues: vi.fn(),
  getStreamSettingsFormValidation: vi.fn(),
}));

// ── Mantine form ───────────────────────────────────────────────────────────────
vi.mock('@mantine/form', () => ({ useForm: vi.fn() }));

// ── ConfirmationDialog mock ────────────────────────────────────────────────────
vi.mock('../../../ConfirmationDialog.jsx', () => ({
  default: ({
    opened,
    onClose,
    onConfirm,
    title,
    message,
    confirmLabel,
    cancelLabel,
    actionKey,
    onSuppressChange,
  }) =>
    opened ? (
      <div data-testid="confirmation-dialog">
        <div data-testid="confirm-title">{title}</div>
        <div data-testid="confirm-message">{message}</div>
        <button data-testid="confirm-ok" onClick={onConfirm}>
          {confirmLabel}
        </button>
        <button data-testid="confirm-cancel" onClick={onClose}>
          {cancelLabel}
        </button>
        {actionKey && (
          <button
            data-testid="confirm-suppress"
            onClick={() => onSuppressChange?.(actionKey)}
          >
            Don't show again
          </button>
        )}
      </div>
    ) : null,
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Alert: ({ title, children }) => (
    <div data-testid="alert">
      <span data-testid="alert-title">{title}</span>
      {children}
    </div>
  ),
  Button: ({ children, onClick, disabled, loading, type, variant, color }) => (
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
  MultiSelect: ({ label, id, data, ...rest }) => (
    <div>
      <label htmlFor={id}>{label}</label>
      <select
        data-testid={id}
        id={id}
        aria-label={label}
        multiple
        onChange={(e) => {
          const selected = Array.from(e.target.selectedOptions).map(
            (o) => o.value
          );
          rest.onChange?.(selected);
        }}
        value={rest.value ?? []}
      >
        {data?.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  ),
  Select: ({ label, id, data, ...rest }) => (
    <div>
      <label htmlFor={id}>{label}</label>
      <select
        data-testid={id}
        id={id}
        aria-label={label}
        onChange={(e) => rest.onChange?.(e.target.value)}
        value={rest.value ?? ''}
      >
        {data?.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  ),
  Switch: ({ id, ...rest }) => (
    <input
      data-testid={id}
      id={id}
      type="checkbox"
      checked={rest.checked ?? false}
      onChange={(e) => rest.onChange?.(e)}
    />
  ),
  Text: ({ children, size, fw }) => (
    <span data-size={size} data-fw={fw}>
      {children}
    </span>
  ),
}));

// ──────────────────────────────────────────────────────────────────────────────
// Imports after mocks
// ──────────────────────────────────────────────────────────────────────────────
import useSettingsStore from '../../../../store/settings.jsx';
import useWarningsStore from '../../../../store/warnings.jsx';
import useUserAgentsStore from '../../../../store/userAgents.jsx';
import useStreamProfilesStore from '../../../../store/streamProfiles.jsx';
import { useForm } from '@mantine/form';
import {
  getChangedSettings,
  parseSettings,
  rehashStreams,
  saveChangedSettings,
} from '../../../../utils/pages/SettingsUtils.js';
import {
  getStreamSettingsFormInitialValues,
  getStreamSettingsFormValidation,
} from '../../../../utils/forms/settings/StreamSettingsFormUtils.js';

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────
const mockFormValues = {
  default_user_agent: '1',
  default_stream_profile: '2',
  preferred_region: 'us',
  auto_import_mapped_files: false,
  m3u_hash_key: ['name'],
};

const makeFormMock = (overrides = {}) => ({
  getInputProps: vi.fn((field, opts) => {
    if (opts?.type === 'checkbox') {
      return { checked: mockFormValues[field] ?? false, onChange: vi.fn() };
    }
    return { value: mockFormValues[field] ?? '', onChange: vi.fn() };
  }),
  setValues: vi.fn(),
  getValues: vi.fn(() => mockFormValues),
  onSubmit: vi.fn((handler) => (e) => {
    e?.preventDefault?.();
    return handler();
  }),
  submitting: false,
  errors: {},
  ...overrides,
});

const makeSettings = (overrides = {}) => ({
  stream_settings: {
    key: 'stream_settings',
    value: { m3u_hash_key: 'name' },
  },
  ...overrides,
});

const makeUserAgents = () => [
  { id: 1, name: 'Chrome' },
  { id: 2, name: 'Firefox' },
];

const makeStreamProfiles = () => [
  { id: 1, name: 'Default' },
  { id: 2, name: 'HLS' },
];

const setupMocks = ({
  settings = makeSettings(),
  formOverrides = {},
  warningSuppressed = false,
  userAgents = makeUserAgents(),
  streamProfiles = makeStreamProfiles(),
} = {}) => {
  const formMock = makeFormMock(formOverrides);

  vi.mocked(useForm).mockReturnValue(formMock);
  vi.mocked(getStreamSettingsFormInitialValues).mockReturnValue(mockFormValues);
  vi.mocked(getStreamSettingsFormValidation).mockReturnValue({});
  vi.mocked(parseSettings).mockReturnValue(mockFormValues);
  vi.mocked(getChangedSettings).mockReturnValue({ preferred_region: 'eu' });
  vi.mocked(saveChangedSettings).mockResolvedValue(undefined);
  vi.mocked(rehashStreams).mockResolvedValue(undefined);

  vi.mocked(useSettingsStore).mockImplementation((sel) => sel({ settings }));
  vi.mocked(useWarningsStore).mockImplementation((sel) =>
    sel({
      suppressWarning: vi.fn(),
      isWarningSuppressed: vi.fn(() => warningSuppressed),
    })
  );
  vi.mocked(useUserAgentsStore).mockImplementation((sel) =>
    sel({ userAgents })
  );
  vi.mocked(useStreamProfilesStore).mockImplementation((sel) =>
    sel({ profiles: streamProfiles })
  );

  return { formMock };
};

// ──────────────────────────────────────────────────────────────────────────────
// Tests
// ──────────────────────────────────────────────────────────────────────────────
describe('StreamSettingsForm', () => {
  let formMock;

  beforeEach(() => {
    vi.clearAllMocks();
    ({ formMock } = setupMocks());
  });

  // ── Rendering ──────────────────────────────────────────────────────────────
  describe('rendering', () => {
    it('renders without crashing', () => {
      render(<StreamSettingsForm active={true} />);
      expect(screen.getByText('Save')).toBeInTheDocument();
    });

    it('renders the Save button', () => {
      render(<StreamSettingsForm active={true} />);
      expect(screen.getByText('Save')).toBeInTheDocument();
    });

    it('renders the Rehash Streams button', () => {
      render(<StreamSettingsForm active={true} />);
      expect(screen.getByText('Rehash Streams')).toBeInTheDocument();
    });

    it('renders the Default User Agent select', () => {
      render(<StreamSettingsForm active={true} />);
      expect(screen.getByTestId('default_user_agent')).toBeInTheDocument();
    });

    it('renders the Default Stream Profile select', () => {
      render(<StreamSettingsForm active={true} />);
      expect(screen.getByTestId('default_stream_profile')).toBeInTheDocument();
    });

    it('renders the Preferred Region select', () => {
      render(<StreamSettingsForm active={true} />);
      expect(screen.getByTestId('preferred_region')).toBeInTheDocument();
    });

    it('renders the Auto-Import Mapped Files switch', () => {
      render(<StreamSettingsForm active={true} />);
      expect(
        screen.getByTestId('auto_import_mapped_files')
      ).toBeInTheDocument();
    });

    it('renders the M3U Hash Key multiselect', () => {
      render(<StreamSettingsForm active={true} />);
      expect(screen.getByTestId('m3u_hash_key')).toBeInTheDocument();
    });

    it('populates user agent options from store', () => {
      render(<StreamSettingsForm active={true} />);
      expect(screen.getByText('Chrome')).toBeInTheDocument();
      expect(screen.getByText('Firefox')).toBeInTheDocument();
    });

    it('populates stream profile options from store', () => {
      render(<StreamSettingsForm active={true} />);
      expect(screen.getByText('Default')).toBeInTheDocument();
      expect(screen.getByText('HLS')).toBeInTheDocument();
    });

    it('populates region options from REGION_CHOICES', () => {
      render(<StreamSettingsForm active={true} />);
      expect(screen.getByText('US')).toBeInTheDocument();
      expect(screen.getByText('EU')).toBeInTheDocument();
    });

    it('does not show success alert on initial render', () => {
      render(<StreamSettingsForm active={true} />);
      expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
    });

    it('does not show confirmation dialog on initial render', () => {
      render(<StreamSettingsForm active={true} />);
      expect(
        screen.queryByTestId('confirmation-dialog')
      ).not.toBeInTheDocument();
    });
  });

  // ── Initialization ─────────────────────────────────────────────────────────
  describe('initialization', () => {
    it('calls getStreamSettingsFormInitialValues on mount', () => {
      render(<StreamSettingsForm active={true} />);
      expect(getStreamSettingsFormInitialValues).toHaveBeenCalled();
    });

    it('calls getStreamSettingsFormValidation on mount', () => {
      render(<StreamSettingsForm active={true} />);
      expect(getStreamSettingsFormValidation).toHaveBeenCalled();
    });

    it('calls parseSettings with settings from store on mount', async () => {
      const settings = makeSettings();
      setupMocks({ settings });
      render(<StreamSettingsForm active={true} />);
      await waitFor(() => {
        expect(parseSettings).toHaveBeenCalledWith(settings);
      });
    });

    it('calls form.setValues with parsed settings on mount', async () => {
      render(<StreamSettingsForm active={true} />);
      await waitFor(() => {
        expect(formMock.setValues).toHaveBeenCalledWith(mockFormValues);
      });
    });

    it('does not call parseSettings when settings is null', async () => {
      vi.mocked(useSettingsStore).mockImplementation((sel) =>
        sel({ settings: null })
      );
      render(<StreamSettingsForm active={true} />);
      await waitFor(() => {
        expect(parseSettings).not.toHaveBeenCalled();
      });
    });
  });

  // ── active prop ────────────────────────────────────────────────────────────
  describe('active prop', () => {
    it('clears saved state when active becomes false', async () => {
      vi.mocked(saveChangedSettings).mockResolvedValue(undefined);
      vi.mocked(getChangedSettings).mockReturnValue({});
      const { rerender } = render(<StreamSettingsForm active={true} />);

      fireEvent.submit(screen.getByText('Save').closest('form'));
      await waitFor(() => {
        expect(screen.getByTestId('alert')).toBeInTheDocument();
      });

      rerender(<StreamSettingsForm active={false} />);
      await waitFor(() => {
        expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
      });
    });

    it('clears rehashSuccess when active becomes false', async () => {
      ({ formMock } = setupMocks({ warningSuppressed: true }));
      const { rerender } = render(<StreamSettingsForm active={true} />);

      fireEvent.click(screen.getByText('Rehash Streams'));
      await waitFor(() => {
        expect(screen.getByTestId('alert')).toBeInTheDocument();
      });

      rerender(<StreamSettingsForm active={false} />);
      await waitFor(() => {
        expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
      });
    });
  });

  // ── Form submission — no hash key change ───────────────────────────────────
  describe('form submission (no M3U hash key change)', () => {
    beforeEach(() => {
      // Same hash key before and after → no dialog
      vi.mocked(getChangedSettings).mockReturnValue({ preferred_region: 'eu' });
      setupMocks();
      formMock = makeFormMock();
      vi.mocked(useForm).mockReturnValue(formMock);
    });

    it('calls saveChangedSettings with settings and changed values on submit', async () => {
      const settings = makeSettings();
      render(<StreamSettingsForm active={true} />);

      fireEvent.submit(screen.getByText('Save').closest('form'));
      await waitFor(() => {
        expect(saveChangedSettings).toHaveBeenCalledWith(
          settings,
          expect.any(Object)
        );
      });
    });

    it('shows success alert after successful save', async () => {
      render(<StreamSettingsForm active={true} />);

      fireEvent.submit(screen.getByText('Save').closest('form'));
      await waitFor(() => {
        expect(screen.getByTestId('alert')).toBeInTheDocument();
        expect(screen.getByTestId('alert-title')).toHaveTextContent(
          'Saved Successfully'
        );
      });
    });

    it('does not show success alert when saveChangedSettings throws', async () => {
      vi.mocked(saveChangedSettings).mockRejectedValue(
        new Error('save failed')
      );
      const consoleSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      render(<StreamSettingsForm active={true} />);

      fireEvent.submit(screen.getByText('Save').closest('form'));
      await waitFor(() => {
        expect(consoleSpy).toHaveBeenCalled();
      });
      expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
      consoleSpy.mockRestore();
    });

    it('logs error when saveChangedSettings throws', async () => {
      const error = new Error('save failed');
      vi.mocked(saveChangedSettings).mockRejectedValue(error);
      const consoleSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      render(<StreamSettingsForm active={true} />);

      fireEvent.submit(screen.getByText('Save').closest('form'));
      await waitFor(() => {
        expect(consoleSpy).toHaveBeenCalledWith(
          'Error saving settings:',
          error
        );
      });
      consoleSpy.mockRestore();
    });

    it('does not open confirmation dialog when hash key is unchanged', async () => {
      render(<StreamSettingsForm active={true} />);

      fireEvent.submit(screen.getByText('Save').closest('form'));
      await waitFor(() => {
        expect(saveChangedSettings).toHaveBeenCalled();
      });
      expect(
        screen.queryByTestId('confirmation-dialog')
      ).not.toBeInTheDocument();
    });
  });

  // ── Form submission — hash key changed ────────────────────────────────────
  describe('form submission (M3U hash key changed)', () => {
    const makeHashChangedFormMock = () =>
      makeFormMock({
        getValues: vi.fn(() => ({
          ...mockFormValues,
          m3u_hash_key: ['url'], // different from stored 'name'
        })),
      });

    it('opens confirmation dialog with save title when hash key changes', async () => {
      const fm = makeHashChangedFormMock();
      vi.mocked(useForm).mockReturnValue(fm);
      render(<StreamSettingsForm active={true} />);

      fireEvent.submit(screen.getByText('Save').closest('form'));
      await waitFor(() => {
        expect(screen.getByTestId('confirmation-dialog')).toBeInTheDocument();
        expect(screen.getByTestId('confirm-title')).toHaveTextContent(
          'Save Settings and Rehash Streams'
        );
      });
    });

    it('shows "Save and Rehash" confirm label for hash key change dialog', async () => {
      const fm = makeHashChangedFormMock();
      vi.mocked(useForm).mockReturnValue(fm);
      render(<StreamSettingsForm active={true} />);

      fireEvent.submit(screen.getByText('Save').closest('form'));
      await waitFor(() => {
        expect(screen.getByTestId('confirm-ok')).toHaveTextContent(
          'Save and Rehash'
        );
      });
    });

    it('does not call saveChangedSettings before dialog is confirmed', async () => {
      const fm = makeHashChangedFormMock();
      vi.mocked(useForm).mockReturnValue(fm);
      render(<StreamSettingsForm active={true} />);

      fireEvent.submit(screen.getByText('Save').closest('form'));
      await waitFor(() => {
        expect(screen.getByTestId('confirmation-dialog')).toBeInTheDocument();
      });
      expect(saveChangedSettings).not.toHaveBeenCalled();
    });

    it('calls saveChangedSettings after confirming save-and-rehash dialog', async () => {
      const fm = makeHashChangedFormMock();
      vi.mocked(useForm).mockReturnValue(fm);
      const settings = makeSettings();
      setupMocks({ settings });
      vi.mocked(useForm).mockReturnValue(fm);
      render(<StreamSettingsForm active={true} />);

      fireEvent.submit(screen.getByText('Save').closest('form'));
      await waitFor(() => screen.getByTestId('confirmation-dialog'));
      fireEvent.click(screen.getByTestId('confirm-ok'));

      await waitFor(() => {
        expect(saveChangedSettings).toHaveBeenCalled();
      });
    });

    it('shows success alert after confirming save-and-rehash dialog', async () => {
      const fm = makeHashChangedFormMock();
      vi.mocked(useForm).mockReturnValue(fm);
      render(<StreamSettingsForm active={true} />);

      fireEvent.submit(screen.getByText('Save').closest('form'));
      await waitFor(() => screen.getByTestId('confirmation-dialog'));
      fireEvent.click(screen.getByTestId('confirm-ok'));

      await waitFor(() => {
        expect(screen.getByTestId('alert-title')).toHaveTextContent(
          'Saved Successfully'
        );
      });
    });

    it('closes dialog after confirming save-and-rehash', async () => {
      const fm = makeHashChangedFormMock();
      vi.mocked(useForm).mockReturnValue(fm);
      render(<StreamSettingsForm active={true} />);

      fireEvent.submit(screen.getByText('Save').closest('form'));
      await waitFor(() => screen.getByTestId('confirmation-dialog'));
      fireEvent.click(screen.getByTestId('confirm-ok'));

      await waitFor(() => {
        expect(
          screen.queryByTestId('confirmation-dialog')
        ).not.toBeInTheDocument();
      });
    });

    it('closes dialog and does not save when Cancel is clicked', async () => {
      const fm = makeHashChangedFormMock();
      vi.mocked(useForm).mockReturnValue(fm);
      render(<StreamSettingsForm active={true} />);

      fireEvent.submit(screen.getByText('Save').closest('form'));
      await waitFor(() => screen.getByTestId('confirmation-dialog'));
      fireEvent.click(screen.getByTestId('confirm-cancel'));

      await waitFor(() => {
        expect(
          screen.queryByTestId('confirmation-dialog')
        ).not.toBeInTheDocument();
      });
      expect(saveChangedSettings).not.toHaveBeenCalled();
    });

    it('skips dialog entirely when rehash-streams warning is suppressed', async () => {
      const fm = makeHashChangedFormMock();
      vi.mocked(useForm).mockReturnValue(fm);
      setupMocks({ warningSuppressed: true });
      vi.mocked(useForm).mockReturnValue(fm);
      render(<StreamSettingsForm active={true} />);

      fireEvent.submit(screen.getByText('Save').closest('form'));
      await waitFor(() => {
        expect(saveChangedSettings).toHaveBeenCalled();
      });
      expect(
        screen.queryByTestId('confirmation-dialog')
      ).not.toBeInTheDocument();
    });
  });

  // ── Rehash Streams ─────────────────────────────────────────────────────────
  describe('Rehash Streams button', () => {
    it('opens confirmation dialog with rehash title when warning is not suppressed', async () => {
      render(<StreamSettingsForm active={true} />);
      fireEvent.click(screen.getByText('Rehash Streams'));

      await waitFor(() => {
        expect(screen.getByTestId('confirmation-dialog')).toBeInTheDocument();
        expect(screen.getByTestId('confirm-title')).toHaveTextContent(
          'Confirm Stream Rehash'
        );
      });
    });

    it('shows "Start Rehash" confirm label for rehash-only dialog', async () => {
      render(<StreamSettingsForm active={true} />);
      fireEvent.click(screen.getByText('Rehash Streams'));

      await waitFor(() => {
        expect(screen.getByTestId('confirm-ok')).toHaveTextContent(
          'Start Rehash'
        );
      });
    });

    it('calls rehashStreams after confirming rehash dialog', async () => {
      render(<StreamSettingsForm active={true} />);
      fireEvent.click(screen.getByText('Rehash Streams'));
      await waitFor(() => screen.getByTestId('confirmation-dialog'));
      fireEvent.click(screen.getByTestId('confirm-ok'));

      await waitFor(() => {
        expect(rehashStreams).toHaveBeenCalled();
      });
    });

    it('skips confirmation dialog and calls rehashStreams directly when suppressed', async () => {
      setupMocks({ warningSuppressed: true });
      render(<StreamSettingsForm active={true} />);
      fireEvent.click(screen.getByText('Rehash Streams'));

      await waitFor(() => {
        expect(rehashStreams).toHaveBeenCalled();
      });
      expect(
        screen.queryByTestId('confirmation-dialog')
      ).not.toBeInTheDocument();
    });

    it('shows rehash success alert after rehash completes', async () => {
      setupMocks({ warningSuppressed: true });
      render(<StreamSettingsForm active={true} />);
      fireEvent.click(screen.getByText('Rehash Streams'));

      await waitFor(() => {
        expect(screen.getByTestId('alert-title')).toHaveTextContent(
          'Rehash task queued successfully'
        );
      });
    });

    it('does not show rehash success alert when rehashStreams throws', async () => {
      setupMocks({ warningSuppressed: true });
      vi.mocked(rehashStreams).mockRejectedValue(new Error('fail'));
      const consoleSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      render(<StreamSettingsForm active={true} />);
      fireEvent.click(screen.getByText('Rehash Streams'));

      await waitFor(() => {
        expect(consoleSpy).toHaveBeenCalled();
      });
      expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
      consoleSpy.mockRestore();
    });

    it('logs error when rehashStreams throws', async () => {
      setupMocks({ warningSuppressed: true });
      const error = new Error('network error');
      vi.mocked(rehashStreams).mockRejectedValue(error);
      const consoleSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      render(<StreamSettingsForm active={true} />);
      fireEvent.click(screen.getByText('Rehash Streams'));

      await waitFor(() => {
        expect(consoleSpy).toHaveBeenCalledWith(
          'Error rehashing streams:',
          error
        );
      });
      consoleSpy.mockRestore();
    });

    it('closes confirmation dialog when Cancel is clicked on rehash dialog', async () => {
      render(<StreamSettingsForm active={true} />);
      fireEvent.click(screen.getByText('Rehash Streams'));
      await waitFor(() => screen.getByTestId('confirmation-dialog'));
      fireEvent.click(screen.getByTestId('confirm-cancel'));

      await waitFor(() => {
        expect(
          screen.queryByTestId('confirmation-dialog')
        ).not.toBeInTheDocument();
      });
      expect(rehashStreams).not.toHaveBeenCalled();
    });

    it('calls suppressWarning when "Don\'t show again" is clicked', async () => {
      const suppressWarning = vi.fn();
      vi.mocked(useWarningsStore).mockImplementation((sel) =>
        sel({
          suppressWarning,
          isWarningSuppressed: vi.fn(() => false),
        })
      );
      render(<StreamSettingsForm active={true} />);
      fireEvent.click(screen.getByText('Rehash Streams'));
      await waitFor(() => screen.getByTestId('confirmation-dialog'));
      fireEvent.click(screen.getByTestId('confirm-suppress'));

      expect(suppressWarning).toHaveBeenCalledWith('rehash-streams');
    });

    it('Rehash Streams button is disabled while rehashing', async () => {
      let resolveRehash;
      vi.mocked(rehashStreams).mockReturnValue(
        new Promise((res) => {
          resolveRehash = res;
        })
      );
      setupMocks({ warningSuppressed: true });
      render(<StreamSettingsForm active={true} />);
      fireEvent.click(screen.getByText('Rehash Streams'));

      await waitFor(() => {
        expect(screen.getByText('Rehash Streams')).toBeDisabled();
      });

      resolveRehash();
      await waitFor(() => {
        expect(screen.getByText('Rehash Streams')).not.toBeDisabled();
      });
    });
  });

  // ── getInputProps wiring ───────────────────────────────────────────────────
  describe('getInputProps wiring', () => {
    it('calls getInputProps for default_user_agent', () => {
      render(<StreamSettingsForm active={true} />);
      expect(formMock.getInputProps).toHaveBeenCalledWith('default_user_agent');
    });

    it('calls getInputProps for default_stream_profile', () => {
      render(<StreamSettingsForm active={true} />);
      expect(formMock.getInputProps).toHaveBeenCalledWith(
        'default_stream_profile'
      );
    });

    it('calls getInputProps for preferred_region', () => {
      render(<StreamSettingsForm active={true} />);
      expect(formMock.getInputProps).toHaveBeenCalledWith('preferred_region');
    });

    it('calls getInputProps for auto_import_mapped_files with checkbox type', () => {
      render(<StreamSettingsForm active={true} />);
      expect(formMock.getInputProps).toHaveBeenCalledWith(
        'auto_import_mapped_files',
        { type: 'checkbox' }
      );
    });

    it('calls getInputProps for m3u_hash_key', () => {
      render(<StreamSettingsForm active={true} />);
      expect(formMock.getInputProps).toHaveBeenCalledWith('m3u_hash_key');
    });
  });
});
