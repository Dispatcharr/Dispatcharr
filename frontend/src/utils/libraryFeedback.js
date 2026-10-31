import { formatApiError } from '../utils';
import { showNotification } from './notificationUtils.js';

export function notifyLibraryError(error, title = 'Library', id) {
  showNotification({
    title,
    message: formatApiError(error),
    color: 'red',
    ...(id ? { id } : {}),
  });
}

export function notifyLibrarySuccess(message) {
  showNotification({
    title: 'Library',
    message,
    color: 'green',
    autoClose: 2000,
  });
}

export function libraryFieldError(error, path) {
  if (!error) return false;
  const body = error.body;
  if (
    !body ||
    typeof body !== 'object' ||
    Array.isArray(body) ||
    body.detail ||
    body.error ||
    body.non_field_errors
  )
    return true;
  return !!path.split('.').reduce((value, key) => value?.[key], body);
}
