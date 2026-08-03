import API from '../../api.js';

export const updatePlaylist = (playlist, values, file) => {
  return API.updatePlaylist({
    id: playlist.id,
    ...values,
    file,
  });
};

export const addPlaylist = async (values, file) => {
  return await API.addPlaylist({
    ...values,
    file,
  });
};

export const getPlaylist = async (newPlaylist) => {
  return await API.getPlaylist(newPlaylist.id);
};

export const refreshPlaylist = async (playlist) => {
  return await API.refreshPlaylist(playlist.id);
};

/**
 * Convert a playlist/account exp_date (ISO string or null) to a Date for the picker.
 * @param {string|null|undefined} expDate
 * @returns {Date|null}
 */
export const expDateFromPlaylist = (expDate) => {
  if (!expDate) return null;
  const parsed = new Date(expDate);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
};

/**
 * Stable comparison key for expiration values (Date, ISO string, or null).
 * @param {Date|string|null|undefined} expDate
 * @returns {string|null}
 */
export const expDateKey = (expDate) => {
  if (expDate instanceof Date) {
    return Number.isNaN(expDate.getTime()) ? null : expDate.toISOString();
  }
  if (!expDate) return null;
  const parsed = new Date(expDate);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
};

export const prepareSubmitValues = (values, expDate) => {
  const prepared = { ...values };

  if (prepared.account_type === 'XC') {
    delete prepared.exp_date;
  } else if (expDate instanceof Date) {
    prepared.exp_date = expDate.toISOString();
  } else {
    prepared.exp_date = null;
  }

  const hasCron =
    prepared.cron_expression && prepared.cron_expression.trim() !== '';
  if (hasCron) {
    prepared.refresh_interval = 0;
  } else {
    prepared.cron_expression = '';
  }

  if (prepared.account_type == 'XC' && prepared.password == '') {
    delete prepared.password;
  }

  if (prepared.user_agent == '0') {
    prepared.user_agent = null;
  }

  if (prepared.server_group == '0') {
    prepared.server_group = null;
  }

  return prepared;
};
