import API from '../../../api.js';

export const getComskipConfig = async () => {
  return await API.getComskipConfig();
};

export const uploadComskipIni = async (file) => {
  return await API.uploadComskipIni(file);
};

export const getDvrSettingsFormInitialValues = () => {
  return {
    'dvr-tv-template': '',
    'dvr-movie-template': '',
    'dvr-tv-fallback-template': '',
    'dvr-movie-fallback-template': '',
    'dvr-comskip-enabled': false,
    'dvr-comskip-custom-path': '',
    'dvr-pre-offset-minutes': 0,
    'dvr-post-offset-minutes': 0,
  };
};