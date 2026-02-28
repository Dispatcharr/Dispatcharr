/**
 * Safe localStorage wrapper that handles SSR gracefully
 * Can be used anywhere: stores, loaders, utilities, etc.
 */

/**
 * Check if we're in a browser environment
 */
function isBrowser(): boolean {
  return typeof window !== "undefined" && typeof localStorage !== "undefined";
}

/**
 * Safely get an item from localStorage
 * Returns null if not in browser or key doesn't exist
 */
export function getItem(key: string): string | null {
  if (!isBrowser()) return null;
  try {
    return localStorage.getItem(key);
  } catch (error) {
    console.error(`Error reading localStorage key "${key}":`, error);
    return null;
  }
}

/**
 * Safely set an item in localStorage
 * No-op if not in browser
 */
export function setItem(key: string, value: string): void {
  if (!isBrowser()) return;
  try {
    localStorage.setItem(key, value);
  } catch (error) {
    console.error(`Error setting localStorage key "${key}":`, error);
  }
}

/**
 * Safely remove an item from localStorage
 * No-op if not in browser
 */
export function removeItem(key: string): void {
  if (!isBrowser()) return;
  try {
    localStorage.removeItem(key);
  } catch (error) {
    console.error(`Error removing localStorage key "${key}":`, error);
  }
}

/**
 * Safely clear all localStorage
 * No-op if not in browser
 */
export function clear(): void {
  if (!isBrowser()) return;
  try {
    localStorage.clear();
  } catch (error) {
    console.error("Error clearing localStorage:", error);
  }
}

/**
 * Get and parse JSON from localStorage
 * Returns null if not found or invalid JSON
 */
export function getJSON<T = any>(key: string): T | null {
  const item = getItem(key);
  if (!item) return null;
  try {
    return JSON.parse(item) as T;
  } catch (error) {
    console.error(`Error parsing JSON for localStorage key "${key}":`, error);
    return null;
  }
}

/**
 * Stringify and set JSON in localStorage
 */
export function setJSON<T = any>(key: string, value: T): void {
  try {
    const json = JSON.stringify(value);
    setItem(key, json);
  } catch (error) {
    console.error(
      `Error stringifying JSON for localStorage key "${key}":`,
      error,
    );
  }
}

/**
 * Default export for convenience
 */
export default {
  getItem,
  setItem,
  removeItem,
  clear,
  getJSON,
  setJSON,
  isBrowser,
};
