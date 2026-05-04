// frontend/src/components/FloatingVideo.js
import React, { useEffect, useState } from 'react';
import usePlaylistsStore from '../store/playlists';
import useStreamsStore from '../store/streams';
import useChannelsStore from '../store/channels';
import useEPGsStore from '../store/epgs';
import useVODStore from '../store/useVODStore';
import {
  Stack,
  Button,
  Group,
  Modal,
  ScrollArea,
  Text,
  Code,
} from '@mantine/core';
import API from '../api';
import { useNavigate } from 'react-router-dom';
import { CircleCheck } from 'lucide-react';
import { showNotification } from '../utils/notificationUtils.js';

const M3uSetupSuccess = ({ data }) => {
  const navigate = useNavigate();

  const onClickRefresh = () => {
    API.refreshPlaylist(data.account);
  };

  const onClickConfigure = () => {
    // Store the ID we want to edit in the store first
    usePlaylistsStore.getState().setEditPlaylistId(data.account);

    // Then navigate to the content sources page
    // Using the exact path that matches your app's routing structure
    navigate('/sources');
  };

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
};

// One-line outcome summary for the notification body.
const buildAutoSyncSummary = (data) => {
  const created = data.channels_created || 0;
  const updated = data.channels_updated || 0;
  const deleted = data.channels_deleted || 0;
  const failed = data.channels_failed || 0;
  if (!created && !updated && !deleted && !failed) return null;
  const parts = [];
  if (created) parts.push(`${created} created`);
  if (updated) parts.push(`${updated} updated`);
  if (deleted) parts.push(`${deleted} deleted`);
  if (failed) parts.push(`${failed} failed`);
  return `Auto-sync: ${parts.join(', ')}.`;
};

// Human labels for the typed failure reasons attached to each
// failed_stream_details entry. Unknown reasons fall back to the raw
// key so a future reason added on the backend still surfaces in the
// modal without a code change here.
const FAILURE_REASON_LABELS = {
  RANGE_EXHAUSTED: 'Channel number range exhausted',
  INTEGRITY_ERROR: 'Database integrity error',
  OTHER: 'Other errors',
};

const FAILURES_PER_GROUP_LIMIT = 50;

// Group entries by their reason key, preserving insertion order so
// section ordering reflects the sync's encounter order. Entries
// without a reason field bucket into OTHER so a backend that does
// not classify failures still renders correctly.
const groupFailuresByReason = (entries) => {
  const buckets = new Map();
  for (const entry of entries) {
    const key = entry?.reason || 'OTHER';
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(entry);
  }
  return buckets;
};

export default function M3URefreshNotification() {
  const playlists = usePlaylistsStore((s) => s.playlists);
  const refreshProgress = usePlaylistsStore((s) => s.refreshProgress);
  const fetchStreams = useStreamsStore((s) => s.fetchStreams);
  const fetchChannelGroups = useChannelsStore((s) => s.fetchChannelGroups);
  const fetchChannelIds = useChannelsStore((s) => s.fetchChannelIds);
  const fetchPlaylists = usePlaylistsStore((s) => s.fetchPlaylists);
  const fetchEPGData = useEPGsStore((s) => s.fetchEPGData);
  const fetchCategories = useVODStore((s) => s.fetchCategories);

  const [notificationStatus, setNotificationStatus] = useState({});
  // Modal payload for the "Click for details" affordance on syncs that
  // produced failed_stream_details. Null when the modal is closed.
  const [failureModal, setFailureModal] = useState(null);

  const handleM3UUpdate = (data) => {
    // Skip if status hasn't changed
    if (
      JSON.stringify(notificationStatus[data.account]) == JSON.stringify(data)
    ) {
      return;
    }

    const playlist = playlists.find((pl) => pl.id == data.account);
    if (!playlist) {
      return;
    }

    // Update notification status
    setNotificationStatus((prev) => ({
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
    const currentStatus = notificationStatus[data.account];
    if (currentStatus && currentStatus.status === 'error') {
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
      fetchChannelIds();
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
    let message =
      data.progress == 0
        ? `${baseMessage} starting...`
        : `${baseMessage} complete!`;

    if (data.progress == 100) {
      triggerPostCompletionFetches(data.action);
    }

    let body = message;
    let autoClose = 2000;
    // Surface auto-sync counts attached to the parsing-complete event
    // so the channel-side outcome appears in the notification body.
    if (data.progress == 100 && data.action === 'parsing') {
      const autoSyncSummary = buildAutoSyncSummary(data);
      const failed = data.channels_failed || 0;
      const failedDetails = Array.isArray(data.failed_stream_details)
        ? data.failed_stream_details
        : [];
      if (autoSyncSummary) {
        body = (
          <Stack gap={4}>
            <Text size="sm">{message}</Text>
            <Text size="xs" c="dimmed">
              {autoSyncSummary}
            </Text>
            {failed > 0 && failedDetails.length > 0 && (
              <Button
                size="xs"
                variant="subtle"
                color="yellow"
                onClick={() =>
                  setFailureModal({
                    playlistName: playlist.name,
                    failedDetails,
                  })
                }
              >
                Click for details
              </Button>
            )}
          </Stack>
        );
        autoClose = failed > 0 ? 12000 : 4000;
      }
    }

    showNotification({
      title: `M3U Processing: ${playlist.name}`,
      message: body,
      loading: data.progress == 0,
      autoClose,
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

  return (
    <Modal
      opened={!!failureModal}
      onClose={() => setFailureModal(null)}
      title={
        failureModal
          ? `Auto-sync failures: ${failureModal.playlistName}`
          : 'Auto-sync failures'
      }
      size="lg"
    >
      <Stack>
        <Text size="sm" c="dimmed">
          The following streams could not be synced. Failures are grouped by
          cause so the most common issues surface first.
        </Text>
        <ScrollArea h={360}>
          <Stack gap="md">
            {Array.from(
              groupFailuresByReason(failureModal?.failedDetails || []).entries()
            ).map(([reasonKey, entries]) => {
              const label = FAILURE_REASON_LABELS[reasonKey] || reasonKey;
              const visible = entries.slice(0, FAILURES_PER_GROUP_LIMIT);
              const hidden = entries.length - visible.length;
              return (
                <Stack key={reasonKey} gap="xs">
                  <Text size="sm" fw={600}>
                    {label} ({entries.length})
                  </Text>
                  {visible.map((entry, idx) => (
                    <Code
                      block
                      key={`${reasonKey}-${entry.stream_id ?? 'na'}-${idx}`}
                    >
                      {[
                        entry.stream_name && `Stream: ${entry.stream_name}`,
                        entry.group && `Group: ${entry.group}`,
                        entry.error && `Error: ${entry.error}`,
                      ]
                        .filter(Boolean)
                        .join('\n')}
                    </Code>
                  ))}
                  {hidden > 0 && (
                    <Text size="xs" c="dimmed">
                      Showing first {visible.length} of {entries.length}.
                      Remaining {hidden} entries are recorded in the server log.
                    </Text>
                  )}
                </Stack>
              );
            })}
          </Stack>
        </ScrollArea>
      </Stack>
    </Modal>
  );
}
