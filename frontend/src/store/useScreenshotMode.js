import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

const useScreenshotMode = create(
  persist(
    (set) => ({
      enabled: false,
      toggle: () => set((state) => ({ enabled: !state.enabled })),
    }),
    {
      name: 'dispatcharr-screenshot-mode',
      storage: createJSONStorage(() => sessionStorage),
      partialize: ({ enabled }) => ({ enabled }),
      merge: (saved, current) => ({
        ...current,
        enabled: saved?.enabled === true,
      }),
    }
  )
);

export default useScreenshotMode;
