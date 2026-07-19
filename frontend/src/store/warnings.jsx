import { create } from 'zustand';

const useWarningsStore = create((set, get) => ({
  // Map of action keys to whether they're suppressed
  suppressedWarnings: {},

  // Optional per-action preferences remembered with confirmations
  // e.g. { 'delete-channel': { stopStream: true } }
  actionPreferences: {},

  // Function to check if a warning is suppressed
  isWarningSuppressed: (actionKey) => {
    const state = get();
    return state.suppressedWarnings[actionKey] === true;
  },

  // Function to suppress a warning
  suppressWarning: (actionKey, suppressed = true) => {
    set((state) => ({
      suppressedWarnings: {
        ...state.suppressedWarnings,
        [actionKey]: suppressed,
      },
    }));
  },

  setActionPreference: (actionKey, preference) => {
    if (!actionKey || !preference || typeof preference !== 'object') {
      return;
    }
    set((state) => ({
      actionPreferences: {
        ...state.actionPreferences,
        [actionKey]: {
          ...(state.actionPreferences[actionKey] || {}),
          ...preference,
        },
      },
    }));
  },

  getActionPreference: (actionKey, key, defaultValue = false) => {
    const prefs = get().actionPreferences[actionKey];
    if (!prefs || !(key in prefs)) {
      return defaultValue;
    }
    return prefs[key];
  },

  // Function to reset all suppressions
  resetSuppressions: () => {
    set({ suppressedWarnings: {}, actionPreferences: {} });
  },
}));

export default useWarningsStore;
