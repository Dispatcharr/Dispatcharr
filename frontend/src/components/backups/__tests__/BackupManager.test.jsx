import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import BackupManager from '../BackupManager';

// ── BackupManagerUtils ─────────────────────────────────────────────────────────
vi.mock('../../../utils/components/backups/BackupManagerUtils.js', () => ({
  listBackups: vi.fn(),
  getBackupSchedule: vi.fn(),
  updateBackupSchedule: vi.fn(),
  createBackup: vi.fn(),
  uploadBackup: vi.fn(),
  downloadBackup: vi.fn(),
  restoreBackup: vi.fn(),
  deleteBackup: vi.fn(),
  to12Hour: vi.fn(),
  to24Hour: vi.fn(),
  DAYS_OF_WEEK: [
    { value: '0', label: 'Sunday' },
    { value: '1', label: 'Monday' },
    { value: '2', label: 'Tuesday' },
    { value: '3', label: 'Wednesday' },
    { value: '4', label: 'Thursday' },
    { value: '5', label: 'Friday' },
    { value: '6', label: 'Saturday' },
  ],
}));

// ── hooks ──────────────────────────────────────────────────────────────────────
vi.mock('../../../hooks/useLocalStorage', () => ({
  default: vi.fn(() => ['UTC', vi.fn()]),
}));

// ── store ──────────────────────────────────────────────────────────────────────
vi.mock('../../../store/warnings', () => ({
  default: vi.fn((sel) => sel({ suppressWarning: vi.fn() })),
}));

// ── dateTimeUtils ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/dateTimeUtils.js', () => ({
  format: vi.fn(() => '01/01/2024, 10:00:00 AM'),
  getDefaultTimeZone: vi.fn(() => 'UTC'),
  useDateTimeFormat: vi.fn(() => ({
    fullDateTimeFormat: 'MM/DD/YYYY, HH:mm:ss',
    timeFormatSetting: '24h',
  })),
}));

// ── utility functions ──────────────────────────────────────────────────────────
vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));
vi.mock('../../../utils/networkUtils.js', () => ({
  formatBytes: vi.fn((bytes) => `${bytes} B`),
}));
vi.mock('../../../utils/cronUtils', () => ({
  validateCronExpression: vi.fn(() => ({ valid: true })),
}));

// ── CustomTable ────────────────────────────────────────────────────────────────
vi.mock('../../tables/CustomTable', () => ({
  CustomTable: ({ table }) => (
    <div data-testid="custom-table">
      {table.__rows?.map((row, i) => (
        <div key={i} data-testid="table-row">
          {table.__bodyCellRenderFns?.actions?.({
            cell: { column: { id: 'actions' } },
            row,
          })}
        </div>
      ))}
    </div>
  ),
  useTable: vi.fn(({ data, bodyCellRenderFns }) => ({
    __rows: (data ?? []).map((item) => ({ original: item })),
    __bodyCellRenderFns: bodyCellRenderFns,
  })),
}));

// ── ScheduleInput ──────────────────────────────────────────────────────────────
vi.mock('../../forms/ScheduleInput', () => ({
  default: ({
    children,
    scheduleType,
    onScheduleTypeChange,
    cronValue,
    onCronChange,
    disabled,
  }) => (
    <div data-testid="schedule-input">
      {scheduleType === 'cron' ? (
        <>
          <label>
            Cron Expression
            <input
              data-testid="cron-input"
              value={cronValue ?? ''}
              onChange={(e) => onCronChange?.(e.target.value)}
            />
          </label>
          <button
            data-testid="switch-to-interval"
            onClick={() => onScheduleTypeChange?.('interval')}
          >
            Use simple schedule
          </button>
        </>
      ) : (
        <>
          {children}
          {!disabled && (
            <button
              data-testid="switch-to-cron"
              onClick={() => onScheduleTypeChange?.('cron')}
            >
              Use custom cron schedule
            </button>
          )}
        </>
      )}
    </div>
  ),
}));

// ── ConfirmationDialog ─────────────────────────────────────────────────────────
vi.mock('../../ConfirmationDialog', () => ({
  default: ({
    opened,
    onClose,
    onConfirm,
    title,
    message,
    confirmLabel,
    cancelLabel,
    loading,
  }) =>
    opened ? (
      <div data-testid="confirmation-dialog">
        <div data-testid="dialog-title">{title}</div>
        <div data-testid="dialog-message">{message}</div>
        <button
          data-testid="dialog-confirm"
          onClick={onConfirm}
          disabled={loading}
        >
          {confirmLabel}
        </button>
        <button
          data-testid="dialog-cancel"
          onClick={onClose}
          disabled={loading}
        >
          {cancelLabel}
        </button>
      </div>
    ) : null,
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  Download: () => <svg data-testid="icon-download" />,
  RefreshCcw: () => <svg data-testid="icon-refresh" />,
  RotateCcw: () => <svg data-testid="icon-restore" />,
  SquareMinus: () => <svg data-testid="icon-delete" />,
  SquarePlus: () => <svg data-testid="icon-create" />,
  UploadCloud: () => <svg data-testid="icon-upload" />,
}));

// ── @mantine/core ──────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  ActionIcon: ({ children, onClick, color, loading, disabled }) => (
    <button
      data-testid="action-icon"
      data-color={color}
      onClick={onClick}
      disabled={!!(disabled || loading)}
    >
      {children}
    </button>
  ),
  Box: ({ children, style }) => <div style={style}>{children}</div>,
  Button: ({ children, onClick, disabled, loading, color, variant }) => (
    <button
      onClick={onClick}
      disabled={!!(disabled || loading)}
      data-color={color}
      data-variant={variant}
    >
      {children}
    </button>
  ),
  FileInput: ({ onChange, label, accept }) => (
    <label>
      {label}
      <input
        type="file"
        data-testid="file-input"
        accept={accept}
        onChange={(e) => onChange?.(e.target.files?.[0] ?? null)}
      />
    </label>
  ),
  Flex: ({ children }) => <div>{children}</div>,
  Group: ({ children }) => <div>{children}</div>,
  Loader: ({ size }) => <div data-testid="loader" data-size={size} />,
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
  NumberInput: ({ value, onChange, label, description, min, disabled }) => (
    <label>
      {label}
      <input
        type="number"
        data-testid="number-input"
        value={value ?? ''}
        min={min}
        disabled={disabled}
        onChange={(e) => onChange?.(Number(e.target.value))}
      />
      {description && <span>{description}</span>}
    </label>
  ),
  Paper: ({ children }) => <div>{children}</div>,
  Select: ({ value, onChange, label, data, disabled }) => (
    <label>
      {label}
      <select
        value={value ?? ''}
        disabled={disabled}
        onChange={(e) => onChange?.(e.target.value)}
      >
        {(data ?? []).map((item) =>
          typeof item === 'string' ? (
            <option key={item} value={item}>
              {item}
            </option>
          ) : (
            <option
              key={item.value}
              value={item.value}
              disabled={item.disabled}
            >
              {item.label}
            </option>
          )
        )}
      </select>
    </label>
  ),
  Stack: ({ children }) => <div>{children}</div>,
  Switch: ({ checked, onChange, label, disabled }) => (
    <label>
      <input
        type="checkbox"
        data-testid="schedule-switch"
        checked={checked}
        disabled={disabled}
        onChange={(e) =>
          onChange?.({ currentTarget: { checked: e.target.checked } })
        }
      />
      {label}
    </label>
  ),
  Text: ({ children, size, c, style }) => (
    <span data-size={size} data-color={c} style={style}>
      {children}
    </span>
  ),
  Tooltip: ({ children, label }) => <div data-tooltip={label}>{children}</div>,
}));

// ── imports after mocks ────────────────────────────────────────────────────────
import {
  listBackups,
  getBackupSchedule,
  updateBackupSchedule,
  createBackup,
  uploadBackup,
  downloadBackup,
  restoreBackup,
  deleteBackup,
  to12Hour,
  to24Hour,
} from '../../../utils/components/backups/BackupManagerUtils.js';
import { showNotification } from '../../../utils/notificationUtils.js';
import { useDateTimeFormat } from '../../../utils/dateTimeUtils.js';

// ── fixtures ───────────────────────────────────────────────────────────────────
const defaultSchedule = {
  enabled: true,
  frequency: 'daily',
  time: '03:00',
  day_of_week: 0,
  retention_count: 5,
  cron_expression: '',
};

const defaultBackups = [
  {
    name: 'backup-2024-01-01.zip',
    size: 1024000,
    created: '2024-01-01T10:00:00Z',
  },
  {
    name: 'backup-2024-01-02.zip',
    size: 2048000,
    created: '2024-01-02T10:00:00Z',
  },
];

const setupMocks = ({ schedule = defaultSchedule, backups = [] } = {}) => {
  vi.mocked(listBackups).mockResolvedValue(backups);
  vi.mocked(getBackupSchedule).mockResolvedValue(schedule);
  vi.mocked(updateBackupSchedule).mockResolvedValue({ ...schedule });
  vi.mocked(createBackup).mockResolvedValue({});
  vi.mocked(uploadBackup).mockResolvedValue({});
  vi.mocked(downloadBackup).mockResolvedValue({});
  vi.mocked(restoreBackup).mockResolvedValue({});
  vi.mocked(deleteBackup).mockResolvedValue({});
  vi.mocked(to12Hour).mockReturnValue({ time: '3:00', period: 'AM' });
  vi.mocked(to24Hour).mockReturnValue('03:00');
};

/**
 * Render BackupManager and wait for both initial API calls to settle.
 * `to12Hour` is called inside `loadSchedule` after `getBackupSchedule` resolves,
 * so its first invocation is a reliable "initial load complete" indicator.
 */
const renderAndLoad = async (opts = {}) => {
  setupMocks(opts);
  render(<BackupManager />);
  await waitFor(() => expect(vi.mocked(to12Hour)).toHaveBeenCalled());
};

// ─────────────────────────────────────────────────────────────────────────────

describe('BackupManager', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(window, 'location', {
      configurable: true,
      writable: true,
      value: { reload: vi.fn() },
    });
  });

  // ── Initial render and data loading ────────────────────────────────────────

  describe('initial data loading', () => {
    it('renders "Scheduled Backups" heading', async () => {
      await renderAndLoad();
      expect(screen.getByText('Scheduled Backups')).toBeInTheDocument();
    });

    it('calls listBackups on mount', async () => {
      await renderAndLoad();
      expect(vi.mocked(listBackups)).toHaveBeenCalledTimes(1);
    });

    it('calls getBackupSchedule on mount', async () => {
      await renderAndLoad();
      expect(vi.mocked(getBackupSchedule)).toHaveBeenCalledTimes(1);
    });

    it('calls to12Hour with the loaded schedule time', async () => {
      await renderAndLoad();
      expect(vi.mocked(to12Hour)).toHaveBeenCalledWith(defaultSchedule.time);
    });

    it('sets scheduleType to "cron" when loaded schedule has a cron_expression', async () => {
      await renderAndLoad({
        schedule: { ...defaultSchedule, cron_expression: '0 3 * * *' },
      });
      expect(screen.getByTestId('cron-input')).toBeInTheDocument();
    });

    it('sets scheduleType to "interval" when loaded schedule has no cron_expression', async () => {
      await renderAndLoad();
      expect(screen.getByTestId('switch-to-cron')).toBeInTheDocument();
    });

    it('handles getBackupSchedule failure silently without showing a notification', async () => {
      vi.mocked(getBackupSchedule).mockRejectedValue(
        new Error('Network error')
      );
      vi.mocked(listBackups).mockResolvedValue([]);
      vi.mocked(to12Hour).mockReturnValue({ time: '3:00', period: 'AM' });
      render(<BackupManager />);
      await waitFor(() => expect(vi.mocked(listBackups)).toHaveBeenCalled());
      expect(vi.mocked(showNotification)).not.toHaveBeenCalled();
    });

    it('shows an error notification when listBackups fails', async () => {
      vi.mocked(listBackups).mockRejectedValue(new Error('Failed'));
      vi.mocked(getBackupSchedule).mockResolvedValue(defaultSchedule);
      vi.mocked(to12Hour).mockReturnValue({ time: '3:00', period: 'AM' });
      render(<BackupManager />);
      await waitFor(() =>
        expect(vi.mocked(showNotification)).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Error', color: 'red' })
        )
      );
    });
  });

  // ── Backup list display ─────────────────────────────────────────────────────

  describe('backup list display', () => {
    it('shows "No backups found" when list is empty', async () => {
      await renderAndLoad({ backups: [] });
      expect(screen.getByText(/No backups found/)).toBeInTheDocument();
    });

    it('renders CustomTable when backups are present', async () => {
      await renderAndLoad({ backups: defaultBackups });
      expect(screen.getByTestId('custom-table')).toBeInTheDocument();
    });

    it('renders one table row per backup', async () => {
      await renderAndLoad({ backups: defaultBackups });
      expect(screen.getAllByTestId('table-row')).toHaveLength(
        defaultBackups.length
      );
    });

    it('does not render CustomTable when list is empty', async () => {
      await renderAndLoad({ backups: [] });
      expect(screen.queryByTestId('custom-table')).not.toBeInTheDocument();
    });
  });

  // ── Create backup ───────────────────────────────────────────────────────────

  describe('create backup', () => {
    it('calls createBackup when "Create Backup" button is clicked', async () => {
      await renderAndLoad();
      fireEvent.click(screen.getByText('Create Backup'));
      await waitFor(() =>
        expect(vi.mocked(createBackup)).toHaveBeenCalledTimes(1)
      );
    });

    it('shows success notification after creating backup', async () => {
      await renderAndLoad();
      fireEvent.click(screen.getByText('Create Backup'));
      await waitFor(() =>
        expect(vi.mocked(showNotification)).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Success', color: 'green' })
        )
      );
    });

    it('refreshes backup list after creating backup', async () => {
      await renderAndLoad();
      vi.mocked(listBackups).mockClear();
      fireEvent.click(screen.getByText('Create Backup'));
      await waitFor(() =>
        expect(vi.mocked(listBackups)).toHaveBeenCalledTimes(1)
      );
    });

    it('shows error notification when createBackup fails', async () => {
      await renderAndLoad();
      vi.mocked(createBackup).mockRejectedValue(new Error('Server error'));
      fireEvent.click(screen.getByText('Create Backup'));
      await waitFor(() =>
        expect(vi.mocked(showNotification)).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Error', color: 'red' })
        )
      );
    });
  });

  // ── Refresh ─────────────────────────────────────────────────────────────────

  describe('refresh', () => {
    it('calls listBackups again when Refresh is clicked', async () => {
      await renderAndLoad();
      vi.mocked(listBackups).mockClear();
      fireEvent.click(screen.getByText('Refresh'));
      await waitFor(() =>
        expect(vi.mocked(listBackups)).toHaveBeenCalledTimes(1)
      );
    });
  });

  // ── Download backup ─────────────────────────────────────────────────────────

  describe('download backup', () => {
    it('calls downloadBackup with the correct filename', async () => {
      await renderAndLoad({ backups: defaultBackups });
      const downloadBtn = screen
        .getAllByTestId('icon-download')[0]
        .closest('button');
      fireEvent.click(downloadBtn);
      await waitFor(() =>
        expect(vi.mocked(downloadBackup)).toHaveBeenCalledWith(
          defaultBackups[0].name
        )
      );
    });

    it('shows "Download Started" notification', async () => {
      await renderAndLoad({ backups: defaultBackups });
      const downloadBtn = screen
        .getAllByTestId('icon-download')[0]
        .closest('button');
      fireEvent.click(downloadBtn);
      await waitFor(() =>
        expect(vi.mocked(showNotification)).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Download Started', color: 'blue' })
        )
      );
    });

    it('shows error notification when downloadBackup fails', async () => {
      await renderAndLoad({ backups: defaultBackups });
      vi.mocked(downloadBackup).mockRejectedValue(new Error('Network error'));
      const downloadBtn = screen
        .getAllByTestId('icon-download')[0]
        .closest('button');
      fireEvent.click(downloadBtn);
      await waitFor(() =>
        expect(vi.mocked(showNotification)).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Error', color: 'red' })
        )
      );
    });
  });

  // ── Delete backup ───────────────────────────────────────────────────────────

  describe('delete backup', () => {
    const openDeleteDialog = async () => {
      await renderAndLoad({ backups: defaultBackups });
      const deleteBtn = screen
        .getAllByTestId('icon-delete')[0]
        .closest('button');
      fireEvent.click(deleteBtn);
    };

    it('opens delete ConfirmationDialog when delete action is clicked', async () => {
      await openDeleteDialog();
      expect(screen.getByTestId('dialog-title')).toHaveTextContent(
        'Delete Backup'
      );
    });

    it('shows the backup filename in the delete dialog message', async () => {
      await openDeleteDialog();
      expect(screen.getByTestId('dialog-message')).toHaveTextContent(
        defaultBackups[0].name
      );
    });

    it('calls deleteBackup with the filename when confirmed', async () => {
      await openDeleteDialog();
      fireEvent.click(screen.getByTestId('dialog-confirm'));
      await waitFor(() =>
        expect(vi.mocked(deleteBackup)).toHaveBeenCalledWith(
          defaultBackups[0].name
        )
      );
    });

    it('refreshes backup list after deletion', async () => {
      await openDeleteDialog();
      vi.mocked(listBackups).mockClear();
      fireEvent.click(screen.getByTestId('dialog-confirm'));
      await waitFor(() =>
        expect(vi.mocked(listBackups)).toHaveBeenCalledTimes(1)
      );
    });

    it('closes dialog after confirming deletion', async () => {
      await openDeleteDialog();
      fireEvent.click(screen.getByTestId('dialog-confirm'));
      await waitFor(() =>
        expect(
          screen.queryByTestId('confirmation-dialog')
        ).not.toBeInTheDocument()
      );
    });

    it('closes dialog when Cancel is clicked', async () => {
      await openDeleteDialog();
      fireEvent.click(screen.getByTestId('dialog-cancel'));
      expect(
        screen.queryByTestId('confirmation-dialog')
      ).not.toBeInTheDocument();
    });

    it('shows error notification when deleteBackup fails', async () => {
      await openDeleteDialog();
      vi.mocked(deleteBackup).mockRejectedValue(new Error('Server error'));
      fireEvent.click(screen.getByTestId('dialog-confirm'));
      await waitFor(() =>
        expect(vi.mocked(showNotification)).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Error', color: 'red' })
        )
      );
    });
  });

  // ── Restore backup ──────────────────────────────────────────────────────────

  describe('restore backup', () => {
    const openRestoreDialog = async () => {
      await renderAndLoad({ backups: defaultBackups });
      const restoreBtn = screen
        .getAllByTestId('icon-restore')[0]
        .closest('button');
      fireEvent.click(restoreBtn);
    };

    it('opens restore ConfirmationDialog when restore action is clicked', async () => {
      await openRestoreDialog();
      expect(screen.getByTestId('dialog-title')).toHaveTextContent(
        'Restore Backup'
      );
    });

    it('shows the backup filename in the restore dialog message', async () => {
      await openRestoreDialog();
      expect(screen.getByTestId('dialog-message')).toHaveTextContent(
        defaultBackups[0].name
      );
    });

    it('calls restoreBackup with the filename when confirmed', async () => {
      await openRestoreDialog();
      fireEvent.click(screen.getByTestId('dialog-confirm'));
      await waitFor(() =>
        expect(vi.mocked(restoreBackup)).toHaveBeenCalledWith(
          defaultBackups[0].name
        )
      );
    });

    it('shows "Restore Complete" notification after successful restore', async () => {
      await openRestoreDialog();
      fireEvent.click(screen.getByTestId('dialog-confirm'));
      await waitFor(() =>
        expect(vi.mocked(showNotification)).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Restore Complete', color: 'green' })
        )
      );
    });

    it('schedules window.location.reload 4 seconds after restore', async () => {
      const setTimeoutSpy = vi.spyOn(globalThis, 'setTimeout');
      await openRestoreDialog();
      fireEvent.click(screen.getByTestId('dialog-confirm'));
      await waitFor(() => expect(vi.mocked(restoreBackup)).toHaveBeenCalled());
      expect(setTimeoutSpy).toHaveBeenCalledWith(expect.any(Function), 4000);
      setTimeoutSpy.mockRestore();
    });

    it('closes dialog when Cancel is clicked', async () => {
      await openRestoreDialog();
      fireEvent.click(screen.getByTestId('dialog-cancel'));
      expect(
        screen.queryByTestId('confirmation-dialog')
      ).not.toBeInTheDocument();
    });

    it('shows error notification when restoreBackup fails', async () => {
      await openRestoreDialog();
      vi.mocked(restoreBackup).mockRejectedValue(new Error('Restore failed'));
      fireEvent.click(screen.getByTestId('dialog-confirm'));
      await waitFor(() =>
        expect(vi.mocked(showNotification)).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Error', color: 'red' })
        )
      );
    });
  });

  // ── Upload backup ───────────────────────────────────────────────────────────

  describe('upload backup', () => {
    it('opens upload modal when Upload button is clicked', async () => {
      await renderAndLoad();
      fireEvent.click(screen.getByText('Upload'));
      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'Upload Backup'
      );
    });

    it('closes upload modal when × is clicked', async () => {
      await renderAndLoad();
      fireEvent.click(screen.getByText('Upload'));
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('closes upload modal when Cancel is clicked', async () => {
      await renderAndLoad();
      fireEvent.click(screen.getByText('Upload'));
      fireEvent.click(screen.getByText('Cancel'));
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('submit Upload button is disabled when no file is selected', async () => {
      await renderAndLoad();
      fireEvent.click(screen.getByText('Upload'));
      // First "Upload" opens the modal; second is the submit button inside the modal
      const submitBtn = screen.getAllByText('Upload')[1];
      expect(submitBtn).toBeDisabled();
    });

    it('calls uploadBackup with the selected file when submitted', async () => {
      await renderAndLoad();
      fireEvent.click(screen.getByText('Upload'));

      const file = new File(['backup data'], 'backup.zip', {
        type: 'application/zip',
      });
      const fileInput = screen.getByTestId('file-input');
      Object.defineProperty(fileInput, 'files', {
        value: [file],
        configurable: true,
      });
      fireEvent.change(fileInput);

      fireEvent.click(screen.getAllByText('Upload')[1]);
      await waitFor(() =>
        expect(vi.mocked(uploadBackup)).toHaveBeenCalledWith(file)
      );
    });

    it('closes modal and refreshes list after successful upload', async () => {
      await renderAndLoad();
      fireEvent.click(screen.getByText('Upload'));

      const file = new File(['data'], 'backup.zip', {
        type: 'application/zip',
      });
      const fileInput = screen.getByTestId('file-input');
      Object.defineProperty(fileInput, 'files', {
        value: [file],
        configurable: true,
      });
      fireEvent.change(fileInput);

      vi.mocked(listBackups).mockClear();
      fireEvent.click(screen.getAllByText('Upload')[1]);

      await waitFor(() => {
        expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
        expect(vi.mocked(listBackups)).toHaveBeenCalledTimes(1);
      });
    });

    it('shows success notification after upload', async () => {
      await renderAndLoad();
      fireEvent.click(screen.getByText('Upload'));

      const file = new File(['data'], 'backup.zip', {
        type: 'application/zip',
      });
      const fileInput = screen.getByTestId('file-input');
      Object.defineProperty(fileInput, 'files', {
        value: [file],
        configurable: true,
      });
      fireEvent.change(fileInput);
      fireEvent.click(screen.getAllByText('Upload')[1]);

      await waitFor(() =>
        expect(vi.mocked(showNotification)).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Success', color: 'green' })
        )
      );
    });

    it('shows error notification when uploadBackup fails', async () => {
      await renderAndLoad();
      vi.mocked(uploadBackup).mockRejectedValue(new Error('Upload failed'));
      fireEvent.click(screen.getByText('Upload'));

      const file = new File(['data'], 'backup.zip', {
        type: 'application/zip',
      });
      const fileInput = screen.getByTestId('file-input');
      Object.defineProperty(fileInput, 'files', {
        value: [file],
        configurable: true,
      });
      fireEvent.change(fileInput);
      fireEvent.click(screen.getAllByText('Upload')[1]);

      await waitFor(() =>
        expect(vi.mocked(showNotification)).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Error', color: 'red' })
        )
      );
    });
  });

  // ── Schedule saving ─────────────────────────────────────────────────────────

  describe('schedule saving', () => {
    it('Save button is disabled before any schedule field changes', async () => {
      await renderAndLoad();
      expect(screen.getByText('Save')).toBeDisabled();
    });

    it('Save button becomes enabled after a schedule field changes', async () => {
      await renderAndLoad();
      fireEvent.change(screen.getByLabelText('Frequency'), {
        target: { value: 'weekly' },
      });
      expect(screen.getByText('Save')).not.toBeDisabled();
    });

    it('calls updateBackupSchedule when Save is clicked', async () => {
      await renderAndLoad();
      fireEvent.change(screen.getByLabelText('Frequency'), {
        target: { value: 'weekly' },
      });
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() =>
        expect(vi.mocked(updateBackupSchedule)).toHaveBeenCalledTimes(1)
      );
    });

    it('sends schedule with an empty cron_expression in interval mode', async () => {
      await renderAndLoad();
      fireEvent.change(screen.getByLabelText('Frequency'), {
        target: { value: 'weekly' },
      });
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() =>
        expect(vi.mocked(updateBackupSchedule)).toHaveBeenCalledWith(
          expect.objectContaining({ cron_expression: '' })
        )
      );
    });

    it('sends schedule with cron_expression intact in cron mode', async () => {
      await renderAndLoad({
        schedule: { ...defaultSchedule, cron_expression: '0 3 * * *' },
      });
      fireEvent.change(screen.getByTestId('cron-input'), {
        target: { value: '0 4 * * *' },
      });
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() =>
        expect(vi.mocked(updateBackupSchedule)).toHaveBeenCalledWith(
          expect.objectContaining({ cron_expression: '0 4 * * *' })
        )
      );
    });

    it('shows success notification after saving schedule', async () => {
      await renderAndLoad();
      fireEvent.change(screen.getByLabelText('Frequency'), {
        target: { value: 'weekly' },
      });
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() =>
        expect(vi.mocked(showNotification)).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Success',
            message: 'Backup schedule saved',
          })
        )
      );
    });

    it('shows error notification when saving schedule fails', async () => {
      await renderAndLoad();
      vi.mocked(updateBackupSchedule).mockRejectedValue(
        new Error('Save failed')
      );
      fireEvent.change(screen.getByLabelText('Frequency'), {
        target: { value: 'weekly' },
      });
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() =>
        expect(vi.mocked(showNotification)).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Error', color: 'red' })
        )
      );
    });

    it('Save button is disabled again after a successful save', async () => {
      await renderAndLoad();
      fireEvent.change(screen.getByLabelText('Frequency'), {
        target: { value: 'weekly' },
      });
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() =>
        expect(vi.mocked(updateBackupSchedule)).toHaveBeenCalled()
      );
      await waitFor(() => expect(screen.getByText('Save')).toBeDisabled());
    });
  });

  // ── Schedule enabled switch ─────────────────────────────────────────────────

  describe('schedule enabled switch', () => {
    it('shows "Enabled" label when schedule.enabled is true', async () => {
      await renderAndLoad({
        schedule: { ...defaultSchedule, enabled: true },
      });
      expect(screen.getByText('Enabled')).toBeInTheDocument();
    });

    it('shows "Disabled" label when schedule.enabled is false', async () => {
      await renderAndLoad({
        schedule: { ...defaultSchedule, enabled: false },
      });
      expect(screen.getByText('Disabled')).toBeInTheDocument();
    });

    it('toggles label from "Enabled" to "Disabled" when switch is unchecked', async () => {
      await renderAndLoad({
        schedule: { ...defaultSchedule, enabled: true },
      });
      fireEvent.click(screen.getByTestId('schedule-switch'));
      await waitFor(() =>
        expect(screen.getByText('Disabled')).toBeInTheDocument()
      );
    });

    it('toggles label from "Disabled" to "Enabled" when switch is checked', async () => {
      await renderAndLoad({
        schedule: { ...defaultSchedule, enabled: false },
      });
      fireEvent.click(screen.getByTestId('schedule-switch'));
      await waitFor(() =>
        expect(screen.getByText('Enabled')).toBeInTheDocument()
      );
    });
  });

  // ── 12-hour vs 24-hour time display ─────────────────────────────────────────

  describe('time format display', () => {
    it('shows Hour, Minute, and Period selects in 12h mode', async () => {
      vi.mocked(useDateTimeFormat).mockReturnValue({
        fullDateTimeFormat: 'MM/DD/YYYY, h:mm:ss A',
        timeFormatSetting: '12h',
      });
      setupMocks();
      render(<BackupManager />);
      await waitFor(() => expect(vi.mocked(to12Hour)).toHaveBeenCalled());

      expect(screen.getByLabelText('Hour')).toBeInTheDocument();
      expect(screen.getByLabelText('Minute')).toBeInTheDocument();
      expect(screen.getByLabelText('Period')).toBeInTheDocument();
    });

    it('does not show a Period select in 24h mode', async () => {
      vi.mocked(useDateTimeFormat).mockReturnValue({
        fullDateTimeFormat: 'MM/DD/YYYY, HH:mm:ss',
        timeFormatSetting: '24h',
      });
      await renderAndLoad();
      expect(screen.queryByLabelText('Period')).not.toBeInTheDocument();
    });

    it('Hour select in 24h mode contains 24 options (00–23)', async () => {
      vi.mocked(useDateTimeFormat).mockReturnValue({
        fullDateTimeFormat: 'MM/DD/YYYY, HH:mm:ss',
        timeFormatSetting: '24h',
      });
      await renderAndLoad();
      const hourSelect = screen.getByLabelText('Hour');
      expect(hourSelect.querySelectorAll('option')).toHaveLength(24);
    });

    it('Hour select in 12h mode contains 12 options (1–12)', async () => {
      vi.mocked(useDateTimeFormat).mockReturnValue({
        fullDateTimeFormat: 'MM/DD/YYYY, h:mm:ss A',
        timeFormatSetting: '12h',
      });
      setupMocks();
      render(<BackupManager />);
      await waitFor(() => expect(vi.mocked(to12Hour)).toHaveBeenCalled());

      const hourSelect = screen.getByLabelText('Hour');
      expect(hourSelect.querySelectorAll('option')).toHaveLength(12);
    });

    it('Minute select contains 60 options (00–59)', async () => {
      await renderAndLoad();
      const minuteSelect = screen.getByLabelText('Minute');
      expect(minuteSelect.querySelectorAll('option')).toHaveLength(60);
    });
  });

  // ── Weekly frequency / Day selector ─────────────────────────────────────────

  describe('weekly frequency', () => {
    it('shows Day select when frequency is "weekly"', async () => {
      await renderAndLoad({
        schedule: { ...defaultSchedule, frequency: 'weekly' },
      });
      expect(screen.getByLabelText('Day')).toBeInTheDocument();
    });

    it('does not show Day select when frequency is "daily"', async () => {
      await renderAndLoad({
        schedule: { ...defaultSchedule, frequency: 'daily' },
      });
      expect(screen.queryByLabelText('Day')).not.toBeInTheDocument();
    });

    it('shows Day select after switching from daily to weekly', async () => {
      await renderAndLoad({
        schedule: { ...defaultSchedule, frequency: 'daily' },
      });
      fireEvent.change(screen.getByLabelText('Frequency'), {
        target: { value: 'weekly' },
      });
      expect(screen.getByLabelText('Day')).toBeInTheDocument();
    });

    it('hides Day select after switching from weekly to daily', async () => {
      await renderAndLoad({
        schedule: { ...defaultSchedule, frequency: 'weekly' },
      });
      fireEvent.change(screen.getByLabelText('Frequency'), {
        target: { value: 'daily' },
      });
      expect(screen.queryByLabelText('Day')).not.toBeInTheDocument();
    });

    it('Day select contains all 7 days of the week', async () => {
      await renderAndLoad({
        schedule: { ...defaultSchedule, frequency: 'weekly' },
      });
      expect(
        screen.getByLabelText('Day').querySelectorAll('option')
      ).toHaveLength(7);
    });
  });

  // ── Timezone info text ───────────────────────────────────────────────────────

  describe('timezone info text', () => {
    it('shows timezone info when schedule is enabled and in interval mode', async () => {
      await renderAndLoad({
        schedule: { ...defaultSchedule, enabled: true, cron_expression: '' },
      });
      expect(screen.getByText(/System Timezone/)).toBeInTheDocument();
    });

    it('does not show timezone info when schedule is disabled', async () => {
      await renderAndLoad({
        schedule: { ...defaultSchedule, enabled: false, cron_expression: '' },
      });
      expect(screen.queryByText(/System Timezone/)).not.toBeInTheDocument();
    });

    it('does not show timezone info in cron mode', async () => {
      await renderAndLoad({
        schedule: {
          ...defaultSchedule,
          enabled: true,
          cron_expression: '0 3 * * *',
        },
      });
      expect(screen.queryByText(/System Timezone/)).not.toBeInTheDocument();
    });

    it('includes the user timezone string in the info text', async () => {
      await renderAndLoad({
        schedule: { ...defaultSchedule, enabled: true, cron_expression: '' },
      });
      // useLocalStorage mock returns 'UTC'
      expect(screen.getByText(/UTC/)).toBeInTheDocument();
    });
  });

  // ── Schedule type switching ──────────────────────────────────────────────────

  describe('schedule type switching', () => {
    it('switches to cron mode when "Use custom cron schedule" is clicked', async () => {
      await renderAndLoad();
      fireEvent.click(screen.getByTestId('switch-to-cron'));
      expect(screen.getByTestId('cron-input')).toBeInTheDocument();
    });

    it('switches back to interval mode when "Use simple schedule" is clicked', async () => {
      await renderAndLoad({
        schedule: { ...defaultSchedule, cron_expression: '0 3 * * *' },
      });
      fireEvent.click(screen.getByTestId('switch-to-interval'));
      expect(screen.queryByTestId('cron-input')).not.toBeInTheDocument();
      expect(screen.getByTestId('switch-to-cron')).toBeInTheDocument();
    });

    it('clears cron_expression when switching back to interval and saving', async () => {
      await renderAndLoad({
        schedule: { ...defaultSchedule, cron_expression: '0 3 * * *' },
      });
      fireEvent.click(screen.getByTestId('switch-to-interval'));
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() =>
        expect(vi.mocked(updateBackupSchedule)).toHaveBeenCalledWith(
          expect.objectContaining({ cron_expression: '' })
        )
      );
    });
  });
});
