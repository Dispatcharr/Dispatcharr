import API from '../../api.js';

export const addM3UFilter = async (m3u, values) => {
  return API.addM3UFilter(m3u.id, values);
};
export const updateM3UFilter = (m3u, filter, values) => {
  return API.updateM3UFilter(m3u.id, filter.id, values);
};
export const deleteM3UFilter = async (playlist, id) => {
  await API.deleteM3UFilter(playlist.id, id);
};
