import { create } from 'zustand';

const useWarningsStore = create((set) => ({
  // Map of action keys to whether they're suppressed
  suppressedWarnings: {},

  // Function to check if a warning is suppressed
  isWarningSuppressed: (actionKey) => {
    const state = useWarningsStore.getState();
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

  // Function to reset all suppressions
  resetSuppressions: () => {
    set({ suppressedWarnings: {} });
  },
}));

export default useWarningsStore;
