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

// Format a failed API response for toast display.
const ERROR_BODY_MAX_CHARS = 200;

const STATUS_LABELS = {
  400: 'Bad Request',
  401: 'Unauthorized',
  403: 'Forbidden',
  404: 'Not Found',
  405: 'Method Not Allowed',
  408: 'Request Timeout',
  409: 'Conflict',
  413: 'Payload Too Large',
  429: 'Too Many Requests',
  500: 'Internal Server Error',
  502: 'Bad Gateway',
  503: 'Service Unavailable',
  504: 'Gateway Timeout',
};

const formatErrorValue = (value) => {
  if (value == null) return '';
  if (Array.isArray(value)) {
    return value.map(formatErrorValue).filter(Boolean).join('; ');
  }
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value);
    } catch {
      return '';
    }
  }
  return String(value);
};

const formatJsonErrorBody = (body) => {
  if (Array.isArray(body)) {
    return formatErrorValue(body) || null;
  }
  if (!body || typeof body !== 'object') {
    return null;
  }

  for (const key of ['detail', 'error', 'non_field_errors']) {
    if (body[key] != null && body[key] !== '') {
      const msg = formatErrorValue(body[key]);
      if (msg) return msg;
    }
  }

  const fieldParts = Object.entries(body)
    .map(([key, value]) => {
      const msg = formatErrorValue(value);
      return msg ? `${key}: ${msg}` : null;
    })
    .filter(Boolean);

  if (fieldParts.length) {
    return fieldParts.join('; ');
  }

  try {
    return JSON.stringify(body, null, 2);
  } catch {
    return null;
  }
};

const formatStatusLine = (status, response) => {
  const reason = response?.statusText?.trim();
  const label = reason || STATUS_LABELS[status] || 'Request failed';
  return `${status} - ${label}`;
};

export const formatApiError = (error) => {
  if (!error || !error.status) {
    return (error && error.message) || 'Unknown error';
  }

  const { status, body, response } = error;

  if (body && typeof body === 'object') {
    const formatted = formatJsonErrorBody(body);
    if (formatted) return formatted;
  }

  const text =
    typeof body === 'string' ? body.trim() : body == null ? '' : String(body);

  // Sniff leading '<' only when Content-Type is missing.
  const contentType = (
    response?.headers?.get?.('content-type') || ''
  ).toLowerCase();
  const isMarkup =
    contentType.includes('html') ||
    contentType.includes('xml') ||
    (!contentType && text.startsWith('<'));

  if (!text || isMarkup) {
    if (text) {
      console.debug(`API error ${status} response body:`, text);
    }
    return formatStatusLine(status, response);
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
