// Helper function to format timestamps
import API from '../../api.js';

export const formatTimestamp = (timestamp) => {
  if (!timestamp) return 'Unknown';
  try {
    const date =
      typeof timestamp === 'string' && timestamp.includes('T')
        ? new Date(timestamp) // This should handle ISO format properly
        : new Date(parseInt(timestamp) * 1000);

    // Convert to user's local time and display with timezone
    return date.toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      timeZoneName: 'short',
    });
  } catch {
    return 'Invalid date';
  }
};

// Helper function to get time remaining
export const getTimeRemaining = (expTimestamp) => {
  if (!expTimestamp) return null;

  try {
    const now = new Date();
    const expDate = new Date(parseInt(expTimestamp) * 1000);
    const diffMs = expDate - now;

    if (diffMs <= 0) return 'Expired';

    const MS_PER_HOUR = 1000 * 60 * 60;
    const MS_PER_DAY = MS_PER_HOUR * 24;

    const days = Math.floor(diffMs / MS_PER_DAY);
    const hours = Math.floor((diffMs % MS_PER_DAY) / MS_PER_HOUR);

    const dayLabel = `${days} ${days === 1 ? 'day' : 'days'}`;
    const hourLabel = `${hours} ${hours === 1 ? 'hour' : 'hours'}`;

    return days > 0 ? `${dayLabel} ${hourLabel}` : hourLabel;
  } catch {
    return 'Unknown';
  }
};

export const refreshAccountInfo = (currentProfile) => {
  return API.refreshAccountInfo(currentProfile.id);
};
