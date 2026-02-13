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

      if (formValues['comskip_custom_path']) {
        setComskipConfig((prev) => ({
          path: formValues['comskip_custom_path'],
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
            form.setFieldValue('comskip_custom_path', response.path);
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
        form.setFieldValue('comskip_custom_path', response.path);
        useSettingsStore.getState().updateSetting({
          ...(settings['comskip_custom_path'] || {
            key: 'comskip_custom_path',
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
          {...form.getInputProps('comskip_enabled', {
            type: 'checkbox',
          })}
          id="comskip_enabled"
          name="comskip_enabled"
        />
        <TextInput
          label="Custom comskip.ini path"
          description="Leave blank to use the built-in defaults."
          placeholder="/app/docker/comskip.ini"
          {...form.getInputProps('comskip_custom_path')}
          id="comskip_custom_path"
          name="comskip_custom_path"
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
          {...form.getInputProps('pre_offset_minutes')}
          id="pre_offset_minutes"
          name="pre_offset_minutes"
        />
        <NumberInput
          label="End late (minutes)"
          description="Continue recording this many minutes after the scheduled end."
          min={0}
          step={1}
          {...form.getInputProps('post_offset_minutes')}
          id="post_offset_minutes"
          name="post_offset_minutes"
        />
        <TextInput
          label="TV Path Template"
          description="Supports {show}, {season}, {episode}, {sub_title}, {channel}, {year}, {start}, {end}. Use format specifiers like {season:02d}. Relative paths are under your library dir."
          placeholder="TV_Shows/{show}/S{season:02d}E{episode:02d}.mkv"
          {...form.getInputProps('tv_template')}
          id="tv_template"
          name="tv_template"
        />
        <TextInput
          label="TV Fallback Template"
          description="Template used when an episode has no season/episode. Supports {show}, {start}, {end}, {channel}, {year}."
          placeholder="TV_Shows/{show}/{start}.mkv"
          {...form.getInputProps('tv_fallback_template')}
          id="tv_fallback_template"
          name="tv_fallback_template"
        />
        <TextInput
          label="Movie Path Template"
          description="Supports {title}, {year}, {channel}, {start}, {end}. Relative paths are under your library dir."
          placeholder="Movies/{title} ({year}).mkv"
          {...form.getInputProps('movie_template')}
          id="movie_template"
          name="movie_template"
        />
        <TextInput
          label="Movie Fallback Template"
          description="Template used when movie metadata is incomplete. Supports {start}, {end}, {channel}."
          placeholder="Movies/{start}.mkv"
          {...form.getInputProps('movie_fallback_template')}
          id="movie_fallback_template"
          name="movie_fallback_template"
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
