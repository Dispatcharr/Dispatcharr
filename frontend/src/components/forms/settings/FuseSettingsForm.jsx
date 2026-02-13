import React, { useEffect, useState } from 'react';
import { useForm } from '@mantine/form';
import {
  Alert,
  Button,
  Flex,
  Stack,
  Switch,
  Text,
  TextInput,
} from '@mantine/core';
import useSettingsStore from '../../../store/settings.jsx';
import {
  createSetting,
  updateSetting,
} from '../../../utils/pages/SettingsUtils.js';

const getFuseSettingsFormInitialValues = () => ({
  enable_fuse: false,
  backend_base_url: '',
  movies_mount_path: '/mnt/vod_movies',
  tv_mount_path: '/mnt/vod_tv',
});

const FuseSettingsForm = React.memo(({ active }) => {
  const settings = useSettingsStore((s) => s.settings);
  const [saved, setSaved] = useState(false);

  const form = useForm({
    mode: 'controlled',
    initialValues: getFuseSettingsFormInitialValues(),
  });

  useEffect(() => {
    if (!active) {
      setSaved(false);
    }
  }, [active]);

  useEffect(() => {
    const fuseSettings = settings?.fuse_settings?.value;
    if (!fuseSettings || typeof fuseSettings !== 'object') {
      return;
    }

    form.setValues({
      enable_fuse: Boolean(fuseSettings.enable_fuse),
      backend_base_url: fuseSettings.backend_base_url || '',
      movies_mount_path: fuseSettings.movies_mount_path || '/mnt/vod_movies',
      tv_mount_path: fuseSettings.tv_mount_path || '/mnt/vod_tv',
    });
  }, [form, settings]);

  const onSubmit = async () => {
    setSaved(false);
    const payload = {
      enable_fuse: Boolean(form.values.enable_fuse),
      backend_base_url: (form.values.backend_base_url || '').trim(),
      movies_mount_path:
        (form.values.movies_mount_path || '').trim() || '/mnt/vod_movies',
      tv_mount_path: (form.values.tv_mount_path || '').trim() || '/mnt/vod_tv',
    };

    try {
      const existing = settings?.fuse_settings;
      const result = existing?.id
        ? await updateSetting({
            ...existing,
            value: payload,
          })
        : await createSetting({
            key: 'fuse_settings',
            name: 'Fuse Settings',
            value: payload,
          });

      if (result) {
        setSaved(true);
      }
    } catch (error) {
      // API helpers handle user-facing error notifications.
      console.error('Error saving FUSE settings:', error);
    }
  };

  return (
    <form onSubmit={form.onSubmit(onSubmit)}>
      <Stack gap="sm">
        {saved && <Alert variant="light" color="green" title="Saved Successfully" />}

        <Switch
          label="Enable FUSE integration"
          description="Expose Movies/TV as read-only host-side virtual drives."
          {...form.getInputProps('enable_fuse', { type: 'checkbox' })}
          id="enable_fuse"
          name="enable_fuse"
        />

        <TextInput
          label="Backend Base URL"
          description="Optional override for the host-side client (for example, http://localhost:9191)."
          placeholder="http://localhost:9191"
          {...form.getInputProps('backend_base_url')}
          id="backend_base_url"
          name="backend_base_url"
        />

        <TextInput
          label="Movies Mount Path"
          placeholder="/mnt/vod_movies"
          {...form.getInputProps('movies_mount_path')}
          id="movies_mount_path"
          name="movies_mount_path"
        />

        <TextInput
          label="TV Mount Path"
          placeholder="/mnt/vod_tv"
          {...form.getInputProps('tv_mount_path')}
          id="tv_mount_path"
          name="tv_mount_path"
        />

        <Text size="sm" c="dimmed">
          Install macFUSE/libfuse/WinFsp on the host, then run the provided client
          script to mount VOD drives.
        </Text>

        <Button
          component="a"
          variant="light"
          href="/api/fuse/client-script/"
          download="fuse_client.py"
        >
          Download fuse_client.py
        </Button>

        <Text size="sm" c="dimmed">
          Example (Movies):{' '}
          <code>
            python fuse_client.py --mode movies --backend-url
            http://localhost:9191 --mountpoint /mnt/vod_movies
          </code>
          . Example (TV):{' '}
          <code>
            python fuse_client.py --mode tv --backend-url http://localhost:9191
            --mountpoint /mnt/vod_tv
          </code>
          .
        </Text>

        <Flex justify="flex-end">
          <Button type="submit" disabled={form.submitting} variant="default">
            Save
          </Button>
        </Flex>
      </Stack>
    </form>
  );
});

export default FuseSettingsForm;
