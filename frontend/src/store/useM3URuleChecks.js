import { create } from 'zustand';

// Last explicitly saved check only. No requests or browser-storage persistence.
const useM3URuleChecks = create((set) => ({
  checks: {},
  remember: (key, signature, coverage) =>
    set((state) => ({
      checks: { ...state.checks, [key]: { signature, coverage } },
    })),
  forget: (key) =>
    set((state) => {
      const checks = { ...state.checks };
      delete checks[key];
      return { checks };
    }),
}));

export default useM3URuleChecks;
