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

  return prepared;
};
