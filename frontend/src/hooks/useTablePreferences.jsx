import { useState, useEffect, useCallback } from 'react';

const useTablePreferences = () => {
  // Initialize all preferences from localStorage
  const [headerPinned, setHeaderPinnedState] = useState(() => {
    try {
      const prefs = localStorage.getItem('table-preferences');
      if (prefs) {
        const parsed = JSON.parse(prefs);
        return parsed.headerPinned ?? false;
      }
    } catch (e) {
      console.error('Error reading headerPinned from localStorage:', e);
    }
    return false;
  });

  const [tableSize, setTableSizeState] = useState(() => {
    try {
      // Check new location first
      const prefs = localStorage.getItem('table-preferences');
      if (prefs) {
        const parsed = JSON.parse(prefs);
        if (parsed.tableSize) {
          return parsed.tableSize;
        }
      }
      // Fallback to old location for migration
      const oldSize = localStorage.getItem('table-size');
      if (oldSize) {
        return JSON.parse(oldSize);
      }
    } catch (e) {
      console.error('Error reading tableSize from localStorage:', e);
    }
    return 'default';
  });

  // Listen for changes from other components
  useEffect(() => {
    const handleCustomEvent = (e) => {
      if (
        e.detail.headerPinned !== undefined &&
        e.detail.headerPinned !== headerPinned
      ) {
        setHeaderPinnedState(e.detail.headerPinned);
      }
      if (
        e.detail.tableSize !== undefined &&
        e.detail.tableSize !== tableSize
      ) {
        setTableSizeState(e.detail.tableSize);
      }
    };

    window.addEventListener('table-preferences-changed', handleCustomEvent);
    return () =>
      window.removeEventListener(
        'table-preferences-changed',
        handleCustomEvent
      );
  }, [headerPinned, tableSize]);

  // Function to update headerPinned and persist to localStorage
  const setHeaderPinned = useCallback((value) => {
    setHeaderPinnedState(value);

    try {
      // Read current prefs, update headerPinned, and save back
      let prefs = {};
      const stored = localStorage.getItem('table-preferences');
      if (stored) {
        prefs = JSON.parse(stored);
      }
      prefs.headerPinned = value;
      localStorage.setItem('table-preferences', JSON.stringify(prefs));

      // Dispatch custom event for same-page sync
      window.dispatchEvent(
        new CustomEvent('table-preferences-changed', {
          detail: { headerPinned: value },
        })
      );
    } catch (e) {
      console.error('Error saving headerPinned to localStorage:', e);
    }
  }, []);

  // Function to update tableSize and persist to localStorage
  const setTableSize = useCallback((value) => {
    setTableSizeState(value);

    try {
      // Read current prefs, update tableSize, and save back
      let prefs = {};
      const stored = localStorage.getItem('table-preferences');
      if (stored) {
        prefs = JSON.parse(stored);
      }
      prefs.tableSize = value;
      localStorage.setItem('table-preferences', JSON.stringify(prefs));

      // Dispatch custom event for same-page sync
      window.dispatchEvent(
        new CustomEvent('table-preferences-changed', {
          detail: { tableSize: value },
        })
      );
    } catch (e) {
      console.error('Error saving tableSize to localStorage:', e);
    }
  }, []);

  return { headerPinned, setHeaderPinned, tableSize, setTableSize };
};

export default useTablePreferences;
