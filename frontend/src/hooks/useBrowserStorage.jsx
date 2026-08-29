import { useEffect, useState } from 'react';

const isPlainObject = (value) =>
  value !== null && typeof value === 'object' && !Array.isArray(value);

const getStorage = (storage = 'local') =>
  storage === 'session' ? sessionStorage : localStorage;

/**
 * Synchronously read a JSON value from local or session storage.
 * Plain objects are shallow-merged with defaultValue so new keys get defaults.
 */
export const readStoredJSON = (key, defaultValue, storage = 'local') => {
  try {
    const item = getStorage(storage).getItem(key);
    if (item == null) {
      return defaultValue;
    }

    const parsed = JSON.parse(item);
    if (isPlainObject(defaultValue) && isPlainObject(parsed)) {
      return { ...defaultValue, ...parsed };
    }

    return parsed;
  } catch (error) {
    console.error(`Error reading key "${key}":`, error);
    return defaultValue;
  }
};

/**
 * Synchronously write a JSON value to local or session storage.
 */
export const writeStoredJSON = (key, value, storage = 'local') => {
  try {
    getStorage(storage).setItem(key, JSON.stringify(value));
  } catch (error) {
    console.error(`Error saving setting: ${key}:`, error);
  }
};

/**
 * Persist React state in localStorage (default) or sessionStorage.
 * Pass { storage: 'session' } for tab-scoped values.
 */
const useBrowserStorage = (key, defaultValue, options = {}) => {
  const { storage = 'local' } = options;

  const [value, setValue] = useState(() =>
    readStoredJSON(key, defaultValue, storage)
  );

  useEffect(() => {
    writeStoredJSON(key, value, storage);
  }, [key, value, storage]);

  return [value, setValue];
};

export default useBrowserStorage;
