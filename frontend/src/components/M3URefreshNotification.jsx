// frontend/src/components/FloatingVideo.js
import React, { useEffect, useState } from 'react';
import usePlaylistsStore from '../store/playlists';
import useStreamsStore from '../store/streams';
import useChannelsStore from '../store/channels';
import useEPGsStore from '../store/epgs';
import useVODStore from '../store/useVODStore';
import { Stack, Button, Group } from '@mantine/core';
import API from '../api';
import { useNavigate } from 'react-router-dom';
import { CircleCheck } from 'lucide-react';
import { showNotification } from '../utils/notificationUtils.js';

const M3uSetupSuccess = (data) => {
  const navigate = useNavigate();

  const onClickRefresh = () => {
    API.refreshPlaylist(data.account);
  }

  const onClickConfigure = () => {
    // Store the ID we want to edit in the store first
    usePlaylistsStore.getState().setEditPlaylistId(data.account);

    // Then navigate to the content sources page
    // Using the exact path that matches your app's routing structure
    navigate('/sources');
  }

  return (
    <Stack>
      {data.message ||
        'M3U groups loaded. Configure group filters and auto channel sync settings.'}
      <Group grow>
        <Button size="xs" variant="default" onClick={onClickRefresh}>
          Refresh Now
        </Button>
        <Button size="xs" variant="outline" onClick={onClickConfigure}>
          Configure Groups
        </Button>
      </Group>
    </Stack>
  );
}

export default function M3URefreshNotification() {
  const playlists = usePlaylistsStore((s) => s.playlists);
  const refreshProgress = usePlaylistsStore((s) => s.refreshProgress);
  const fetchStreams = useStreamsStore((s) => s.fetchStreams);
  const fetchChannelGroups = useChannelsStore((s) => s.fetchChannelGroups);
  const fetchChannels = useChannelsStore((s) => s.fetchChannels);
  const fetchPlaylists = usePlaylistsStore((s) => s.fetchPlaylists);
  const fetchEPGData = useEPGsStore((s) => s.fetchEPGData);
  const fetchCategories = useVODStore((s) => s.fetchCategories);

  const [notificationStatus, setNotificationStatus] = useState({});

  const handleM3UUpdate = (data) => {
    // Skip if status hasn't changed
    if (JSON.stringify(notificationStatus[data.account]) == JSON.stringify(data)) {
      return;
    }

    const playlist = playlists.find((pl) => pl.id == data.account);
    if (!playlist) return;

    // Update notification status
    setNotificationStatus(prev => ({
      ...prev,
      [data.account]: data,
    }));

    // Handle different status types
    if (data.status === 'pending_setup') {
      handlePendingSetup(playlist, data);
      return;
    }

    if (data.status === 'error') {
      handleError(playlist, data);
      return;
    }

    // Skip if already errored
    if (notificationStatus[data.account]?.status === 'error') {
      return;
    }

    // Handle normal progress updates (0% start, 100% completion)
    if (data.progress === 0 || data.progress === 100) {
      handleProgressNotification(playlist, data);
    }
  };

  const handlePendingSetup = (playlist, data) => {
    fetchChannelGroups();
    fetchPlaylists();

    showNotification({
      title: `M3U Setup: ${playlist.name}`,
      message: <M3uSetupSuccess data={data} />,
      color: 'orange.5',
      autoClose: 5000,
    });
  };

  const handleError = (playlist, data) => {
    if (data.progress === 100) {
      showNotification({
        title: `M3U Processing: ${playlist.name}`,
        message: `${data.action || 'Processing'} failed: ${data.error || 'Unknown error'}`,
        color: 'red',
        autoClose: 5000,
      });
    }
  };

  const getActionMessage = (action) => {
    const messages = {
      downloading: 'Downloading',
      parsing: 'Stream parsing',
      processing_groups: 'Group parsing',
      vod_refresh: 'VOD content refresh',
    };
    return messages[action] || 'Processing';
  };

  const triggerPostCompletionFetches = (action) => {
    if (action == 'parsing') {
      fetchStreams();
      API.requeryChannels();
      fetchChannels();
    } else if (action == 'processing_groups') {
      fetchStreams();
      fetchChannelGroups();
      fetchEPGData();
      fetchPlaylists();
    } else if (action == 'vod_refresh') {
      fetchPlaylists();
      fetchCategories();
    }
  };

  const handleProgressNotification = (playlist, data) => {
    const baseMessage = getActionMessage(data.action);
    const message = data.progress == 0
      ? `${baseMessage} starting...`
      : `${baseMessage} complete!`;

    if (data.progress == 100) {
      triggerPostCompletionFetches(data.action);
    }

    showNotification({
      title: `M3U Processing: ${playlist.name}`,
      message,
      loading: data.progress == 0,
      autoClose: 2000,
      icon: data.progress == 100 ? <CircleCheck /> : null,
    });
  };

  useEffect(() => {
    // Reset notificationStatus when playlists change to prevent stale data
    if (playlists.length > 0 && Object.keys(notificationStatus).length > 0) {
      const validIds = playlists.map((p) => p.id);
      const currentIds = Object.keys(notificationStatus).map(Number);

      // If we have notification statuses for playlists that no longer exist, reset the state
      if (!currentIds.every((id) => validIds.includes(id))) {
        setNotificationStatus({});
      }
    }

    // Process all refresh progress updates
    Object.values(refreshProgress).map((data) => handleM3UUpdate(data));
  }, [playlists, refreshProgress]);

  return <></>;
}
