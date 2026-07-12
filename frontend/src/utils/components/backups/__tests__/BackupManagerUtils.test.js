import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── API mock ───────────────────────────────────────────────────────────────────
vi.mock('../../../../api.js', () => ({
  default: {
    listBackups: vi.fn(),
    getBackupSchedule: vi.fn(),
    updateBackupSchedule: vi.fn(),
    createBackup: vi.fn(),
    uploadBackup: vi.fn(),
    downloadBackup: vi.fn(),
    restoreBackup: vi.fn(),
    deleteBackup: vi.fn(),
  },
}));

import API from '../../../../api.js';
import {
  to12Hour,
  to24Hour,
  DAYS_OF_WEEK,
  listBackups,
  getBackupSchedule,
  updateBackupSchedule,
  createBackup,
  uploadBackup,
  downloadBackup,
  restoreBackup,
  deleteBackup,
} from '../BackupManagerUtils.js';

// ──────────────────────────────────────────────────────────────────────────────

describe('BackupManagerUtils', () => {
  describe('to12Hour', () => {
    it('converts midnight (00:00) to 12:00 AM', () => {
      expect(to12Hour('00:00')).toEqual({ time: '12:00', period: 'AM' });
    });

    it('converts noon (12:00) to 12:00 PM', () => {
      expect(to12Hour('12:00')).toEqual({ time: '12:00', period: 'PM' });
    });

    it('converts 13:00 to 1:00 PM', () => {
      expect(to12Hour('13:00')).toEqual({ time: '1:00', period: 'PM' });
    });

    it('converts 09:05 to 9:05 AM', () => {
      expect(to12Hour('09:05')).toEqual({ time: '9:05', period: 'AM' });
    });

    it('converts 23:59 to 11:59 PM', () => {
      expect(to12Hour('23:59')).toEqual({ time: '11:59', period: 'PM' });
    });

    it('converts 01:30 to 1:30 AM', () => {
      expect(to12Hour('01:30')).toEqual({ time: '1:30', period: 'AM' });
    });

    it('converts 12:45 to 12:45 PM', () => {
      expect(to12Hour('12:45')).toEqual({ time: '12:45', period: 'PM' });
    });

    it('returns default when called with null', () => {
      expect(to12Hour(null)).toEqual({ time: '12:00', period: 'AM' });
    });

    it('returns default when called with undefined', () => {
      expect(to12Hour(undefined)).toEqual({ time: '12:00', period: 'AM' });
    });

    it('returns default when called with empty string', () => {
      expect(to12Hour('')).toEqual({ time: '12:00', period: 'AM' });
    });

    it('pads single-digit minutes correctly', () => {
      expect(to12Hour('14:05')).toEqual({ time: '2:05', period: 'PM' });
    });
  });

  // ──────────────────────────────────────────────────────────────────────────────

  describe('to24Hour', () => {
    it('converts 12:00 AM to 00:00', () => {
      expect(to24Hour('12:00', 'AM')).toBe('00:00');
    });

    it('converts 12:00 PM to 12:00', () => {
      expect(to24Hour('12:00', 'PM')).toBe('12:00');
    });

    it('converts 1:00 PM to 13:00', () => {
      expect(to24Hour('1:00', 'PM')).toBe('13:00');
    });

    it('converts 11:59 PM to 23:59', () => {
      expect(to24Hour('11:59', 'PM')).toBe('23:59');
    });

    it('converts 9:05 AM to 09:05', () => {
      expect(to24Hour('9:05', 'AM')).toBe('09:05');
    });

    it('converts 12:30 AM to 00:30', () => {
      expect(to24Hour('12:30', 'AM')).toBe('00:30');
    });

    it('converts 12:45 PM to 12:45', () => {
      expect(to24Hour('12:45', 'PM')).toBe('12:45');
    });

    it('converts 1:00 AM to 01:00', () => {
      expect(to24Hour('1:00', 'AM')).toBe('01:00');
    });

    it('returns 00:00 when time12 is null', () => {
      expect(to24Hour(null, 'AM')).toBe('00:00');
    });

    it('returns 00:00 when time12 is undefined', () => {
      expect(to24Hour(undefined, 'PM')).toBe('00:00');
    });

    it('returns 00:00 when time12 is empty string', () => {
      expect(to24Hour('', 'PM')).toBe('00:00');
    });

    it('pads hours and minutes to two digits', () => {
      expect(to24Hour('2:05', 'PM')).toBe('14:05');
    });
  });

  // ──────────────────────────────────────────────────────────────────────────────

  describe('to12Hour / to24Hour roundtrip', () => {
    const cases = [
      '00:00',
      '00:30',
      '01:00',
      '09:05',
      '11:59',
      '12:00',
      '12:01',
      '13:00',
      '14:05',
      '23:59',
    ];

    it.each(cases)('round-trips %s', (time24) => {
      const { time, period } = to12Hour(time24);
      expect(to24Hour(time, period)).toBe(time24);
    });
  });

  // ──────────────────────────────────────────────────────────────────────────────

  describe('DAYS_OF_WEEK', () => {
    it('has 7 entries', () => {
      expect(DAYS_OF_WEEK).toHaveLength(7);
    });

    it('starts with Sunday (value "0")', () => {
      expect(DAYS_OF_WEEK[0]).toEqual({ value: '0', label: 'Sunday' });
    });

    it('ends with Saturday (value "6")', () => {
      expect(DAYS_OF_WEEK[6]).toEqual({ value: '6', label: 'Saturday' });
    });

    it('contains Monday through Friday in order', () => {
      const labels = DAYS_OF_WEEK.map((d) => d.label);
      expect(labels).toEqual([
        'Sunday',
        'Monday',
        'Tuesday',
        'Wednesday',
        'Thursday',
        'Friday',
        'Saturday',
      ]);
    });

    it('has string values "0"–"6"', () => {
      DAYS_OF_WEEK.forEach((day, i) => {
        expect(day.value).toBe(String(i));
      });
    });
  });

  // ──────────────────────────────────────────────────────────────────────────────

  describe('API proxy functions', () => {
    beforeEach(() => {
      vi.clearAllMocks();
    });

    describe('listBackups', () => {
      it('delegates to API.listBackups and returns its result', async () => {
        const data = [{ filename: 'backup1.zip' }];
        vi.mocked(API.listBackups).mockResolvedValue(data);
        await expect(listBackups()).resolves.toEqual(data);
        expect(API.listBackups).toHaveBeenCalledTimes(1);
      });

      it('propagates rejection from API.listBackups', async () => {
        vi.mocked(API.listBackups).mockRejectedValue(new Error('network'));
        await expect(listBackups()).rejects.toThrow('network');
      });
    });

    describe('getBackupSchedule', () => {
      it('delegates to API.getBackupSchedule and returns its result', async () => {
        const schedule = { enabled: true, time: '02:00' };
        vi.mocked(API.getBackupSchedule).mockResolvedValue(schedule);
        await expect(getBackupSchedule()).resolves.toEqual(schedule);
        expect(API.getBackupSchedule).toHaveBeenCalledTimes(1);
      });

      it('propagates rejection from API.getBackupSchedule', async () => {
        vi.mocked(API.getBackupSchedule).mockRejectedValue(new Error('fail'));
        await expect(getBackupSchedule()).rejects.toThrow('fail');
      });
    });

    describe('updateBackupSchedule', () => {
      it('passes settings through to API.updateBackupSchedule', async () => {
        const settings = { enabled: false, time: '03:00' };
        const updated = { ...settings, id: 1 };
        vi.mocked(API.updateBackupSchedule).mockResolvedValue(updated);
        await expect(updateBackupSchedule(settings)).resolves.toEqual(updated);
        expect(API.updateBackupSchedule).toHaveBeenCalledWith(settings);
      });

      it('propagates rejection', async () => {
        vi.mocked(API.updateBackupSchedule).mockRejectedValue(new Error('err'));
        await expect(updateBackupSchedule({})).rejects.toThrow('err');
      });
    });

    describe('createBackup', () => {
      it('delegates to API.createBackup and returns its result', async () => {
        const result = { filename: 'new-backup.zip' };
        vi.mocked(API.createBackup).mockResolvedValue(result);
        await expect(createBackup()).resolves.toEqual(result);
        expect(API.createBackup).toHaveBeenCalledTimes(1);
      });

      it('propagates rejection', async () => {
        vi.mocked(API.createBackup).mockRejectedValue(new Error('disk full'));
        await expect(createBackup()).rejects.toThrow('disk full');
      });
    });

    describe('uploadBackup', () => {
      it('passes file to API.uploadBackup', async () => {
        const file = new File(['data'], 'backup.zip');
        const result = { filename: 'backup.zip' };
        vi.mocked(API.uploadBackup).mockResolvedValue(result);
        await expect(uploadBackup(file)).resolves.toEqual(result);
        expect(API.uploadBackup).toHaveBeenCalledWith(file);
      });

      it('propagates rejection', async () => {
        vi.mocked(API.uploadBackup).mockRejectedValue(
          new Error('upload error')
        );
        await expect(uploadBackup(new File([], 'x.zip'))).rejects.toThrow(
          'upload error'
        );
      });
    });

    describe('downloadBackup', () => {
      it('passes filename to API.downloadBackup', async () => {
        const filename = 'backup-2024.zip';
        vi.mocked(API.downloadBackup).mockResolvedValue({ filename });
        await expect(downloadBackup(filename)).resolves.toEqual({ filename });
        expect(API.downloadBackup).toHaveBeenCalledWith(filename);
      });

      it('propagates rejection', async () => {
        vi.mocked(API.downloadBackup).mockRejectedValue(new Error('not found'));
        await expect(downloadBackup('missing.zip')).rejects.toThrow(
          'not found'
        );
      });
    });

    describe('restoreBackup', () => {
      it('passes filename and onProgress to API.restoreBackup', async () => {
        const filename = 'backup.zip';
        const onProgress = vi.fn();
        const result = { success: true };
        vi.mocked(API.restoreBackup).mockResolvedValue(result);
        await expect(restoreBackup(filename, onProgress)).resolves.toEqual(
          result
        );
        expect(API.restoreBackup).toHaveBeenCalledWith(filename, onProgress);
      });

      it('propagates rejection', async () => {
        vi.mocked(API.restoreBackup).mockRejectedValue(
          new Error('restore failed')
        );
        await expect(restoreBackup('backup.zip', vi.fn())).rejects.toThrow(
          'restore failed'
        );
      });
    });

    describe('deleteBackup', () => {
      it('passes filename to API.deleteBackup', async () => {
        const filename = 'old-backup.zip';
        vi.mocked(API.deleteBackup).mockResolvedValue(undefined);
        await expect(deleteBackup(filename)).resolves.toBeUndefined();
        expect(API.deleteBackup).toHaveBeenCalledWith(filename);
      });

      it('propagates rejection', async () => {
        vi.mocked(API.deleteBackup).mockRejectedValue(
          new Error('delete error')
        );
        await expect(deleteBackup('old.zip')).rejects.toThrow('delete error');
      });
    });
  });
});
