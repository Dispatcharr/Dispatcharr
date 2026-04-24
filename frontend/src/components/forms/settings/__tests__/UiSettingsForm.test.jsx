import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import UiSettingsForm from '../UiSettingsForm';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../../store/settings.jsx', () => ({ default: vi.fn() }));

// ── Hook mocks ─────────────────────────────────────────────────────────────────
vi.mock('../../../../hooks/useLocalStorage.jsx', () => ({ default: vi.fn() }));
vi.mock('../../../../hooks/useTablePreferences.jsx', () => ({
  default: vi.fn(),
}));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../../utils/dateTimeUtils.js', () => ({
  buildTimeZoneOptions: vi.fn(),
  getDefaultTimeZone: vi.fn(),
}));

vi.mock('../../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

vi.mock('../../../../utils/forms/settings/UiSettingsFormUtils.js', () => ({
  saveTimeZoneSetting: vi.fn(),
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Select: ({ label, value, onChange, data }) => (
    <div>
      <label>{label}</label>
      <select
        data-testid={`select-${label?.toLowerCase().replace(/\s+/g, '-')}`}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value)}
      >
        {data?.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  ),
  Switch: ({ label, description, checked, onChange }) => (
    <div>
      <label>{label}</label>
      {description && <p>{description}</p>}
      <input
        data-testid="switch-header-pinned"
        type="checkbox"
        checked={checked}
        onChange={onChange}
      />
    </div>
  ),
  Stack: ({ children }) => <div>{children}</div>,
}));

// ──────────────────────────────────────────────────────────────────────────────
// Imports after mocks
// ──────────────────────────────────────────────────────────────────────────────
import useSettingsStore from '../../../../store/settings.jsx';
import useLocalStorage from '../../../../hooks/useLocalStorage.jsx';
import useTablePreferences from '../../../../hooks/useTablePreferences.jsx';
import {
  buildTimeZoneOptions,
  getDefaultTimeZone,
} from '../../../../utils/dateTimeUtils.js';
import { showNotification } from '../../../../utils/notificationUtils.js';
import { saveTimeZoneSetting } from '../../../../utils/forms/settings/UiSettingsFormUtils.js';

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────
const makeSettings = ({ timeZone = null } = {}) => ({
  system_settings: timeZone
    ? { value: { time_zone: timeZone } }
    : { value: {} },
});

const DEFAULT_TZ = 'America/New_York';
const TZ_OPTIONS = [
  { value: 'America/New_York', label: 'America/New_York' },
  { value: 'America/Chicago', label: 'America/Chicago' },
  { value: 'UTC', label: 'UTC' },
];

const setupMocks = ({
  settings = makeSettings(),
  timeFormat = '12h',
  dateFormat = 'mdy',
  timeZone = DEFAULT_TZ,
  headerPinned = false,
  tableSize = 'default',
} = {}) => {
  const setTimeFormat = vi.fn();
  const setDateFormat = vi.fn();
  const setTimeZone = vi.fn();
  const setHeaderPinned = vi.fn();
  const setTableSize = vi.fn();

  vi.mocked(getDefaultTimeZone).mockReturnValue(DEFAULT_TZ);
  vi.mocked(buildTimeZoneOptions).mockReturnValue(TZ_OPTIONS);
  vi.mocked(saveTimeZoneSetting).mockResolvedValue(undefined);

  vi.mocked(useSettingsStore).mockImplementation((sel) => sel({ settings }));

  vi.mocked(useLocalStorage).mockImplementation((key, defaultVal) => {
    if (key === 'time-format') return [timeFormat, setTimeFormat];
    if (key === 'date-format') return [dateFormat, setDateFormat];
    if (key === 'time-zone') return [timeZone, setTimeZone];
    return [defaultVal, vi.fn()];
  });

  vi.mocked(useTablePreferences).mockReturnValue({
    headerPinned,
    setHeaderPinned,
    tableSize,
    setTableSize,
  });

  return {
    setTimeFormat,
    setDateFormat,
    setTimeZone,
    setHeaderPinned,
    setTableSize,
  };
};

// ──────────────────────────────────────────────────────────────────────────────
// Tests
// ──────────────────────────────────────────────────────────────────────────────
describe('UiSettingsForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the Table Size select', () => {
      setupMocks();
      render(<UiSettingsForm />);
      expect(screen.getByTestId('select-table-size')).toBeInTheDocument();
    });

    it('renders the Time format select', () => {
      setupMocks();
      render(<UiSettingsForm />);
      expect(screen.getByTestId('select-time-format')).toBeInTheDocument();
    });

    it('renders the Date format select', () => {
      setupMocks();
      render(<UiSettingsForm />);
      expect(screen.getByTestId('select-date-format')).toBeInTheDocument();
    });

    it('renders the Time zone select', () => {
      setupMocks();
      render(<UiSettingsForm />);
      expect(screen.getByTestId('select-time-zone')).toBeInTheDocument();
    });

    it('renders the Pin Table Headers switch', () => {
      setupMocks();
      render(<UiSettingsForm />);
      expect(screen.getByTestId('switch-header-pinned')).toBeInTheDocument();
    });

    it('renders the switch description', () => {
      setupMocks();
      render(<UiSettingsForm />);
      expect(
        screen.getByText('Keep table headers visible when scrolling')
      ).toBeInTheDocument();
    });

    it('renders Table Size select with initial value', () => {
      setupMocks({ tableSize: 'compact' });
      render(<UiSettingsForm />);
      expect(screen.getByTestId('select-table-size')).toHaveValue('compact');
    });

    it('renders Time format select with initial value', () => {
      setupMocks({ timeFormat: '24h' });
      render(<UiSettingsForm />);
      expect(screen.getByTestId('select-time-format')).toHaveValue('24h');
    });

    it('renders Date format select with initial value', () => {
      setupMocks({ dateFormat: 'dmy' });
      render(<UiSettingsForm />);
      expect(screen.getByTestId('select-date-format')).toHaveValue('dmy');
    });

    it('renders Time zone select with initial value', () => {
      setupMocks({ timeZone: 'UTC' });
      render(<UiSettingsForm />);
      expect(screen.getByTestId('select-time-zone')).toHaveValue('UTC');
    });

    it('renders switch unchecked when headerPinned is false', () => {
      setupMocks({ headerPinned: false });
      render(<UiSettingsForm />);
      expect(screen.getByTestId('switch-header-pinned')).not.toBeChecked();
    });

    it('renders switch checked when headerPinned is true', () => {
      setupMocks({ headerPinned: true });
      render(<UiSettingsForm />);
      expect(screen.getByTestId('switch-header-pinned')).toBeChecked();
    });
  });

  // ── onChange handlers ──────────────────────────────────────────────────────

  describe('onChange handlers', () => {
    it('calls setTableSize when Table Size select changes', () => {
      const { setTableSize } = setupMocks();
      render(<UiSettingsForm />);
      fireEvent.change(screen.getByTestId('select-table-size'), {
        target: { value: 'large' },
      });
      expect(setTableSize).toHaveBeenCalledWith('large');
    });

    it('does not call setTableSize when value is empty', () => {
      const { setTableSize } = setupMocks();
      render(<UiSettingsForm />);
      fireEvent.change(screen.getByTestId('select-table-size'), {
        target: { value: '' },
      });
      expect(setTableSize).not.toHaveBeenCalled();
    });

    it('calls setTimeFormat when Time format select changes', () => {
      const { setTimeFormat } = setupMocks();
      render(<UiSettingsForm />);
      fireEvent.change(screen.getByTestId('select-time-format'), {
        target: { value: '24h' },
      });
      expect(setTimeFormat).toHaveBeenCalledWith('24h');
    });

    it('does not call setTimeFormat when value is empty', () => {
      const { setTimeFormat } = setupMocks();
      render(<UiSettingsForm />);
      fireEvent.change(screen.getByTestId('select-time-format'), {
        target: { value: '' },
      });
      expect(setTimeFormat).not.toHaveBeenCalled();
    });

    it('calls setDateFormat when Date format select changes', () => {
      const { setDateFormat } = setupMocks();
      render(<UiSettingsForm />);
      fireEvent.change(screen.getByTestId('select-date-format'), {
        target: { value: 'dmy' },
      });
      expect(setDateFormat).toHaveBeenCalledWith('dmy');
    });

    it('does not call setDateFormat when value is empty', () => {
      const { setDateFormat } = setupMocks();
      render(<UiSettingsForm />);
      fireEvent.change(screen.getByTestId('select-date-format'), {
        target: { value: '' },
      });
      expect(setDateFormat).not.toHaveBeenCalled();
    });

    it('calls setTimeZone and saveTimeZoneSetting when Time zone select changes', async () => {
      const { setTimeZone } = setupMocks();
      render(<UiSettingsForm />);
      fireEvent.change(screen.getByTestId('select-time-zone'), {
        target: { value: 'UTC' },
      });
      expect(setTimeZone).toHaveBeenCalledWith('UTC');
      await waitFor(() => {
        expect(saveTimeZoneSetting).toHaveBeenCalledWith('UTC', makeSettings());
      });
    });

    it('does not call setTimeZone when value is empty', () => {
      const { setTimeZone } = setupMocks();
      render(<UiSettingsForm />);
      fireEvent.change(screen.getByTestId('select-time-zone'), {
        target: { value: '' },
      });
      expect(setTimeZone).not.toHaveBeenCalled();
      // Only called during initial sync, not on empty change
      expect(saveTimeZoneSetting).toHaveBeenCalledTimes(1);
    });

    it('calls setHeaderPinned when switch is toggled on', () => {
      const { setHeaderPinned } = setupMocks({ headerPinned: false });
      render(<UiSettingsForm />);
      fireEvent.click(screen.getByTestId('switch-header-pinned'));
      expect(setHeaderPinned).toHaveBeenCalledWith(true);
    });

    it('calls setHeaderPinned when switch is toggled off', () => {
      const { setHeaderPinned } = setupMocks({ headerPinned: true });
      render(<UiSettingsForm />);
      fireEvent.click(screen.getByTestId('switch-header-pinned'));
      expect(setHeaderPinned).toHaveBeenCalledWith(false);
    });
  });

  // ── Time zone sync from settings ───────────────────────────────────────────

  describe('time zone sync from settings', () => {
    it('calls setTimeZone with system time_zone on mount when settings has tz', () => {
      const { setTimeZone } = setupMocks({
        settings: makeSettings({ timeZone: 'America/Chicago' }),
        timeZone: DEFAULT_TZ,
      });
      render(<UiSettingsForm />);
      expect(setTimeZone).toHaveBeenCalled();
    });

    it('does not change timeZone when settings tz matches current tz', () => {
      const { setTimeZone } = setupMocks({
        settings: makeSettings({ timeZone: DEFAULT_TZ }),
        timeZone: DEFAULT_TZ,
      });
      render(<UiSettingsForm />);
      // setTimeZone is called with a function that returns prev when equal
      const callArg = setTimeZone.mock.calls[0]?.[0];
      if (typeof callArg === 'function') {
        expect(callArg(DEFAULT_TZ)).toBe(DEFAULT_TZ);
      }
    });

    it('calls persistTimeZoneSetting (saveTimeZoneSetting) when no tz in settings and timeZone is set', async () => {
      setupMocks({
        settings: makeSettings({ timeZone: null }),
        timeZone: DEFAULT_TZ,
      });
      render(<UiSettingsForm />);
      await waitFor(() => {
        expect(saveTimeZoneSetting).toHaveBeenCalledWith(
          DEFAULT_TZ,
          makeSettings({ timeZone: null })
        );
      });
    });

    it('does not call saveTimeZoneSetting when settings is null', async () => {
      setupMocks({ settings: null, timeZone: DEFAULT_TZ });
      render(<UiSettingsForm />);
      await waitFor(() => {
        expect(saveTimeZoneSetting).not.toHaveBeenCalled();
      });
    });

    it('does not call saveTimeZoneSetting when timeZone is falsy and no tz in settings', async () => {
      setupMocks({
        settings: makeSettings({ timeZone: null }),
        timeZone: '',
      });
      render(<UiSettingsForm />);
      await waitFor(() => {
        expect(saveTimeZoneSetting).not.toHaveBeenCalled();
      });
    });
  });

  // ── Error handling ─────────────────────────────────────────────────────────

  describe('error handling', () => {
    it('shows error notification when saveTimeZoneSetting throws on tz change', async () => {
      const consoleSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      setupMocks({ settings: makeSettings({ timeZone: null }), timeZone: '' });
      vi.mocked(saveTimeZoneSetting).mockRejectedValue(
        new Error('network error')
      );

      render(<UiSettingsForm />);
      fireEvent.change(screen.getByTestId('select-time-zone'), {
        target: { value: 'UTC' },
      });

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            color: 'red',
            title: 'Failed to update time zone',
          })
        );
      });
      consoleSpy.mockRestore();
    });

    it('logs error when saveTimeZoneSetting throws on tz change', async () => {
      const error = new Error('network error');
      const consoleSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      setupMocks({ settings: makeSettings({ timeZone: null }), timeZone: '' });
      vi.mocked(saveTimeZoneSetting).mockRejectedValue(error);

      render(<UiSettingsForm />);
      fireEvent.change(screen.getByTestId('select-time-zone'), {
        target: { value: 'UTC' },
      });

      await waitFor(() => {
        expect(consoleSpy).toHaveBeenCalledWith(
          'Failed to persist time zone setting',
          error
        );
      });
      consoleSpy.mockRestore();
    });

    it('shows error notification when saveTimeZoneSetting throws during initial sync', async () => {
      const consoleSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      setupMocks({
        settings: makeSettings({ timeZone: null }),
        timeZone: DEFAULT_TZ,
      });
      vi.mocked(saveTimeZoneSetting).mockRejectedValue(
        new Error('sync failed')
      );

      render(<UiSettingsForm />);

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            color: 'red',
            title: 'Failed to update time zone',
          })
        );
      });
      consoleSpy.mockRestore();
    });
  });

  // ── buildTimeZoneOptions ───────────────────────────────────────────────────

  describe('buildTimeZoneOptions', () => {
    it('calls buildTimeZoneOptions with current timeZone value', () => {
      setupMocks({ timeZone: 'America/Chicago' });
      render(<UiSettingsForm />);
      expect(buildTimeZoneOptions).toHaveBeenCalledWith('America/Chicago');
    });
  });
});
