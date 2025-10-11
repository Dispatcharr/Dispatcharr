// Modal.js
import React, { useState, useEffect, forwardRef } from 'react';
import { useFormik } from 'formik';
import * as Yup from 'yup';
import API from '../../api';
import M3UProfiles from './M3UProfiles';
import {
  LoadingOverlay,
  TextInput,
  Button,
  Checkbox,
  Modal,
  Flex,
  NativeSelect,
  FileInput,
  Select,
  Space,
  Chip,
  Stack,
  Group,
  Center,
  SimpleGrid,
  Text,
  NumberInput,
  Divider,
  Alert,
  Box,
  MultiSelect,
  Tooltip,
  Tabs,
} from '@mantine/core';
import { Info } from 'lucide-react';
import useChannelsStore from '../../store/channels';
import useVODStore from '../../store/useVODStore';
import { CircleCheck, CircleX } from 'lucide-react';
import { notifications } from '@mantine/notifications';
import LiveGroupFilter from './LiveGroupFilter';
import VODCategoryFilter from './VODCategoryFilter';

// Custom item component for MultiSelect with tooltip
const OptionWithTooltip = forwardRef(
  ({ label, description, ...others }, ref) => (
    <Tooltip label={description} withArrow>
      <div ref={ref} {...others}>
        {label}
      </div>
    </Tooltip>
  )
);

const M3UGroupFilter = ({ playlist = null, isOpen, onClose }) => {
  const channelGroups = useChannelsStore((s) => s.channelGroups);
  const fetchCategories = useVODStore((s) => s.fetchCategories);
  const [groupStates, setGroupStates] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [movieCategoryStates, setMovieCategoryStates] = useState([]);
  const [seriesCategoryStates, setSeriesCategoryStates] = useState([]);
  const [autoEnableNewGroupsLive, setAutoEnableNewGroupsLive] = useState(true);
  const [autoEnableNewGroupsVod, setAutoEnableNewGroupsVod] = useState(true);
  const [autoEnableNewGroupsSeries, setAutoEnableNewGroupsSeries] =
    useState(true);

  useEffect(() => {
    if (!playlist) return;

    // Initialize account-level settings
    setAutoEnableNewGroupsLive(playlist.auto_enable_new_groups_live ?? true);
    setAutoEnableNewGroupsVod(playlist.auto_enable_new_groups_vod ?? true);
    setAutoEnableNewGroupsSeries(
      playlist.auto_enable_new_groups_series ?? true
    );
  }, [playlist]);

  useEffect(() => {
    if (Object.keys(channelGroups).length === 0) {
      return;
    }

    setGroupStates(
      playlist.channel_groups.map((group) => {
        // Parse custom_properties if present
        let customProps = {};
        if (group.custom_properties) {
          try {
            customProps =
              typeof group.custom_properties === 'string'
                ? JSON.parse(group.custom_properties)
                : group.custom_properties;
          } catch (e) {
            customProps = {};
          }
        }
        return {
          ...group,
          name: channelGroups[group.channel_group].name,
          auto_channel_sync: group.auto_channel_sync || false,
          auto_sync_channel_start: group.auto_sync_channel_start || 1.0,
          custom_properties: customProps,
        };
      })
    );
  }, [playlist, channelGroups]);

  // Fetch VOD categories when modal opens for XC accounts with VOD enabled
  useEffect(() => {
    if (
      isOpen &&
      playlist &&
      playlist.account_type === 'XC' &&
      playlist.enable_vod
    ) {
      fetchCategories();
    }
  }, [isOpen, playlist, fetchCategories]);

  const submit = async () => {
    setIsLoading(true);
    try {
      // Prepare groupStates for API
      // Send ALL group states like the original code did, don't filter by enabled changes
      const groupSettings = groupStates.map((state) => ({
        ...state,
        custom_properties: state.custom_properties || undefined,
      }));

      const categorySettings = movieCategoryStates
        .concat(seriesCategoryStates)
        .map((state) => ({
          ...state,
          custom_properties: state.custom_properties || undefined,
        }))
        .filter((state) => state.enabled !== state.original_enabled);

      // Update account-level settings via the proper account endpoint
      await API.updatePlaylist({
        id: playlist.id,
        auto_enable_new_groups_live: autoEnableNewGroupsLive,
        auto_enable_new_groups_vod: autoEnableNewGroupsVod,
        auto_enable_new_groups_series: autoEnableNewGroupsSeries,
      });

      // Update group settings via API endpoint
      await API.updateM3UGroupSettings(
        playlist.id,
        groupSettings,
        categorySettings
      );

      // Show notification about the refresh process
      notifications.show({
        title: 'Group Settings Updated',
        message: 'Settings saved. Starting M3U refresh to apply changes...',
        color: 'green',
        autoClose: 3000,
      });

      // Refresh the playlist - this will handle channel sync automatically at the end
      await API.refreshPlaylist(playlist.id);

      notifications.show({
        title: 'M3U Refresh Started',
        message:
          'The M3U account is being refreshed. Channel sync will occur automatically after parsing completes.',
        color: 'blue',
        autoClose: 5000,
      });

      onClose();
    } catch (error) {
      console.error('Error updating group settings:', error);
    } finally {
      setIsLoading(false);
    }
  };

  if (!isOpen) {
    return <></>;
  }

  return (
    <Modal
      opened={isOpen}
      onClose={onClose}
      title="M3U Group Filter & Auto Channel Sync"
      size={1000}
      styles={{ content: { '--mantine-color-body': '#27272A' } }}
    >
      <LoadingOverlay visible={isLoading} overlayBlur={2} />
      <Stack>
        <Tabs defaultValue="live">
          <Tabs.List>
            <Tabs.Tab value="live">Live</Tabs.Tab>
            <Tabs.Tab value="vod-movie">VOD - Movies</Tabs.Tab>
            <Tabs.Tab value="vod-series">VOD - Series</Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="live">
            <LiveGroupFilter
              playlist={playlist}
              groupStates={groupStates}
              setGroupStates={setGroupStates}
              autoEnableNewGroupsLive={autoEnableNewGroupsLive}
              setAutoEnableNewGroupsLive={setAutoEnableNewGroupsLive}
            />
          </Tabs.Panel>

          <Tabs.Panel value="vod-movie">
            <VODCategoryFilter
              playlist={playlist}
              categoryStates={movieCategoryStates}
              setCategoryStates={setMovieCategoryStates}
              type="movie"
              autoEnableNewGroups={autoEnableNewGroupsVod}
              setAutoEnableNewGroups={setAutoEnableNewGroupsVod}
            />
          </Tabs.Panel>

          <Tabs.Panel value="vod-series">
            <VODCategoryFilter
              playlist={playlist}
              categoryStates={seriesCategoryStates}
              setCategoryStates={setSeriesCategoryStates}
              type="series"
              autoEnableNewGroups={autoEnableNewGroupsSeries}
              setAutoEnableNewGroups={setAutoEnableNewGroupsSeries}
            />
          </Tabs.Panel>
        </Tabs>

        <Flex mih={50} gap="xs" justify="flex-end" align="flex-end">
          <Button variant="default" onClick={onClose} size="xs">
            Cancel
          </Button>
          <Button
            type="submit"
            variant="filled"
            color="blue"
            disabled={isLoading}
            onClick={submit}
          >
            Save and Refresh
          </Button>
        </Flex>
      </Stack>
    </Modal>
  );
};

export default M3UGroupFilter;
