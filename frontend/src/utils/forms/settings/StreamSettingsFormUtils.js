import { isNotEmpty } from '@mantine/form';

export const getStreamSettingsFormInitialValues = () => {
  return {
    default_user_agent: '',
    default_stream_profile: '',
    m3u_hash_key: [],
    default_output_format: 'mpegts',
    hdhr_output_profile_id: null,
  };
};

export const getStreamSettingsFormValidation = () => {
  return {
    default_user_agent: isNotEmpty('Select a user agent'),
    default_stream_profile: isNotEmpty('Select a stream profile'),
  };
};
