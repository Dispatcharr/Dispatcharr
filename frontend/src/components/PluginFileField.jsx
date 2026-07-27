import React, { useState } from 'react';
import { FileInput, Stack, Text } from '@mantine/core';
import { uploadPluginFieldFile } from '../utils/pages/PluginsUtils.js';
import { showNotification } from '../utils/notificationUtils.js';

export const PluginFileField = ({ field, value, onChange, pluginKey }) => {
  const [uploading, setUploading] = useState(false);
  const currentName = value ? value.split('/').pop() : null;

  const handleChange = async (file) => {
    if (!file) return;
    setUploading(true);
    try {
      const response = await uploadPluginFieldFile(pluginKey, field.id, file);
      if (response?.success) {
        onChange(field.id, response.path);
      } else {
        showNotification({
          title: 'Upload failed',
          message: response?.error || 'Failed to upload file',
          color: 'red',
        });
      }
    } catch (e) {
      showNotification({
        title: 'Upload failed',
        message: e?.message || 'Failed to upload file',
        color: 'red',
      });
    } finally {
      setUploading(false);
    }
  };

  return (
    <Stack gap={4}>
      <FileInput
        label={field.label}
        description={field.help_text ?? field.description}
        placeholder={uploading ? 'Uploading...' : field.placeholder || 'Choose file'}
        accept={field.accept}
        disabled={uploading}
        onChange={handleChange}
      />
      {currentName && (
        <Text size="xs" c="dimmed">
          Current: {currentName}
        </Text>
      )}
    </Stack>
  );
};
