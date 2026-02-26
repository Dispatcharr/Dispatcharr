import { useEffect, useState } from 'react';

const useLocalStorage = (key, defaultValue) => {
  const localKey = key;

  const [value, setValue] = useState(() => {
    try {
      const item = localStorage.getItem(localKey);
      return item ? JSON.parse(item) : defaultValue;
    } catch (error) {
      console.error(`Error reading key "${localKey}":`, error);
    }

    return defaultValue;
  });

  useEffect(() => {
    try {
      localStorage.setItem(localKey, JSON.stringify(value));
    } catch (error) {
      console.error(`Error saving setting: ${localKey}:`, error);
    }
  }, [localKey, value]);

  return [value, setValue];
};

export default useLocalStorage;
