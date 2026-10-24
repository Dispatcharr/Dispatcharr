// frontend/src/components/FloatingVideo.js
import React, { useEffect, useRef, useState } from 'react';
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
  Progress,
} from '@mantine/core';
import API from '../api';
import { useNavigate } from 'react-router-dom';
import { CircleCheck } from 'lucide-react';
import {
  showNotification,
  updateNotification,
  hideNotification,
} from '../utils/notificationUtils.js';
import { getStatusContent } from '../utils/tables/M3UsTableUtils.js';

const RefreshProgress = ({ data }) => {
  const content = getStatusContent(data);
  if (!content) return <Text size="xs">Preparing next phase…</Text>;
  const labels = {
    downloading: 'Downloading',
    parsing: 'Processing streams',
    groups: 'Processing categories',
  };
  const phase =
    content.phase ||
    labels[content.type] ||
    content.label ||
    'Preparing refresh';
  return (
    <Stack gap={4}>
      <Text size="xs">
        {phase}
        {content.progress != null && `: ${content.progress}%`}
      </Text>
      {content.progress != null && (
        <Progress size="xs" value={content.progress} />
      )}
      {content.elapsedTime && (
        <Text size="xs">Elapsed: {content.elapsedTime}</Text>
      )}
      {content.timeRemaining && (
        <Text size="xs">Remaining (estimated): {content.timeRemaining}</Text>
      )}
      {content.speed && <Text size="xs">Speed: {content.speed}</Text>}
      {content.itemsProcessed != null && content.itemsTotal != null && (
        <Text size="xs">
          Catalog entries: {content.itemsProcessed.toLocaleString()} /{' '}
          {content.itemsTotal.toLocaleString()}
        </Text>
      )}
      {content.streamsProcessed != null && (
        <Text size="xs">Streams: {content.streamsProcessed}</Text>
      )}
      {content.groupsProcessed != null && (
        <Text size="xs">Categories: {content.groupsProcessed}</Text>
      )}
    </Stack>
  );
};

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
    navigate('/sources/m3u');
  };

  return (
    <Stack>
      {data.message ||
        'M3U categories loaded. Configure category imports and auto channel sync settings.'}
      <Group grow>
        <Button size="xs" variant="default" onClick={onClickRefresh}>
          Refresh Now
        </Button>
        <Button size="xs" variant="outline" onClick={onClickConfigure}>
          Configure Categories
        </Button>
      </Group>
    </Stack>
  );
};

// One-line outcome summary for the notification body.
const buildStreamSummary = (data) => {
  if (data.streams_processed == null && data.streams_created == null) {
    return null;
  }
  const created = data.streams_created || 0;
  const updated = data.streams_updated || 0;
  const stale = data.streams_stale || 0;
  const removed = data.streams_deleted || 0;
  const processed = data.streams_processed || 0;
  return (
    `Streams: ${created} created, ${updated} updated, ` +
    `${stale} marked stale, ${removed} removed. ` +
    `Total processed: ${processed}.`
  );
};

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

  const notificationStatus = useRef({});
  const visibleNotifications = useRef(new Set());
  // Modal payload for the "Click for details" affordance on syncs that
  // produced failed_stream_details. Null when the modal is closed.
  const [failureModal, setFailureModal] = useState(null);

  const notify = (data, notification) => {
    const kind = data.action === 'vod_refresh' ? 'vod' : 'live';
    const id = `m3u-refresh-${data.account}-${kind}`;
    const options = {
      ...notification,
      id,
      onClose: () => visibleNotifications.current.delete(id),
    };
    if (visibleNotifications.current.has(id)) updateNotification(id, options);
    else {
      visibleNotifications.current.add(id);
      showNotification(options);
    }
  };

  const handleM3UUpdate = (data) => {
    // Skip if status hasn't changed
    if (
      JSON.stringify(notificationStatus.current[data.account]) ==
      JSON.stringify(data)
    ) {
      return;
    }

    const playlist = playlists.find((pl) => pl.id == data.account);
    if (!playlist) {
      return;
    }

    // Update notification status
    notificationStatus.current[data.account] = data;

    // Guided setup owns its handoffs; retain errors, but do not add a
    // second configure/categories prompt or progress toast over its dialog.
    if (playlist.setup_step && data.status !== 'error') {
      if (data.status === 'pending_setup') {
        fetchChannelGroups();
        fetchPlaylists();
      }
      return;
    }

    // Handle different status types
    if (data.status === 'pending_setup') {
      handlePendingSetup(playlist, data);
      return;
    }

    if (data.status === 'error') {
      handleError(playlist, data);
      return;
    }

    handleProgressNotification(playlist, data);
  };

  const handlePendingSetup = (playlist, data) => {
    fetchChannelGroups();
    fetchPlaylists();

    notify(data, {
      title: `M3U Setup: ${playlist.name}`,
      message: <M3uSetupSuccess data={data} />,
      color: 'orange.5',
      loading: false,
      withCloseButton: true,
      autoClose: 5000,
    });
  };

  const handleError = (playlist, data) => {
    notify(data, {
      title: `${data.action === 'vod_refresh' ? 'VOD' : 'Live TV'} refresh: ${playlist.name}`,
      message: data.error || data.message || 'Refresh failed. Please retry.',
      color: 'red',
      loading: false,
      withCloseButton: true,
      autoClose: false,
    });
  };

  const getActionMessage = (action) => {
    const messages = {
      downloading: 'Downloading',
      parsing: 'Stream parsing',
      processing_groups: 'Category loading',
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
    const complete =
      data.progress === 100 &&
      ['parsing', 'processing_groups', 'vod_refresh'].includes(data.action);
    if (!complete) {
      notify(data, {
        title: `${data.action === 'vod_refresh' ? 'VOD' : 'Live TV'} refresh: ${playlist.name}`,
        message: <RefreshProgress data={data} />,
        loading: true,
        autoClose: false,
        withCloseButton: false,
      });
      return;
    }
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
    // Surface stream and auto-sync counts attached to the parsing-complete
    // event so the outcome appears in the notification body.
    if (data.progress == 100 && data.action === 'parsing') {
      const streamSummary = buildStreamSummary(data);
      const autoSyncSummary = buildAutoSyncSummary(data);
      const failed = data.channels_failed || 0;
      const failedDetails = Array.isArray(data.failed_stream_details)
        ? data.failed_stream_details
        : [];
      if (streamSummary || autoSyncSummary) {
        body = (
          <Stack gap={4}>
            <Text size="sm">{message}</Text>
            {streamSummary && (
              <Text size="xs" c="dimmed">
                {streamSummary}
              </Text>
            )}
            {autoSyncSummary && (
              <Text size="xs" c="dimmed">
                {autoSyncSummary}
              </Text>
            )}
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

    notify(data, {
      title: `${data.action === 'vod_refresh' ? 'VOD' : 'Live TV'} refresh: ${playlist.name}`,
      message: body,
      loading: false,
      autoClose,
      withCloseButton: true,
      color: data.channels_failed > 0 ? 'yellow' : 'green',
      icon: <CircleCheck />,
    });
  };

  useEffect(() => {
    const validIds = new Set(playlists.map((playlist) => String(playlist.id)));
    for (const account of Object.keys(notificationStatus.current)) {
      if (!validIds.has(account)) {
        delete notificationStatus.current[account];
        for (const kind of ['live', 'vod']) {
          const id = `m3u-refresh-${account}-${kind}`;
          if (visibleNotifications.current.delete(id)) hideNotification(id);
        }
      }
    }

    // Process all refresh progress updates
    Object.values(refreshProgress).map((data) => handleM3UUpdate(data));
  });

  useEffect(() => {
    const visible = visibleNotifications.current;
    const seen = notificationStatus.current;
    return () => {
      visible.forEach((id) => hideNotification(id));
      visible.clear();
      for (const account of Object.keys(seen)) delete seen[account];
    };
  }, []);

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
