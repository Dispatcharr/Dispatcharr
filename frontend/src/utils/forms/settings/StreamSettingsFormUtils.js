import { isNotEmpty } from '@mantine/form';

export const getStreamSettingsFormInitialValues = () => {
  return {
    default_user_agent: '',
    default_stream_profile: '',
    preferred_region: '',
    auto_import_mapped_files: true,
    m3u_hash_key: [],
  };
};

export const getStreamSettingsFormValidation = () => {
  return {
    default_user_agent: isNotEmpty('Select a user agent'),
    default_stream_profile: isNotEmpty('Select a stream profile'),
    preferred_region: isNotEmpty('Select a region'),
  };
};
