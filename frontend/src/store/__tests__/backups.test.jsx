import { describe, beforeEach, afterEach, it, expect, vi } from 'vitest';
import useBackupsStore from '../backups';

vi.mock('@mantine/notifications', () => ({ notifications: { show: vi.fn() } }));

const apiMocks = vi.hoisted(() => ({
  getBackupSettings: vi.fn(),
  getBackupJobs: vi.fn(),
  updateBackupSettings: vi.fn(),
  createBackupJob: vi.fn(),
  restoreBackupJob: vi.fn(),
  uploadAndRestoreBackup: vi.fn(),
  downloadBackupJob: vi.fn(),
  cancelBackupJob: vi.fn(),
  deleteBackupJob: vi.fn(),
}));

vi.mock('../../api', () => ({
  __esModule: true,
  default: apiMocks,
}));

describe('useBackupsStore', () => {
  const initialState = useBackupsStore.getState();
  const defaultTimezone = Intl?.DateTimeFormat?.().resolvedOptions().timeZone || 'UTC';

  beforeEach(() => {
    useBackupsStore.setState(initialState, true);
    Object.values(apiMocks).forEach((mock) => mock.mockReset());
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('fetchSettings loads settings into state', async () => {
    const payload = {
      enabled: true,
      retention: 3,
      path: '/tmp',
      extra_paths: [],
      schedule: {
        preset: 'weekly',
        minute: '30',
        hour: '1',
        day_of_month: '*',
        month: '*',
        day_of_week: 'mon,fri',
        timezone: 'UTC',
      },
    };
    apiMocks.getBackupSettings.mockResolvedValue(payload);

    await useBackupsStore.getState().fetchSettings();

    const state = useBackupsStore.getState();
    expect(state.settings).toEqual({
      include_recordings: true,
      schedule: {
        preset: 'daily',
        minute: '15',
        hour: '3',
        day_of_month: '*',
        month: '*',
        day_of_week: '*',
        timezone: defaultTimezone,
      },
      ...payload,
    });
    expect(state.loading).toBe(false);
  });

  it('runBackup queues job and triggers polling', async () => {
    const job = { id: 7, status: 'pending', job_type: 'backup' };
    apiMocks.createBackupJob.mockResolvedValue(job);
    const pollSpy = vi.fn();
    useBackupsStore.setState({ pollUntilSettled: pollSpy }, false);

    await useBackupsStore.getState().runBackup();

    expect(apiMocks.createBackupJob).toHaveBeenCalledTimes(1);
    expect(useBackupsStore.getState().jobs[0]).toEqual(job);
    expect(pollSpy).toHaveBeenCalledTimes(1);
  });

  it('restoreBackup enqueues restore job', async () => {
    const job = { id: 9, status: 'pending', job_type: 'restore' };
    apiMocks.restoreBackupJob.mockResolvedValue(job);
    const pollSpy = vi.fn();
    useBackupsStore.setState({ pollUntilSettled: pollSpy }, false);

    await useBackupsStore.getState().restoreBackup(9);

    expect(apiMocks.restoreBackupJob).toHaveBeenCalledWith(9);
    expect(useBackupsStore.getState().jobs[0]).toEqual(job);
    expect(pollSpy).toHaveBeenCalledTimes(1);
  });

  it('uploadAndRestore calls API with file', async () => {
    const fileJob = { id: 11, status: 'pending', job_type: 'restore' };
    apiMocks.uploadAndRestoreBackup.mockResolvedValue(fileJob);
    const pollSpy = vi.fn();
    useBackupsStore.setState({ pollUntilSettled: pollSpy }, false);

    const file = new File(['content'], 'backup.tar.gz');
    await useBackupsStore.getState().uploadAndRestore(file);

    expect(apiMocks.uploadAndRestoreBackup).toHaveBeenCalledWith(file);
    expect(useBackupsStore.getState().jobs[0]).toEqual(fileJob);
    expect(pollSpy).toHaveBeenCalledTimes(1);
  });

  it('updateSettings persists and stores new values', async () => {
    const updated = {
      enabled: true,
      retention: 4,
      path: '/backups',
      extra_paths: ['/extra'],
      include_recordings: false,
      schedule: {
        preset: 'custom',
        minute: '0,30',
        hour: '*/6',
        day_of_month: '1,15',
        month: '*',
        day_of_week: '*',
        timezone: 'UTC',
      },
    };
    apiMocks.updateBackupSettings.mockResolvedValue(updated);

    await useBackupsStore.getState().updateSettings(updated);

    expect(apiMocks.updateBackupSettings).toHaveBeenCalledWith(updated);
    expect(useBackupsStore.getState().settings).toEqual({
      include_recordings: true,
      schedule: {
        preset: 'daily',
        minute: '15',
        hour: '3',
        day_of_month: '*',
        month: '*',
        day_of_week: '*',
        timezone: defaultTimezone,
      },
      ...updated,
    });
  });

  it('cancelJob updates job status', async () => {
    const job = { id: 5, status: 'running', job_type: 'backup', can_cancel: true };
    useBackupsStore.setState({ jobs: [job] });
    apiMocks.cancelBackupJob.mockResolvedValue({ ...job, status: 'canceled', can_cancel: false });

    await useBackupsStore.getState().cancelJob(5);

    expect(apiMocks.cancelBackupJob).toHaveBeenCalledWith(5);
    expect(useBackupsStore.getState().jobs[0].status).toBe('canceled');
  });

  it('deleteJob removes job from store', async () => {
    const job = { id: 6, status: 'succeeded', job_type: 'backup', can_delete: true };
    useBackupsStore.setState({ jobs: [job] });
    apiMocks.deleteBackupJob.mockResolvedValue();

    await useBackupsStore.getState().deleteJob(6);

    expect(apiMocks.deleteBackupJob).toHaveBeenCalledWith(6);
    expect(useBackupsStore.getState().jobs).toHaveLength(0);
  });
});
