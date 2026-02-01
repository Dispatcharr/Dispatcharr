import { useMemo, useState, useEffect, useRef } from 'react';
import {
  Modal,
  Stack,
  Text,
  TagsInput,
  Group,
  Button,
  Loader,
  Radio,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import useSettingsStore from '../../store/settings';
import API from '../../api';
import {
  getChangedSettings,
  saveChangedSettings,
} from '../../utils/pages/SettingsUtils';

// Extract EPG settings directly without parsing all settings
const getEpgSettingsFromStore = (settings) => {
  const epgSettings = settings?.['epg_settings']?.value;
  return {
    epg_match_mode: epgSettings?.epg_match_mode || 'default',
    epg_match_ignore_prefixes: Array.isArray(epgSettings?.epg_match_ignore_prefixes)
      ? epgSettings.epg_match_ignore_prefixes
      : [],
    epg_match_ignore_suffixes: Array.isArray(epgSettings?.epg_match_ignore_suffixes)
      ? epgSettings.epg_match_ignore_suffixes
      : [],
    epg_match_ignore_custom: Array.isArray(epgSettings?.epg_match_ignore_custom)
      ? epgSettings.epg_match_ignore_custom
      : [],
  };
};

const EPGMatchModal = ({
  opened,
  onClose,
  selectedChannelIds = [],
}) => {
  const settings = useSettingsStore((s) => s.settings);

  const [loading, setLoading] = useState(false);
  const [settingsMode, setSettingsMode] = useState('default');

  // Compute form values directly from settings - memoized for performance
  const storedValues = useMemo(
    () => getEpgSettingsFromStore(settings),
    [settings]
  );

  // Local form state
  const [formValues, setFormValues] = useState(storedValues);

  // Track previous opened state to detect transitions
  const prevOpened = useRef(false);

  // Reset to stored values and mode only when modal opens (not on storedValues changes)
  useEffect(() => {
    // Only reset when transitioning from closed to open
    if (opened && !prevOpened.current) {
      setFormValues(storedValues);
      setSettingsMode(storedValues.epg_match_mode);
    }
    prevOpened.current = opened;
  }, [opened, storedValues]);

  const handleConfirm = async () => {
    setLoading(true);
    try {
      // Save mode and settings (backend will ignore custom settings if mode is 'default')
      const settingsToSave = {
        ...formValues,
        epg_match_mode: settingsMode,
      };
      const changedSettings = getChangedSettings(settingsToSave, settings);
      if (Object.keys(changedSettings).length > 0) {
        await saveChangedSettings(settings, changedSettings);
      }

      // Then trigger auto-match
      if (selectedChannelIds.length > 0) {
        await API.matchEpg(selectedChannelIds);
        notifications.show({
          title: `EPG matching started for ${selectedChannelIds.length} selected channel(s)`,
          color: 'green',
        });
      } else {
        await API.matchEpg();
        notifications.show({
          title: 'EPG matching started for all channels without EPG',
          color: 'green',
        });
      }

      onClose();
    } catch (error) {
      console.error('Error during auto-match:', error);
      notifications.show({
        title: 'Error',
        message: error.message || 'Failed to start EPG matching',
        color: 'red',
      });
    } finally {
      setLoading(false);
    }
  };

  const scopeText = selectedChannelIds.length > 0
    ? `${selectedChannelIds.length} selected channel(s)`
    : 'all channels without EPG';

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title="EPG Match Settings"
      size="md"
      centered
    >
      <Stack gap="md">
        <Text size="sm" c="dimmed">
          Match channels to EPG data for {scopeText}.
        </Text>

        <Radio.Group
          value={settingsMode}
          onChange={setSettingsMode}
          label="Matching Mode"
        >
          <Stack gap="xs" mt="xs">
            <Radio
              value="default"
              label="Use default settings"
              description="Recommended for most users. Handles standard channel name variations automatically."
            />
            <Radio
              value="advanced"
              label="Configure advanced options"
              description="Use if channels aren't matching correctly. Add custom prefixes, suffixes, or strings to ignore."
            />
          </Stack>
        </Radio.Group>

        {settingsMode === 'advanced' && (
          <>
            <TagsInput
              label="Ignore Prefixes"
              description="Removed from START of channel names (e.g., Prime:, Sling:, US:)"
              placeholder="Type and press Enter"
              value={formValues.epg_match_ignore_prefixes}
              onChange={(value) =>
                setFormValues((prev) => ({
                  ...prev,
                  epg_match_ignore_prefixes: value,
                }))
              }
              splitChars={[]}
              clearable
            />

            <TagsInput
              label="Ignore Suffixes"
              description="Removed from END of channel names (e.g., HD, 4K, +1)"
              placeholder="Type and press Enter"
              value={formValues.epg_match_ignore_suffixes}
              onChange={(value) =>
                setFormValues((prev) => ({
                  ...prev,
                  epg_match_ignore_suffixes: value,
                }))
              }
              splitChars={[]}
              clearable
            />

            <TagsInput
              label="Ignore Custom Strings"
              description="Removed from ANYWHERE in channel names (e.g., 24/7, LIVE)"
              placeholder="Type and press Enter"
              value={formValues.epg_match_ignore_custom}
              onChange={(value) =>
                setFormValues((prev) => ({
                  ...prev,
                  epg_match_ignore_custom: value,
                }))
              }
              splitChars={[]}
              clearable
            />

            <Text size="xs" c="dimmed">
              Channel display names are never modified. These settings only affect
              the matching algorithm.
            </Text>
          </>
        )}

        <Group justify="flex-end" mt="md">
          <Button variant="default" onClick={onClose} disabled={loading}>
            Cancel
          </Button>
          <Button onClick={handleConfirm} disabled={loading}>
            {loading ? <Loader size="xs" /> : 'Start Auto-Match'}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default EPGMatchModal;
