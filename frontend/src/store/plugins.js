import { create } from 'zustand';

const usePluginsStore = create((set, get) => ({
  // Plugin state change trigger - increment to force re-fetch
  pluginStateVersion: 0,
  
  // Increment version to trigger plugin list refresh in components
  triggerPluginRefresh: () => {
    set((state) => ({ pluginStateVersion: state.pluginStateVersion + 1 }));
  },
}));

export default usePluginsStore;

