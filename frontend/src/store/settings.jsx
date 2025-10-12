import { create } from 'zustand';
import api from '../api';

const useSettingsStore = create((set) => ({
  settings: {},
  environment: {
    // Add default values for environment settings
    public_ip: '',
    country_code: '',
    country_name: '',
    env_mode: 'prod',
  },
  isLoading: false,
  error: null,

  fetchSettings: async () => {
    set({ isLoading: true, error: null });
    try {
      const settings = await api.getSettings();
      const env = await api.getEnvironmentSettings();
      set({
        settings: settings.reduce((acc, setting) => {
          acc[setting.key] = setting;
          return acc;
        }, {}),
        isLoading: false,
        environment: env || {
          public_ip: '',
          country_code: '',
          country_name: '',
          env_mode: 'prod',
        },
      });
    } catch (error) {
      set({ error: 'Failed to load settings.', isLoading: false });
    }
  },

  updateSetting: (setting) =>
    set((state) => ({
      settings: { ...state.settings, [setting.key]: setting },
    })),
  removeSetting: (key) =>
    set((state) => {
      if (!key) return state;
      const next = { ...state.settings };
      delete next[key];
      return { ...state, settings: next };
    }),
}));

export default useSettingsStore;
