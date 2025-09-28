import { create } from 'zustand';
import { notifications } from '@mantine/notifications';
import API from '../api';

const defaultTimezone = Intl?.DateTimeFormat?.().resolvedOptions().timeZone || 'UTC';

const useBackupsStore = create((set, get) => ({
  jobs: [],
  settings: {
    enabled: false,
    retention: 5,
    path: '/data/backups',
    extra_paths: [],
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
  },
  loading: false,
  saving: false,
  error: null,
  lastFetched: null,

  fetchSettings: async () => {
    set({ loading: true });
    try {
      const settings = await API.getBackupSettings();
      set({
        settings: {
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
          ...settings,
        },
        loading: false,
        error: null,
        lastFetched: new Date(),
      });
    } catch (error) {
      notifications.show({
        title: 'Backup settings',
        message: 'Failed to load backup settings',
        color: 'red',
      });
      set({ loading: false, error });
    }
  },

  fetchJobs: async () => {
    try {
      const jobs = await API.getBackupJobs();
      if (jobs) {
        set({ jobs });
      }
    } catch (error) {
      notifications.show({
        title: 'Backup history',
        message: 'Failed to load backup history',
        color: 'red',
      });
    }
  },

  runBackup: async () => {
    try {
      const job = await API.createBackupJob();
      notifications.show({
        title: 'Backup scheduled',
        message: 'Backup job queued successfully',
        color: 'green',
      });
      set((state) => ({
        jobs: job
          ? [job, ...state.jobs.filter((existing) => existing.id !== job.id)]
          : state.jobs,
      }));
      get().pollUntilSettled();
    } catch (error) {
      notifications.show({
        title: 'Backup',
        message: 'Failed to start backup job',
        color: 'red',
      });
    }
  },

  restoreBackup: async (jobId) => {
    try {
      const job = await API.restoreBackupJob(jobId);
      notifications.show({
        title: 'Restore queued',
        message: 'Restore job started, Dispatcharr will reload data shortly',
        color: 'blue',
      });
      set((state) => ({
        jobs: job
          ? [job, ...state.jobs.filter((existing) => existing.id !== job.id)]
          : state.jobs,
      }));
      get().pollUntilSettled();
    } catch (error) {
      notifications.show({
        title: 'Restore',
        message: 'Failed to start restore job',
        color: 'red',
      });
    }
  },

  uploadAndRestore: async (file) => {
    try {
      const job = await API.uploadAndRestoreBackup(file);
      notifications.show({
        title: 'Restore queued',
        message: `Uploaded ${file.name} and queued restore`,
        color: 'blue',
      });
      set((state) => ({
        jobs: job
          ? [job, ...state.jobs.filter((existing) => existing.id !== job.id)]
          : state.jobs,
      }));
      get().pollUntilSettled();
    } catch (error) {
      notifications.show({
        title: 'Restore',
        message: 'Failed to upload backup archive',
        color: 'red',
      });
    }
  },

  updateSettings: async (payload) => {
    set({ saving: true });
    try {
      const settings = await API.updateBackupSettings(payload);
      set({
        settings: {
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
          ...settings,
        },
        saving: false,
      });
      notifications.show({
        title: 'Backup settings',
        message: 'Settings saved successfully',
        color: 'green',
      });
      return settings;
    } catch (error) {
      set({ saving: false });
      notifications.show({
        title: 'Backup settings',
        message: error?.body?.detail || 'Failed to save backup settings',
        color: 'red',
      });
      throw error;
    }
  },

  cancelJob: async (jobId) => {
    try {
      const job = await API.cancelBackupJob(jobId);
      notifications.show({
        title: 'Backup',
        message: 'Backup job canceled',
        color: 'yellow',
      });
      set((state) => ({
        jobs: state.jobs.map((existing) =>
          existing.id === job.id ? job : existing
        ),
      }));
    } catch (error) {
      notifications.show({
        title: 'Backup',
        message: 'Failed to cancel backup job',
        color: 'red',
      });
      throw error;
    }
  },

  deleteJob: async (jobId) => {
    try {
      await API.deleteBackupJob(jobId);
      set((state) => ({
        jobs: state.jobs.filter((job) => job.id !== jobId),
      }));
      notifications.show({
        title: 'Backup',
        message: 'Backup job deleted',
        color: 'green',
      });
    } catch (error) {
      notifications.show({
        title: 'Backup',
        message: 'Failed to delete backup job',
        color: 'red',
      });
      throw error;
    }
  },

  pollUntilSettled: () => {
    const interval = setInterval(async () => {
      await get().fetchJobs();
      const hasRunning = get().jobs.some((job) =>
        ['pending', 'running'].includes(job.status)
      );
      if (!hasRunning) {
        clearInterval(interval);
      }
    }, 5000);
    return interval;
  },
}));

export default useBackupsStore;
