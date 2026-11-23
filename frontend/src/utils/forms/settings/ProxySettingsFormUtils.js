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
    experimental_ingest_buffer: true,
    redis_chunk_ttl: 60,
    channel_shutdown_delay: 0,
    channel_init_grace_period: 60,
    channel_client_wait_period: 5,
    new_client_behind_seconds: 6,
    init_min_buffer_seconds: 2,
    init_buffer_max_wait_seconds: 3,
    stream_startup_timeout: 8,
    connection_timeout: 10,
    validate_redirect_urls: true,
    max_retries: 3,
    stream_retry_timeout: 3,
  };
};
