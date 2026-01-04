import { isNotEmpty } from '@mantine/form';

export const getStreamSettingsFormInitialValues = () => {
  return {
    'default-user-agent': '',
    'default-stream-profile': '',
    'preferred-region': '',
    'auto-import-mapped-files': true,
    'm3u-hash-key': [],
  };
};

export const getStreamSettingsFormValidation = () => {
  return {
    'default-user-agent': isNotEmpty('Select a user agent'),
    'default-stream-profile': isNotEmpty('Select a stream profile'),
    'preferred-region': isNotEmpty('Select a region'),
  };
};