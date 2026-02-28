import { useState, useEffect, useCallback } from "react";
import storage from "~/lib/safe-storage";

export type TableSize = "compact" | "default" | "large";

interface TablePreferences {
  tableSize?: TableSize;
  headerPinned?: boolean;
}

const STORAGE_KEY = "table-preferences";

/**
 * Hook for managing table display preferences (size, header pinning, etc.)
 * Persists preferences to localStorage and syncs across the app
 */
export function useTablePreferences() {
  const [tableSize, setTableSizeState] = useState<TableSize>(() => {
    const prefs = storage.getJSON<TablePreferences>(STORAGE_KEY);
    return prefs?.tableSize || "default";
  });

  const [headerPinned, setHeaderPinnedState] = useState<boolean>(() => {
    const prefs = storage.getJSON<TablePreferences>(STORAGE_KEY);
    return prefs?.headerPinned ?? true;
  });

  // Listen for changes from other components via custom event
  useEffect(() => {
    const handleCustomEvent = (e: CustomEvent<TablePreferences>) => {
      if (e.detail.tableSize && e.detail.tableSize !== tableSize) {
        setTableSizeState(e.detail.tableSize);
      }
      if (
        e.detail.headerPinned !== undefined &&
        e.detail.headerPinned !== headerPinned
      ) {
        setHeaderPinnedState(e.detail.headerPinned);
      }
    };

    window.addEventListener(
      "table-preferences-changed",
      handleCustomEvent as EventListener,
    );
    return () =>
      window.removeEventListener(
        "table-preferences-changed",
        handleCustomEvent as EventListener,
      );
  }, [tableSize, headerPinned]);

  // Update tableSize and persist to localStorage
  const setTableSize = useCallback((value: TableSize) => {
    setTableSizeState(value);

    try {
      const prefs: TablePreferences =
        storage.getJSON<TablePreferences>(STORAGE_KEY) || {};
      prefs.tableSize = value;
      storage.setJSON(STORAGE_KEY, prefs);

      // Dispatch custom event for same-page sync
      window.dispatchEvent(
        new CustomEvent("table-preferences-changed", {
          detail: { tableSize: value },
        }),
      );
    } catch (e) {
      console.error("Error saving tableSize to localStorage:", e);
    }
  }, []);

  // Update headerPinned and persist to localStorage
  const setHeaderPinned = useCallback((value: boolean) => {
    setHeaderPinnedState(value);

    try {
      const prefs: TablePreferences =
        storage.getJSON<TablePreferences>(STORAGE_KEY) || {};
      prefs.headerPinned = value;
      storage.setJSON(STORAGE_KEY, prefs);

      // Dispatch custom event for same-page sync
      window.dispatchEvent(
        new CustomEvent("table-preferences-changed", {
          detail: { headerPinned: value },
        }),
      );
    } catch (e) {
      console.error("Error saving headerPinned to localStorage:", e);
    }
  }, []);

  return { tableSize, setTableSize, headerPinned, setHeaderPinned };
}

export default useTablePreferences;
