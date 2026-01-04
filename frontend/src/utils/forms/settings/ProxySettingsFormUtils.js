import { PROXY_SETTINGS_OPTIONS } from '../../../constants.js';

export const getProxySettingsFormInitialValues = () => {
  return Object.keys(PROXY_SETTINGS_OPTIONS).reduce((acc, key) => {
    acc[key] = '';
    return acc;
  }, {});
};

export const getProxySettingDefaults = () => {
  return {
    buffering_timeout: 15,
    buffering_speed: 1.0,
    redis_chunk_ttl: 60,
    channel_shutdown_delay: 0,
    channel_init_grace_period: 5,
  };
};