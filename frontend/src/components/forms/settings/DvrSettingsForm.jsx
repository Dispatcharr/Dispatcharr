import useSettingsStore from '../../../store/settings.jsx';
import React, { useEffect, useState } from 'react';
import {
  getChangedSettings,
  parseSettings,
  saveChangedSettings,
} from '../../../utils/pages/SettingsUtils.js';
import { showNotification } from '../../../utils/notificationUtils.js';
import {
  Alert,
  Button,
  FileInput,
  Flex,
  Group,
  NumberInput,
  Stack,
  Switch,
  Text,
  TextInput,
} from '@mantine/core';
import {
  getComskipConfig,
  getDvrSettingsFormInitialValues,
  uploadComskipIni,
} from '../../../utils/forms/settings/DvrSettingsFormUtils.js';
import { useForm } from '@mantine/form';

const DvrSettingsForm = React.memo(({ active }) => {
  const settings = useSettingsStore((s) => s.settings);
  const [saved, setSaved] = useState(false);
  const [comskipFile, setComskipFile] = useState(null);
  const [comskipUploadLoading, setComskipUploadLoading] = useState(false);
  const [comskipConfig, setComskipConfig] = useState({
    path: '',
    exists: false,
  });

  const form = useForm({
    mode: 'controlled',
    initialValues: getDvrSettingsFormInitialValues(),
  });

  useEffect(() => {
    if (!active) setSaved(false);
  }, [active]);

  useEffect(() => {
    if (settings) {
      const formValues = parseSettings(settings);

      form.setValues(formValues);

      if (formValues['dvr-comskip-custom-path']) {
        setComskipConfig((prev) => ({
          path: formValues['dvr-comskip-custom-path'],
          exists: prev.exists,
        }));
      }
    }
  }, [settings]);

  useEffect(() => {
    const loadComskipConfig = async () => {
      try {
        const response = await getComskipConfig();
        if (response) {
          setComskipConfig({
            path: response.path || '',
            exists: Boolean(response.exists),
          });
          if (response.path) {
            form.setFieldValue('dvr-comskip-custom-path', response.path);
          }
        }
      } catch (error) {
        console.error('Failed to load comskip config', error);
      }
    };
    loadComskipConfig();
  }, []);

  const onComskipUpload = async () => {
    if (!comskipFile) {
      return;
    }

    setComskipUploadLoading(true);
    try {
      const response = await uploadComskipIni(comskipFile);
      if (response?.path) {
        showNotification({
          title: 'comskip.ini uploaded',
          message: response.path,
          autoClose: 3000,
          color: 'green',
        });
        form.setFieldValue('dvr-comskip-custom-path', response.path);
        useSettingsStore.getState().updateSetting({
          ...(settings['dvr-comskip-custom-path'] || {
            key: 'dvr-comskip-custom-path',
            name: 'DVR Comskip Custom Path',
          }),
          value: response.path,
        });
        setComskipConfig({ path: response.path, exists: true });
      }
    } catch (error) {
      console.error('Failed to upload comskip.ini', error);
    } finally {
      setComskipUploadLoading(false);
      setComskipFile(null);
    }
  };

  const onSubmit = async () => {
    setSaved(false);

    const changedSettings = getChangedSettings(form.getValues(), settings);

    // Update each changed setting in the backend (create if missing)
    try {
      await saveChangedSettings(settings, changedSettings);

      setSaved(true);
    } catch (error) {
      // Error notifications are already shown by API functions
      // Just don't show the success message
      console.error('Error saving settings:', error);
    }
  };

  return (
    <form onSubmit={form.onSubmit(onSubmit)}>
      <Stack gap="sm">
        {saved && (
          <Alert variant="light" color="green" title="Saved Successfully" />
        )}
        <Switch
          label="Enable Comskip (remove commercials after recording)"
          {...form.getInputProps('dvr-comskip-enabled', {
            type: 'checkbox',
          })}
          id={settings['dvr-comskip-enabled']?.id || 'dvr-comskip-enabled'}
          name={settings['dvr-comskip-enabled']?.key || 'dvr-comskip-enabled'}
        />
        <TextInput
          label="Custom comskip.ini path"
          description="Leave blank to use the built-in defaults."
          placeholder="/app/docker/comskip.ini"
          {...form.getInputProps('dvr-comskip-custom-path')}
          id={
            settings['dvr-comskip-custom-path']?.id || 'dvr-comskip-custom-path'
          }
          name={
            settings['dvr-comskip-custom-path']?.key ||
            'dvr-comskip-custom-path'
          }
        />
        <Group align="flex-end" gap="sm">
          <FileInput
            placeholder="Select comskip.ini"
            accept=".ini"
            value={comskipFile}
            onChange={setComskipFile}
            clearable
            disabled={comskipUploadLoading}
            flex={1}
          />
          <Button
            variant="light"
            onClick={onComskipUpload}
            disabled={!comskipFile || comskipUploadLoading}
          >
            {comskipUploadLoading ? 'Uploading...' : 'Upload comskip.ini'}
          </Button>
        </Group>
        <Text size="xs" c="dimmed">
          {comskipConfig.exists && comskipConfig.path
            ? `Using ${comskipConfig.path}`
            : 'No custom comskip.ini uploaded.'}
        </Text>
        <NumberInput
          label="Start early (minutes)"
          description="Begin recording this many minutes before the scheduled start."
          min={0}
          step={1}
          {...form.getInputProps('dvr-pre-offset-minutes')}
          id={
            settings['dvr-pre-offset-minutes']?.id || 'dvr-pre-offset-minutes'
          }
          name={
            settings['dvr-pre-offset-minutes']?.key || 'dvr-pre-offset-minutes'
          }
        />
        <NumberInput
          label="End late (minutes)"
          description="Continue recording this many minutes after the scheduled end."
          min={0}
          step={1}
          {...form.getInputProps('dvr-post-offset-minutes')}
          id={
            settings['dvr-post-offset-minutes']?.id || 'dvr-post-offset-minutes'
          }
          name={
            settings['dvr-post-offset-minutes']?.key ||
            'dvr-post-offset-minutes'
          }
        />
        <TextInput
          label="TV Path Template"
          description="Supports {show}, {season}, {episode}, {sub_title}, {channel}, {year}, {start}, {end}. Use format specifiers like {season:02d}. Relative paths are under your library dir."
          placeholder="TV_Shows/{show}/S{season:02d}E{episode:02d}.mkv"
          {...form.getInputProps('dvr-tv-template')}
          id={settings['dvr-tv-template']?.id || 'dvr-tv-template'}
          name={settings['dvr-tv-template']?.key || 'dvr-tv-template'}
        />
        <TextInput
          label="TV Fallback Template"
          description="Template used when an episode has no season/episode. Supports {show}, {start}, {end}, {channel}, {year}."
          placeholder="TV_Shows/{show}/{start}.mkv"
          {...form.getInputProps('dvr-tv-fallback-template')}
          id={
            settings['dvr-tv-fallback-template']?.id ||
            'dvr-tv-fallback-template'
          }
          name={
            settings['dvr-tv-fallback-template']?.key ||
            'dvr-tv-fallback-template'
          }
        />
        <TextInput
          label="Movie Path Template"
          description="Supports {title}, {year}, {channel}, {start}, {end}. Relative paths are under your library dir."
          placeholder="Movies/{title} ({year}).mkv"
          {...form.getInputProps('dvr-movie-template')}
          id={settings['dvr-movie-template']?.id || 'dvr-movie-template'}
          name={settings['dvr-movie-template']?.key || 'dvr-movie-template'}
        />
        <TextInput
          label="Movie Fallback Template"
          description="Template used when movie metadata is incomplete. Supports {start}, {end}, {channel}."
          placeholder="Movies/{start}.mkv"
          {...form.getInputProps('dvr-movie-fallback-template')}
          id={
            settings['dvr-movie-fallback-template']?.id ||
            'dvr-movie-fallback-template'
          }
          name={
            settings['dvr-movie-fallback-template']?.key ||
            'dvr-movie-fallback-template'
          }
        />
        <Flex mih={50} gap="xs" justify="flex-end" align="flex-end">
          <Button type="submit" variant="default">
            Save
          </Button>
        </Flex>
      </Stack>
    </form>
  );
});

export default DvrSettingsForm;