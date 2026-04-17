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
    new_client_behind_seconds: 5,
    max_retries: 2,
    url_switch_timeout: 20,
    max_stream_switches: 200,
    connection_timeout: 10,
    failover_grace_period: 20,
    chunk_timeout: 5,
    initial_behind_chunks: 4,
    stream_cooldown_enabled: false,
    stream_cooldown_minutes: 10,
    health_check_interval: 5,
  };
};
