import useSettingsStore from '../../../store/settings.jsx';
import useOutputProfilesStore from '../../../store/outputProfiles.jsx';
import React, { useEffect, useState } from 'react';
import {
  getChangedGroupSettings,
  parseGroupSettings,
  saveGroupSettings,
} from '../../../utils/pages/SettingsUtils.js';
import { showNotification } from '../../../utils/notificationUtils.js';
import useSettingsSaveGuard from '../../../hooks/useSettingsSaveGuard.jsx';
import {
  Alert,
  Button,
  Flex,
  Group,
  NumberInput,
  Select,
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
import { FolderOpen } from 'lucide-react';
import SafeDirectoryBrowser from '../../SafeDirectoryBrowser.jsx';

const DVR_GROUP = 'dvr_settings';

const DvrSettingsForm = React.memo(({ active }) => {
  const settings = useSettingsStore((s) => s.settings);
  const outputProfiles = useOutputProfilesStore((s) => s.profiles);
  const [saved, setSaved] = useState(false);
  const [comskipConfig, setComskipConfig] = useState({
    path: '',
    exists: false,
  });
  const [pathBrowser, setPathBrowser] = useState(null);
  const { isSavingRef, runSave } = useSettingsSaveGuard();

  const form = useForm({
    mode: 'controlled',
    initialValues: getDvrSettingsFormInitialValues(),
  });

  useEffect(() => {
    if (!active) setSaved(false);
  }, [active]);

  useEffect(() => {
    if (settings && !isSavingRef.current) {
      const formValues = parseGroupSettings(settings, DVR_GROUP);

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

  const onComskipUpload = async (file) => {
    try {
      const response = await uploadComskipIni(file);
      if (response?.path) {
        showNotification({
          title: 'comskip.ini uploaded',
          message: response.path,
          autoClose: 3000,
          color: 'green',
        });
        // Backend already persisted the path. Only update local form state here.
        // Writing the Zustand settings store would re-run the hydrate effect and
        // wipe any unsaved edits on other DVR fields.
        form.setFieldValue('comskip_custom_path', response.path);
        setComskipConfig({ path: response.path, exists: true });
      }
      return response;
    } catch (error) {
      console.error('Failed to upload comskip.ini', error);
      throw error;
    }
  };

  const onSubmit = async () => {
    setSaved(false);

    const changedSettings = getChangedGroupSettings(
      form.getValues(),
      settings,
      DVR_GROUP
    );

    try {
      await runSave(async () => {
        await saveGroupSettings(settings, DVR_GROUP, changedSettings);
        const latestSettings = useSettingsStore.getState().settings;
        if (latestSettings) {
          const formValues = parseGroupSettings(latestSettings, DVR_GROUP);
          form.setValues(formValues);
          if (formValues['comskip_custom_path']) {
            setComskipConfig((prev) => ({
              path: formValues['comskip_custom_path'],
              exists: prev.exists,
            }));
          }
        }
        setSaved(true);
      });
    } catch (error) {
      console.error('Error saving settings:', error);
    }
  };

  const browserField =
    pathBrowser === 'comskip' ? 'comskip_custom_path' : 'library_dir';
  const browserInitialPath = form.getValues()[browserField] || '';

  const selectBrowserPath = (path) => {
    form.setFieldValue(browserField, path);
    if (browserField === 'comskip_custom_path') {
      setComskipConfig({ path, exists: true });
    }
    setPathBrowser(null);
  };

  return (
    <>
      <form onSubmit={form.onSubmit(onSubmit)}>
        <Stack gap="sm">
          {saved && (
            <Alert variant="light" color="green" title="Saved Successfully" />
          )}
          <Group align="flex-end" gap="sm" wrap="nowrap">
            <TextInput
              label="Recording library directory"
              description="Completed DVR recordings are saved here and synchronized by the built-in Media Library."
              placeholder="/data/recordings"
              {...form.getInputProps('library_dir')}
              id="library_dir"
              name="library_dir"
              style={{ flex: 1 }}
            />
            <Button
              type="button"
              variant="light"
              leftSection={<FolderOpen size={16} />}
              onClick={() => setPathBrowser('library')}
              aria-label="Browse recording library"
            >
              Browse
            </Button>
          </Group>
          <Switch
            label="Enable Comskip (commercial detection after recording)"
            {...form.getInputProps('comskip_enabled', {
              type: 'checkbox',
            })}
            id="comskip_enabled"
            name="comskip_enabled"
          />
          <Select
            label="Comskip mode"
            description="Cut: permanently removes commercials from the file. Mark: keeps the file intact and writes an EDL file for players that support EDL-based commercial skipping."
            data={[
              { value: 'cut', label: 'Cut (remove commercials from file)' },
              {
                value: 'mark',
                label: 'Mark (store timestamps, keep file intact)',
              },
            ]}
            {...form.getInputProps('comskip_mode')}
            id="comskip_mode"
            name="comskip_mode"
          />
          <Select
            label="Hardware acceleration"
            description="Offloads video decoding to a hardware decoder. Requires the corresponding driver/device to be available inside the container."
            data={[
              { value: 'none', label: 'None (software decode)' },
              { value: 'cuvid', label: 'NVIDIA NVDEC (--cuvid)' },
              { value: 'hwassist', label: 'Hardware assist (--hwassist)' },
            ]}
            {...form.getInputProps('comskip_hw_accel')}
            id="comskip_hw_accel"
            name="comskip_hw_accel"
          />
          <Group align="flex-end" gap="sm" wrap="nowrap">
            <TextInput
              label="Custom comskip.ini path"
              description="Leave blank to use the built-in defaults."
              placeholder="/app/docker/comskip.ini"
              {...form.getInputProps('comskip_custom_path')}
              id="comskip_custom_path"
              name="comskip_custom_path"
              style={{ flex: 1 }}
            />
            <Button
              type="button"
              variant="light"
              leftSection={<FolderOpen size={16} />}
              onClick={() => setPathBrowser('comskip')}
              aria-label="Browse comskip.ini"
            >
              Browse
            </Button>
          </Group>
          <Text size="xs" c="dimmed">
            {comskipConfig.exists && comskipConfig.path
              ? `Using ${comskipConfig.path}`
              : 'No custom comskip.ini uploaded.'}
          </Text>
          <Select
            id="output_profile_id"
            name="output_profile_id"
            label="DVR Output Profile"
            description="Output profile applied when capturing a recording. Leave unset to record the source as-is."
            clearable
            searchable
            placeholder="No transcoding (pass-through)"
            value={
              form.values['output_profile_id'] != null
                ? `${form.values['output_profile_id']}`
                : null
            }
            onChange={(value) =>
              form.setFieldValue(
                'output_profile_id',
                value ? parseInt(value, 10) : null
              )
            }
            data={outputProfiles
              .filter((p) => p.is_active)
              .map((p) => ({ value: `${p.id}`, label: p.name }))}
          />
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
            description="Supports {show}, {season}, {episode}, {sub_title}, {channel}, {year}, {start}, {end}, plus {start_date} and {start_year}, {start_month}, {start_day} for the broadcast date in your system time zone. Use format specifiers like {season:02d} or {start_month:02d}. Relative paths are under your library dir."
            placeholder="TV_Shows/{show}/S{season:02d}E{episode:02d}.mkv"
            {...form.getInputProps('tv_template')}
            id="tv_template"
            name="tv_template"
          />
          <TextInput
            label="TV Fallback Template"
            description="Template used when an episode has no season/episode. Supports {show}, {sub_title}, {start}, {end}, {channel}, {year}, {original_air_date}, plus {start_date} and {start_year}, {start_month}, {start_day} for the broadcast date in your system time zone."
            placeholder="TV_Shows/{show}/{start}.mkv"
            {...form.getInputProps('tv_fallback_template')}
            id="tv_fallback_template"
            name="tv_fallback_template"
          />
          <TextInput
            label="Movie Path Template"
            description="Supports {title}, {year}, {channel}, {start}, {end}, plus {start_date} and {start_year}, {start_month}, {start_day} for the broadcast date in your system time zone. Relative paths are under your library dir."
            placeholder="Movies/{title} ({year}).mkv"
            {...form.getInputProps('movie_template')}
            id="movie_template"
            name="movie_template"
          />
          <TextInput
            label="Movie Fallback Template"
            description="Template used when movie metadata is incomplete. Supports {start}, {end}, {channel}, plus {start_date} and {start_year}, {start_month}, {start_day} for the broadcast date in your system time zone."
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
      <SafeDirectoryBrowser
        opened={pathBrowser !== null}
        onClose={() => setPathBrowser(null)}
        onSelect={selectBrowserPath}
        scope={pathBrowser === 'comskip' ? 'dvr-comskip' : 'dvr-library'}
        initialPath={browserInitialPath}
        onUpload={pathBrowser === 'comskip' ? onComskipUpload : undefined}
        uploadAccept=".ini"
        uploadLabel="Upload comskip.ini"
        title={
          pathBrowser === 'comskip'
            ? 'Select comskip.ini'
            : 'Select recording library directory'
        }
      />
    </>
  );
});

export default DvrSettingsForm;
