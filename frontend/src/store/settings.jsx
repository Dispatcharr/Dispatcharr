import { create } from 'zustand';
import api from '../api';

const useSettingsStore = create((set, get) => ({
  settings: {},
  environment: {
    // Add default values for environment settings
    public_ip: '',
    country_code: '',
    country_name: '',
    env_mode: 'aio',
    ip_lookup_enabled: true,
    ip_lookup_env_disabled: false,
    ip_lookup_pending: false,
  },
  version: {
    version: '',
    timestamp: null,
  },
  isLoading: false,
  error: null,

  fetchSettings: async () => {
    set({ isLoading: true, error: null });
    try {
      // Only fetch version if not already loaded (may have been fetched by Login/Superuser form)
      const currentVersion = get().version;
      const needsVersion = !currentVersion.version;

      const [settings, env, versionData] = await Promise.all([
        api.getSettings(),
        api.getEnvironmentSettings(),
        needsVersion ? api.getVersion() : Promise.resolve(null),
      ]);

      const newState = {
        settings: settings.reduce((acc, setting) => {
          acc[setting.key] = setting;
          return acc;
        }, {}),
        isLoading: false,
        environment: env || {
          public_ip: '',
          country_code: '',
          country_name: '',
          env_mode: 'aio',
          ip_lookup_enabled: true,
          ip_lookup_env_disabled: false,
          ip_lookup_pending: false,
        },
      };

      // Only update version if we fetched it
      if (versionData) {
        newState.version = {
          version: versionData?.version || '',
          timestamp: versionData?.timestamp || null,
        };
      }

      set(newState);

      // If the IP lookup was still running when we fetched, retry once it should be done
      if (env?.ip_lookup_pending) {
        setTimeout(async () => {
          try {
            const freshEnv = await api.getEnvironmentSettings();
            if (freshEnv && !freshEnv.ip_lookup_pending) {
              set({ environment: freshEnv });
            }
          } catch {}
        }, 7000);
      }
    } catch (error) {
      set({ error: 'Failed to load settings.', isLoading: false });
    }
  },

  // Fetch version independently (for unauthenticated pages like Login)
  fetchVersion: async () => {
    // Skip if already loaded
    if (get().version.version) {
      return get().version;
    }
    try {
      const versionData = await api.getVersion();
      const version = {
        version: versionData?.version || '',
        timestamp: versionData?.timestamp || null,
      };
      set({ version });
      return version;
    } catch (error) {
      console.error('Failed to fetch version:', error);
      return get().version;
    }
  },

  updateSetting: (setting) =>
    set((state) => ({
      settings: { ...state.settings, [setting.key]: setting },
    })),
}));

export default useSettingsStore;
