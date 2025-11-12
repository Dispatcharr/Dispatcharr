import { create } from 'zustand';

const usePluginsStore = create((set, get) => ({
  // Plugin state change trigger - increment to force re-fetch
  pluginStateVersion: 0,

  // Increment version to trigger plugin list refresh in components
  triggerPluginRefresh: () => {
    set((state) => {
      const newVersion = state.pluginStateVersion + 1;
      console.log('[PluginsStore] Triggering plugin refresh. Old version:', state.pluginStateVersion, 'New version:', newVersion);
      return { pluginStateVersion: newVersion };
    });
  },
}));

export default usePluginsStore;

