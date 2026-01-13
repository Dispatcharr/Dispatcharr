import API from '../../../api.js';

export const getComskipConfig = async () => {
  return await API.getComskipConfig();
};

export const uploadComskipIni = async (file) => {
  return await API.uploadComskipIni(file);
};

export const getDvrSettingsFormInitialValues = () => {
  return {
    'tv_template': '',
    'movie_template': '',
    'tv_fallback_template': '',
    'movie_fallback_template': '',
    'comskip_enabled': false,
    'comskip_custom_path': '',
    'pre_offset_minutes': 0,
    'post_offset_minutes': 0,
  };
};