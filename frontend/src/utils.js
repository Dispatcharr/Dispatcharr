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

// Human-readable message for a failed API response (#1261). Backends that
// are down or timing out answer with whole HTML error pages (Django's
// "Server Error (500)" page, nginx's 502/504 pages) - rendering those
// verbatim in a toast is unreadable. JSON error bodies keep their existing
// formatting; markup and empty bodies collapse to the response's own
// status line (the full body goes to console.debug for troubleshooting);
// long plain-text bodies are truncated.
const ERROR_BODY_MAX_CHARS = 200;

export const formatApiError = (error) => {
  if (!error || !error.status) {
    return (error && error.message) || 'Unknown error';
  }

  // request() attaches the fetch Response as error.response; it carries the
  // canonical reason phrase and the declared content type.
  const { status, body, response } = error;

  if (body && typeof body === 'object') {
    try {
      return JSON.stringify(body, null, 2);
    } catch {
      // Unserializable object; fall through to the string handling below.
    }
  }

  const text =
    typeof body === 'string' ? body.trim() : body == null ? '' : String(body);

  // Trust the declared content type first; sniff only when it is absent
  // (some proxies omit or mislabel it on error pages).
  const contentType = response?.headers?.get?.('content-type') || '';
  const isMarkup =
    contentType.includes('html') ||
    contentType.includes('xml') ||
    text.startsWith('<');

  if (!text || isMarkup) {
    if (text) {
      console.debug(`API error ${status} response body:`, text);
    }
    // statusText is the protocol's reason phrase ("Bad Gateway"), defined
    // for every status code. HTTP/2+ does not transmit one, so fall back
    // to a generic label rather than re-enumerating the HTTP spec here.
    return `${status} - ${response?.statusText || 'Request failed'}`;
  }

  return text.length > ERROR_BODY_MAX_CHARS
    ? `${status} - ${text.slice(0, ERROR_BODY_MAX_CHARS)}...`
    : `${status} - ${text}`;
};

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
