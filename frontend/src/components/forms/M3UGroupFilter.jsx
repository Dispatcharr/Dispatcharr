// Modal.js
import React, { useEffect, useState } from 'react';
import {
  Button,
  Flex,
  LoadingOverlay,
  Modal,
  Stack,
  Tabs,
  TabsList,
  TabsPanel,
  TabsTab,
} from '@mantine/core';
import useChannelsStore from '../../store/channels';
import useVODStore from '../../store/useVODStore';
import LiveGroupFilter from './LiveGroupFilter';
import VODCategoryFilter from './VODCategoryFilter';
import { showNotification } from '../../utils/notificationUtils.js';
import {
  buildGroupStates,
  saveAndRefreshPlaylist,
} from '../../utils/forms/M3uGroupFilterUtils.js';

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
    if (Object.keys(channelGroups).length === 0) return;
    setGroupStates(buildGroupStates(channelGroups, playlist.channel_groups));
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
      await saveAndRefreshPlaylist(
        playlist,
        groupStates,
        movieCategoryStates,
        seriesCategoryStates,
        {
          auto_enable_new_groups_live: autoEnableNewGroupsLive,
          auto_enable_new_groups_vod: autoEnableNewGroupsVod,
          auto_enable_new_groups_series: autoEnableNewGroupsSeries,
        }
      );

      showNotification({
        title: 'Group Settings Updated',
        message: 'Settings saved. Starting M3U refresh to apply changes...',
        color: 'green',
        autoClose: 3000,
      });

      showNotification({
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
      scrollAreaComponent={Modal.NativeScrollArea}
      lockScroll={false}
      withinPortal={true}
      yOffset="2vh"
    >
      <LoadingOverlay visible={isLoading} overlayBlur={2} />
      <Stack>
        <Tabs defaultValue="live">
          <TabsList>
            <TabsTab value="live">Live</TabsTab>
            <TabsTab value="vod-movie">VOD - Movies</TabsTab>
            <TabsTab value="vod-series">VOD - Series</TabsTab>
          </TabsList>

          <TabsPanel value="live">
            <LiveGroupFilter
              playlist={playlist}
              groupStates={groupStates}
              setGroupStates={setGroupStates}
              autoEnableNewGroupsLive={autoEnableNewGroupsLive}
              setAutoEnableNewGroupsLive={setAutoEnableNewGroupsLive}
            />
          </TabsPanel>

          <TabsPanel value="vod-movie">
            <VODCategoryFilter
              playlist={playlist}
              categoryStates={movieCategoryStates}
              setCategoryStates={setMovieCategoryStates}
              type="movie"
              autoEnableNewGroups={autoEnableNewGroupsVod}
              setAutoEnableNewGroups={setAutoEnableNewGroupsVod}
            />
          </TabsPanel>

          <TabsPanel value="vod-series">
            <VODCategoryFilter
              playlist={playlist}
              categoryStates={seriesCategoryStates}
              setCategoryStates={setSeriesCategoryStates}
              type="series"
              autoEnableNewGroups={autoEnableNewGroupsSeries}
              setAutoEnableNewGroups={setAutoEnableNewGroupsSeries}
            />
          </TabsPanel>
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
