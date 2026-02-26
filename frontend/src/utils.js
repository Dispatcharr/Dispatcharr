import React, { useState, useEffect, useRef } from 'react';
import { notifications } from '@mantine/notifications';

export default {
  Limiter: (n, list) => {
    if (!list || !list.length) {
      return;
    }

    var tail = list.splice(n);
    var head = list;
    var resolved = [];
    var processed = 0;

    return new Promise(function (resolve) {
      head.forEach(function (x) {
        var res = x();
        resolved.push(res);
        res.then(function (y) {
          runNext();
          return y;
        });
      });
      function runNext() {
        if (processed == tail.length) {
          resolve(Promise.all(resolved));
        } else {
          resolved.push(
            tail[processed]().then(function (x) {
              runNext();
              return x;
            })
          );
          processed++;
        }
      }
    });
  },
};

// Custom debounce hook
export function useDebounce(value, delay = 500, callback = null) {
  const [debouncedValue, setDebouncedValue] = useState(value);
  const isFirstRender = useRef(true);
  const previousValueRef = useRef(JSON.stringify(value));

  useEffect(() => {
    const currentValueStr = JSON.stringify(value);

    // Skip if value hasn't actually changed (prevents unnecessary state updates)
    if (previousValueRef.current === currentValueStr) {
      return;
    }

    const handler = setTimeout(() => {
      setDebouncedValue(value);
      // Only fire callback if not the first render
      if (callback && !isFirstRender.current) {
        callback();
      }
      isFirstRender.current = false;
      previousValueRef.current = currentValueStr;
    }, delay);

    return () => clearTimeout(handler); // Cleanup timeout on unmount or value change
  }, [value, delay]);

  return debouncedValue;
}

export function sleep(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

export const getDescendantProp = (obj, path) =>
  path.split('.').reduce((acc, part) => acc && acc[part], obj);

export const copyToClipboard = async (value, options = {}) => {
  const {
    successTitle = 'Copied!',
    successMessage = 'Copied to clipboard',
    failureTitle = 'Copy Failed',
    failureMessage = 'Failed to copy to clipboard',
    showNotification = true,
  } = options;

  let success = false;

  if (navigator.clipboard) {
    // Modern method, using navigator.clipboard
    try {
      await navigator.clipboard.writeText(value);
      success = true;
    } catch (err) {
      console.error('Failed to copy: ', err);
    }
  }

  if (!success) {
    // Fallback method for environments without clipboard support
    try {
      const textarea = document.createElement('textarea');
      textarea.value = value;
      document.body.appendChild(textarea);
      textarea.select();
      const successful = document.execCommand('copy');
      document.body.removeChild(textarea);
      success = successful;
    } catch (err) {
      console.error('Failed to copy with fallback method: ', err);
      success = false;
    }
  }

  // Show notification if enabled
  if (showNotification) {
    notifications.show({
      title: success ? successTitle : failureTitle,
      message: success ? successMessage : failureMessage,
      color: success ? 'green' : 'red',
    });
  }

  return success;
};

export const setCustomProperty = (input, key, value, serialize = false) => {
  let obj;

  if (input == null) {
    // matches null or undefined
    obj = {};
  } else if (typeof input === 'string') {
    try {
      obj = JSON.parse(input);
    } catch (e) {
      obj = {};
    }
  } else if (typeof input === 'object' && !Array.isArray(input)) {
    obj = { ...input }; // shallow copy
  } else {
    obj = {};
  }

  obj[key] = value;

  if (serialize === true) {
    return JSON.stringify(obj);
  }

  return obj;
};
