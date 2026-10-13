import { useCallback, useRef } from 'react';

/**
 * Prevent settings-store updates from flashing old values into a form mid-save.
 *
 * Gate store→form hydration with ``!isSavingRef.current``. Wrap the save path
 * in ``runSave`` so the effect skips until the request finishes.
 */
export default function useSettingsSaveGuard() {
  const isSavingRef = useRef(false);

  const runSave = useCallback(async (fn) => {
    isSavingRef.current = true;
    try {
      return await fn();
    } finally {
      isSavingRef.current = false;
    }
  }, []);

  return { isSavingRef, runSave };
}
