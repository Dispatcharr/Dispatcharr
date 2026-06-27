import API from '../../api.js';

export const updateOutputProfile = (values) => API.updateOutputProfile(values);
export const deleteOutputProfile = async (id) => {
  await API.deleteOutputProfile(id);
};
