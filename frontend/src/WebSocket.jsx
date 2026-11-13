import React, {
  useState,
  useEffect,
  useRef,
  useMemo,
  useCallback,
} from 'react';
import { notifications } from '@mantine/notifications';
import useChannelsStore from './store/channels';
import useLogosStore from './store/logos';
import usePlaylistsStore from './store/playlists';
import useEPGsStore from './store/epgs';
import { Button, Alert } from '@mantine/core';
import API from './api';
import useSettingsStore from './store/settings';
import useAuthStore from './store/auth';
import useUsersStore from './store/users';
import { usePluginStore } from './store/plugins.jsx';
import { computeBackoffDelay } from './utils/backoff';
import { WebsocketContext } from './WebSocketContext';

// UI WebSocket reconnect: grow slowly, cap at 30s, half-jitter so many tabs
// recovering together do not hammer DNS in lockstep.
const WS_RECONNECT_BACKOFF = {
  initialMs: 1000,
  maxMs: 30000,
  factor: 1.5,
  jitter: 0.5,
};

// Debounce: coalesces rapid recording WS events into a single fetchRecordings()
// call (400 ms window) to prevent redundant re-renders in the TV Guide.
let _recordingFetchTimer = null;
function scheduleRecordingFetch() {
  if (_recordingFetchTimer) clearTimeout(_recordingFetchTimer);
  _recordingFetchTimer = setTimeout(async () => {
    _recordingFetchTimer = null;
    try {
      await useChannelsStore.getState().fetchRecordings();
    } catch (e) {
      console.warn('Failed to refresh recordings:', e);
    }
  }, 400);
}

export const WebsocketProvider = ({ children }) => {
  const [isReady, setIsReady] = useState(false);
  const [val, setVal] = useState(null);
  const ws = useRef(null);
  const reconnectTimerRef = useRef(null);
  // Attempt / ready / close intent live in refs so reconnect scheduling is not
  // tied to React effect identity. Putting these in useCallback/effect deps
  // previously cancelled backoff timers and reconnected in a tight loop.
  const reconnectAttemptsRef = useRef(0);
  const isReadyRef = useRef(false);
  const intentionalCloseRef = useRef(false);
  const connectRef = useRef(null);
  const accessTokenRef = useRef(null);
  const envModeRef = useRef('aio');
  const [reconnectAttempts, setReconnectAttempts] = useState(0);
  const [connectionError, setConnectionError] = useState(null);
  const env_mode = useSettingsStore((s) => s.environment.env_mode);
  const accessToken = useAuthStore((s) => s.accessToken);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  accessTokenRef.current = accessToken;
  envModeRef.current = env_mode;

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  const getWebSocketUrl = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.hostname;
    const appPort = window.location.port;
    const token = accessTokenRef.current;
    const mode = envModeRef.current;

    // In development mode, connect directly to the WebSocket server on port 8001
    if (mode === 'dev') {
      return `${protocol}//${host}:8001/ws/?token=${token}`;
    }
    // In production mode, use the same port as the main application so nginx
    // can forward the WebSocket upgrade.
    return appPort
      ? `${protocol}//${host}:${appPort}/ws/?token=${token}`
      : `${protocol}//${host}/ws/?token=${token}`;
  }, []);

  const scheduleReconnect = useCallback(() => {
    if (intentionalCloseRef.current) return;
    // Only one pending retry; avoids stacking timers if close races fire twice.
    if (reconnectTimerRef.current) return;

    const attempt = reconnectAttemptsRef.current;
    const delay = computeBackoffDelay(attempt, WS_RECONNECT_BACKOFF);
    reconnectAttemptsRef.current = attempt + 1;
    // Banner visibility only needs a non-zero attempts state once. Later
    // retries update the message text, not this counter.
    if (attempt === 0) {
      setReconnectAttempts(reconnectAttemptsRef.current);
    }
    const seconds = Math.max(1, Math.ceil(delay / 1000));
    setConnectionError(
      `Connection lost. Reconnecting in ${seconds} ${seconds === 1 ? 'second' : 'seconds'}...`
    );
    console.log(
      `Scheduling WebSocket reconnect in ${delay}ms (attempt ${reconnectAttemptsRef.current})...`
    );

    reconnectTimerRef.current = setTimeout(() => {
      reconnectTimerRef.current = null;
      // Logout or unmount may have landed after this timer was queued.
      if (intentionalCloseRef.current) return;
      connectRef.current?.();
    }, delay);
  }, []);

  const connectWebSocket = useCallback(() => {
    // Auth / unmount own intentionalCloseRef. Never clear it here: a logout
    // can land between a timer's guard and this call, and clearing would
    // open a socket after the user signed out.
    if (intentionalCloseRef.current) return;

    // Clear any existing timers to avoid multiple reconnection attempts
    clearReconnectTimer();

    // Drop ready before swapping sockets. Otherwise a token or env change
    // replaces the socket while isReady stays true, and context keeps send()
    // bound to the closed socket.
    if (isReadyRef.current) {
      isReadyRef.current = false;
      setIsReady(false);
    }

    // Clear old websocket if exists
    if (ws.current) {
      // Remove event handlers to prevent duplicate events
      ws.current.onclose = null;
      ws.current.onerror = null;
      ws.current.onopen = null;
      ws.current.onmessage = null;

      try {
        ws.current.close();
      } catch (e) {
        console.warn('Error closing existing WebSocket:', e);
      }
      ws.current = null;
    }

    try {
      const attemptLabel = reconnectAttemptsRef.current + 1;
      console.log(`Attempting WebSocket connection (attempt ${attemptLabel})...`);

      const wsUrl = getWebSocketUrl();
      console.log(`Connecting to WebSocket at: ${wsUrl.split('?')[0]}`);

      const socket = new WebSocket(wsUrl);
      ws.current = socket;

      socket.onopen = () => {
        if (ws.current !== socket) return;
        console.log('WebSocket connected successfully');
        isReadyRef.current = true;
        setIsReady(true);
        setConnectionError(null);
        reconnectAttemptsRef.current = 0;
        setReconnectAttempts(0);
      };

      socket.onerror = (error) => {
        console.error('WebSocket connection error:', error);
        // Close follows error and owns the banner. Setting it here only
        // forces an extra render with a message that close immediately replaces.
        if (reconnectAttemptsRef.current === 0 && !isReadyRef.current) {
          console.log('Initial connection attempt failed, will retry...');
        }
      };

      socket.onclose = (event) => {
        // Ignore a close from a socket this provider already replaced.
        if (ws.current !== socket) return;

        console.warn('WebSocket connection closed', event);
        ws.current = null;
        isReadyRef.current = false;
        setIsReady(false);
        scheduleReconnect();
      };

      // Message handler
      socket.onmessage = async (event) => {
        try {
          const parsedEvent = JSON.parse(event.data);

          // Handle connection_established event
          if (parsedEvent.type === 'connection_established') {
            console.log(
              'WebSocket connection established:',
              parsedEvent.data?.message
            );
            // Don't need to do anything else for this event type
            return;
          }

          // Handle standard message format for other event types
          switch (parsedEvent.data?.type) {
            case 'comskip_status': {
              const rid = parsedEvent.data.recording_id;
              const id = `comskip-${rid}`;
              const status = parsedEvent.data.status;
              const title = parsedEvent.data.title || 'Recording';
              if (status === 'started') {
                notifications.show({
                  id,
                  title: 'Removing commercials',
                  message: `Processing ${title}...`,
                  color: 'blue.5',
                  autoClose: false,
                  withCloseButton: false,
                  loading: true,
                });
              } else if (status === 'completed') {
                notifications.update({
                  id,
                  title: 'Commercials removed',
                  message: `${title}: kept ${parsedEvent.data.segments_kept} segments`,
                  color: 'green.5',
                  loading: false,
                  autoClose: 4000,
                });
                scheduleRecordingFetch();
              } else if (status === 'skipped') {
                const reasonMap = {
                  no_commercials_detected:
                    'No commercials were detected in this recording',
                  no_commercials:
                    'No commercials were detected in this recording',
                };
                notifications.update({
                  id,
                  title: 'No commercials to remove',
                  message:
                    reasonMap[parsedEvent.data.reason] ||
                    parsedEvent.data.reason ||
                    '',
                  color: 'teal',
                  loading: false,
                  autoClose: 3000,
                });
                scheduleRecordingFetch();
              } else if (status === 'error') {
                notifications.update({
                  id,
                  title: 'Comskip failed',
                  message: parsedEvent.data.reason || 'Unknown error',
                  color: 'red',
                  loading: false,
                  autoClose: 6000,
                });
                scheduleRecordingFetch();
              }
              break;
            }
            case 'epg_file':
              useEPGsStore.getState().fetchEPGs();
              notifications.show({
                title: 'EPG File Detected',
                message: `Processing ${parsedEvent.data.filename}`,
              });
              break;

            case 'm3u_file':
              usePlaylistsStore.getState().fetchPlaylists();
              notifications.show({
                title: 'M3U File Detected',
                message: `Processing ${parsedEvent.data.filename}`,
              });
              break;

            case 'm3u_refresh':
              // Update the store with progress information
              usePlaylistsStore.getState().setRefreshProgress(parsedEvent.data);

              // Update the playlist status whenever we receive a status update
              // Not just when progress is 100% or status is pending_setup
              if (parsedEvent.data.status && parsedEvent.data.account) {
                // Get fresh playlists from store to avoid stale state from React render cycle
                const currentPlaylists = usePlaylistsStore.getState().playlists;
                const isArray = Array.isArray(currentPlaylists);
                const playlist = isArray
                  ? currentPlaylists.find(
                      (p) => p.id === parsedEvent.data.account
                    )
                  : currentPlaylists[parsedEvent.data.account];

                if (playlist) {
                  // When we receive a "success" status with 100% progress, this is a completed refresh
                  // So we should also update the updated_at timestamp
                  const updateData = {
                    ...playlist,
                    status: parsedEvent.data.status,
                    last_message:
                      parsedEvent.data.message || playlist.last_message,
                  };

                  // Update the timestamp when we complete a successful refresh
                  if (
                    parsedEvent.data.status === 'success' &&
                    parsedEvent.data.progress === 100
                  ) {
                    updateData.updated_at = new Date().toISOString();
                    // Log successful completion for debugging
                    console.log(
                      'M3U refresh completed successfully:',
                      updateData
                    );
                    usePlaylistsStore.getState().fetchPlaylists();
                    useChannelsStore.getState().fetchChannelProfiles();
                  }

                  usePlaylistsStore.getState().updatePlaylist(updateData);
                } else {
                  // Playlist not in store yet - this happens when backend sends websocket
                  // updates immediately after creating the playlist, before the API response
                  // returns. The frontend will receive a 'playlist_created' event shortly
                  // which will trigger a fetchPlaylists() to sync the store.
                  console.log(
                    `Received update for playlist ID ${parsedEvent.data.account} not yet in store. ` +
                      `Waiting for playlist_created event to sync...`
                  );
                }
              }
              break;

            case 'channel_stats':
              useChannelsStore
                .getState()
                .setChannelStats(JSON.parse(parsedEvent.data.stats));
              break;

            case 'vod_stats':
              useChannelsStore
                .getState()
                .setVodStats(JSON.parse(parsedEvent.data.stats));
              break;

            case 'timeshift_stats':
              useChannelsStore
                .getState()
                .setTimeshiftStats(JSON.parse(parsedEvent.data.stats));
              break;

            case 'vod_started':
            case 'vod_stopped': {
              const { content_name, client_ip, user_id } = parsedEvent.data;
              const isStart = parsedEvent.data.type === 'vod_started';
              let identity = client_ip || 'unknown';
              if (user_id && user_id !== '0') {
                const allUsers = useUsersStore.getState().users;
                const matched = allUsers.find(
                  (u) => String(u.id) === String(user_id)
                );
                if (matched?.username)
                  identity = `${matched.username} (${client_ip})`;
              }
              notifications.show({
                title: isStart ? 'VOD started' : 'VOD ended',
                message: (
                  <>
                    <div>{content_name}</div>
                    <div style={{ marginTop: 2 }}>{identity}</div>
                  </>
                ),
                color: 'blue.5',
              });
              break;
            }

            case 'epg_channels':
              notifications.show({
                message: 'EPG channels updated!',
                color: 'green.5',
              });

              // If source_id is provided, update that specific EPG's status
              if (parsedEvent.data.source_id) {
                const { epgs: epgsState, updateEPG: patchEPG } =
                  useEPGsStore.getState();
                const epg = epgsState[parsedEvent.data.source_id];
                if (epg) {
                  patchEPG({
                    ...epg,
                    status: 'success',
                  });
                }
              }

              useEPGsStore.getState().fetchEPGData();
              break;

            case 'single_channel_epg_match': {
              const matchResult = parsedEvent.data;
              if (matchResult.channel) {
                useChannelsStore.getState().updateChannel(matchResult.channel);
              }
              window.dispatchEvent(
                new CustomEvent('single-channel-epg-match', {
                  detail: matchResult,
                })
              );
              break;
            }

            case 'epg_match':
              notifications.show({
                message: parsedEvent.data.message || 'EPG match is complete!',
                color: 'green.5',
              });

              // Celery already applied assignments server-side; refresh local state.
              useEPGsStore.getState().fetchEPGData();
              API.requeryChannels();
              break;

            case 'epg_matching_progress': {
              const progress = parsedEvent.data;
              const id = 'epg-matching-progress';

              if (progress.stage === 'starting') {
                notifications.show({
                  id,
                  title: 'EPG Matching in Progress',
                  message: `Starting to match ${progress.total} channels...`,
                  color: 'blue.5',
                  autoClose: false,
                  withCloseButton: false,
                  loading: true,
                });
              } else if (progress.stage === 'matching') {
                let message = `Matched ${progress.matched} of ${progress.total} channels`;
                if (progress.remaining > 0) {
                  message += ` (${progress.remaining} remaining)`;
                }
                if (progress.current_channel) {
                  message += `\nCurrently processing: ${progress.current_channel}`;
                }

                notifications.update({
                  id,
                  title: 'EPG Matching in Progress',
                  message,
                  color: 'blue.5',
                  autoClose: false,
                  withCloseButton: false,
                  loading: true,
                });
              } else if (progress.stage === 'completed') {
                notifications.update({
                  id,
                  title: 'EPG Matching Complete',
                  message: `Successfully matched ${progress.matched} of ${progress.total} channels (${progress.progress_percent}%)`,
                  color: progress.matched > 0 ? 'green.5' : 'orange',
                  loading: false,
                  autoClose: 6000,
                });
              }
              break;
            }

            case 'epg_logo_setting_progress': {
              const progress = parsedEvent.data;
              const id = 'epg-logo-setting-progress';

              if (progress.status === 'running' && progress.progress === 0) {
                // Initial message
                notifications.show({
                  id,
                  title: 'Setting Logos from EPG',
                  message: `Processing ${progress.total} channels...`,
                  color: 'blue.5',
                  autoClose: false,
                  withCloseButton: false,
                  loading: true,
                });
              } else if (progress.status === 'running') {
                // Progress update
                let message = `Processed ${progress.progress} of ${progress.total} channels`;
                if (progress.updated_count !== undefined) {
                  message += ` (${progress.updated_count} updated)`;
                }
                if (progress.created_logos_count !== undefined) {
                  message += `, created ${progress.created_logos_count} logos`;
                }

                notifications.update({
                  id,
                  title: 'Setting Logos from EPG',
                  message,
                  color: 'blue.5',
                  autoClose: false,
                  withCloseButton: false,
                  loading: true,
                });
              } else if (progress.status === 'completed') {
                notifications.update({
                  id,
                  title: 'Logo Setting Complete',
                  message: `Successfully updated ${progress.updated_count || 0} channel logos${progress.created_logos_count ? `, created ${progress.created_logos_count} new logos` : ''}`,
                  color: progress.updated_count > 0 ? 'green.5' : 'orange',
                  loading: false,
                  autoClose: 6000,
                });
                // Refresh channels data and logos
                try {
                  await API.requeryChannels();
                  await useChannelsStore.getState().fetchChannelIds();

                  // Get updated channel data and extract logo IDs to load
                  const channels = useChannelsStore.getState().channels;
                  const logoIds = Object.values(channels)
                    .filter((channel) => channel.logo_id)
                    .map((channel) => channel.logo_id);

                  // Fetch the specific logos that were just assigned
                  if (logoIds.length > 0) {
                    await useLogosStore.getState().fetchLogosByIds(logoIds);
                  }
                } catch (e) {
                  console.warn(
                    'Failed to refresh channels after logo setting:',
                    e
                  );
                }
              }
              break;
            }

            case 'epg_name_setting_progress': {
              const progress = parsedEvent.data;
              const id = 'epg-name-setting-progress';

              if (progress.status === 'running' && progress.progress === 0) {
                // Initial message
                notifications.show({
                  id,
                  title: 'Setting Names from EPG',
                  message: `Processing ${progress.total} channels...`,
                  color: 'blue.5',
                  autoClose: false,
                  withCloseButton: false,
                  loading: true,
                });
              } else if (progress.status === 'running') {
                // Progress update
                let message = `Processed ${progress.progress} of ${progress.total} channels`;
                if (progress.updated_count !== undefined) {
                  message += ` (${progress.updated_count} updated)`;
                }

                notifications.update({
                  id,
                  title: 'Setting Names from EPG',
                  message,
                  color: 'blue.5',
                  autoClose: false,
                  withCloseButton: false,
                  loading: true,
                });
              } else if (progress.status === 'completed') {
                notifications.update({
                  id,
                  title: 'Name Setting Complete',
                  message: `Successfully updated ${progress.updated_count || 0} channel names from EPG data`,
                  color: progress.updated_count > 0 ? 'green.5' : 'orange',
                  loading: false,
                  autoClose: 6000,
                });
                // Refresh channels data
                try {
                  await API.requeryChannels();
                  await useChannelsStore.getState().fetchChannelIds();
                } catch (e) {
                  console.warn(
                    'Failed to refresh channels after name setting:',
                    e
                  );
                }
              }
              break;
            }

            case 'm3u_profile_test':
              usePlaylistsStore
                .getState()
                .setProfilePreview(
                  parsedEvent.data.search_preview,
                  parsedEvent.data.result
                );
              break;

            case 'recording_updated':
              scheduleRecordingFetch();
              break;

            case 'recordings_refreshed':
              scheduleRecordingFetch();
              break;

            case 'recording_started':
              notifications.show({
                title: 'Recording started!',
                message: `Started recording channel ${parsedEvent.data.channel}`,
              });
              scheduleRecordingFetch();
              break;

            case 'recording_ended':
              notifications.show({
                title: 'Recording finished!',
                message: `Stopped recording channel ${parsedEvent.data.channel}`,
              });
              scheduleRecordingFetch();
              break;

            case 'recording_stopped':
              notifications.show({
                title: 'Recording stopped',
                message: `Recording stopped early for ${parsedEvent.data.channel || 'channel'}. Partial content has been saved.`,
                color: 'yellow',
              });
              scheduleRecordingFetch();
              break;

            case 'recording_extended':
              scheduleRecordingFetch();
              break;

            case 'recording_cancelled':
              notifications.show({
                title: parsedEvent.data.was_in_progress
                  ? 'Recording cancelled'
                  : 'Recording deleted',
                message: parsedEvent.data.was_in_progress
                  ? 'Recording cancelled and content removed.'
                  : 'Recording deleted.',
                color: 'red',
              });
              // Surgical removal by ID avoids a full fetchRecordings() re-render.
              // Fall back to a full refresh if the ID is missing (e.g. older server).
              if (parsedEvent.data.recording_id != null) {
                useChannelsStore
                  .getState()
                  .removeRecording(parsedEvent.data.recording_id);
              } else {
                scheduleRecordingFetch();
              }
              break;

            case 'epg_fetch_error':
              notifications.show({
                title: 'EPG Source Error',
                message: parsedEvent.data.message,
                color: 'orange.5',
                autoClose: 8000,
              });

              // Update EPG status in store
              if (parsedEvent.data.source_id) {
                const { epgs: epgsState, updateEPG: patchEPG } =
                  useEPGsStore.getState();
                const epg = epgsState[parsedEvent.data.source_id];
                if (epg) {
                  patchEPG({
                    ...epg,
                    status: 'error',
                    last_message: parsedEvent.data.message,
                  });
                }
              }
              break;

            case 'epg_refresh': {
              const sourceId =
                parsedEvent.data.source || parsedEvent.data.account;
              if (!sourceId) break;

              // Always read EPG state fresh; a newly created source is otherwise
              // missed and parsing_channels completion never refreshes programs.
              let {
                epgs: epgsState,
                updateEPG,
                updateEPGProgress,
                fetchEPGs,
                fetchEPGData,
              } = useEPGsStore.getState();

              if (!epgsState[sourceId]) {
                try {
                  await fetchEPGs();
                } catch (e) {
                  console.warn(
                    'Failed to refresh EPG sources for progress update:',
                    e
                  );
                }
                epgsState = useEPGsStore.getState().epgs;
              }

              updateEPGProgress(parsedEvent.data);

              const epg = epgsState[sourceId];
              if (!epg) break;

              const hasError =
                parsedEvent.data.status === 'error' ||
                !!parsedEvent.data.error ||
                (parsedEvent.data.message &&
                  parsedEvent.data.message.toLowerCase().includes('error'));

              if (hasError) {
                const errorMessage =
                  parsedEvent.data.error ||
                  parsedEvent.data.message ||
                  'Unknown error occurred';

                updateEPG({
                  ...epg,
                  status: 'error',
                  last_message: errorMessage,
                });

                notifications.show({
                  title: 'EPG Refresh Error',
                  message: errorMessage,
                  color: 'red.5',
                });
              } else if (parsedEvent.data.progress === 100) {
                updateEPG({
                  ...epg,
                  status: parsedEvent.data.status || 'success',
                  last_message: parsedEvent.data.message || epg.last_message,
                  ...(parsedEvent.data.updated_at && {
                    updated_at: parsedEvent.data.updated_at,
                  }),
                });

                if (parsedEvent.data.action === 'parsing_channels') {
                  notifications.show({
                    message: 'EPG channels updated!',
                    color: 'green.5',
                  });

                  await fetchEPGData();
                } else if (parsedEvent.data.action === 'parsing_programs') {
                  notifications.show({
                    title: 'EPG Processing Complete',
                    message: 'EPG data has been updated successfully',
                    color: 'green.5',
                  });

                  await fetchEPGData();
                }
              }
              break;
            }

            case 'epg_sources_changed':
              // A plugin or backend process signaled that the EPG sources changed
              try {
                await useEPGsStore.getState().fetchEPGs();
              } catch (e) {
                console.warn(
                  'Failed to refresh EPG sources after change notification:',
                  e
                );
              }
              break;

            case 'epg_data_created':
              // A new EPG data entry was created (e.g., for a dummy EPG)
              // Fetch EPG data so the channel form can immediately assign it
              try {
                await useEPGsStore.getState().fetchEPGData();
              } catch (e) {
                console.warn('Failed to refresh EPG data after creation:', e);
              }
              break;

            case 'stream_rehash':
              // Handle stream rehash progress updates
              if (parsedEvent.data.action === 'starting') {
                notifications.show({
                  id: 'stream-rehash-progress', // Persistent ID
                  title: 'Stream Rehash Started',
                  message: parsedEvent.data.message,
                  color: 'blue.5',
                  autoClose: false, // Don't auto-close
                  withCloseButton: false, // No close button during processing
                  loading: true, // Show loading indicator
                });
              } else if (parsedEvent.data.action === 'processing') {
                // Update the existing notification
                notifications.update({
                  id: 'stream-rehash-progress',
                  title: 'Stream Rehash in Progress',
                  message: `${parsedEvent.data.progress}% complete - ${parsedEvent.data.processed} streams processed, ${parsedEvent.data.duplicates_merged} duplicates merged`,
                  color: 'blue.5',
                  autoClose: false,
                  withCloseButton: false,
                  loading: true,
                });
              } else if (parsedEvent.data.action === 'completed') {
                // Update to completion state
                notifications.update({
                  id: 'stream-rehash-progress',
                  title: 'Stream Rehash Complete',
                  message: `Processed ${parsedEvent.data.total_processed} streams, merged ${parsedEvent.data.duplicates_merged} duplicates. Final count: ${parsedEvent.data.final_count}`,
                  color: 'green.5',
                  autoClose: 8000, // Auto-close after completion
                  withCloseButton: true, // Allow manual close
                  loading: false, // Remove loading indicator
                });
                // Requery streams and channels after rehash completes
                try {
                  await API.requeryChannels();
                  await API.requeryStreams();
                  await useChannelsStore.getState().fetchChannelIds();
                } catch (error) {
                  console.error(
                    'Error refreshing channels/streams after rehash:',
                    error
                  );
                }
              } else if (parsedEvent.data.action === 'blocked') {
                // Handle blocked rehash attempt
                notifications.show({
                  title: 'Stream Rehash Blocked',
                  message: parsedEvent.data.message,
                  color: 'orange.5',
                  autoClose: 8000,
                });
              }
              break;

            case 'logo_processing_summary':
              notifications.show({
                title: 'Logo Processing Summary',
                message: `${parsedEvent.data.message}`,
                color: 'blue',
                autoClose: 5000,
              });
              useLogosStore.getState().fetchAllLogos();
              break;

            case 'account_info_refresh_success':
              notifications.show({
                title: 'Account Info Refreshed',
                message: `Successfully updated account information for ${parsedEvent.data.profile_name}`,
                color: 'green',
                autoClose: 4000,
              });
              // Trigger refresh of playlists to update the UI
              usePlaylistsStore.getState().fetchPlaylists();
              break;

            case 'account_info_refresh_error':
              notifications.show({
                title: 'Account Info Refresh Failed',
                message:
                  parsedEvent.data.error ||
                  'Failed to refresh account information',
                color: 'red',
                autoClose: 8000,
              });
              break;

            case 'channels_created':
              // General notification for channel creation
              notifications.show({
                title: 'Channels Created',
                message: `Successfully created ${parsedEvent.data.count || 'multiple'} channel(s)`,
                color: 'green',
                autoClose: 4000,
              });

              // Refresh the channels table to show new channels
              try {
                await API.requeryChannels();
                await API.requeryStreams();
                useChannelsStore.getState().fetchChannelIds();
                await useChannelsStore.getState().fetchChannelProfiles();
                console.log('Channels refreshed after bulk creation');
              } catch (error) {
                console.error(
                  'Error refreshing channels after creation:',
                  error
                );
              }

              break;

            case 'playlist_created':
              // Backend signals that a new playlist has been created and we should refresh
              console.log(
                'Playlist created event received, refreshing playlists...'
              );
              usePlaylistsStore.getState().fetchPlaylists();
              break;

            case 'bulk_channel_creation_progress': {
              // Handle progress updates with persistent notifications like stream rehash
              const data = parsedEvent.data;

              if (data.status === 'starting') {
                notifications.show({
                  id: 'bulk-channel-creation-progress', // Persistent ID
                  title: 'Bulk Channel Creation Started',
                  message: data.message || 'Starting bulk channel creation...',
                  color: 'blue.5',
                  autoClose: false, // Don't auto-close
                  withCloseButton: false, // No close button during processing
                  loading: true, // Show loading indicator
                });
              } else if (
                data.status === 'processing' ||
                data.status === 'creating_logos' ||
                data.status === 'creating_channels'
              ) {
                // Calculate progress percentage
                const progressPercent =
                  data.total > 0
                    ? Math.round((data.progress / data.total) * 100)
                    : 0;

                // Update the existing notification with progress
                notifications.update({
                  id: 'bulk-channel-creation-progress',
                  title: 'Bulk Channel Creation in Progress',
                  message: `${progressPercent}% complete - ${data.message}`,
                  color: 'blue.5',
                  autoClose: false,
                  withCloseButton: false,
                  loading: true,
                });
              } else if (data.status === 'completed') {
                // Hide the progress notification since channels_created will show success
                notifications.hide('bulk-channel-creation-progress');
              } else if (data.status === 'failed') {
                // Update to error state
                notifications.update({
                  id: 'bulk-channel-creation-progress',
                  title: 'Bulk Channel Creation Failed',
                  message:
                    data.error ||
                    'An error occurred during bulk channel creation',
                  color: 'red.5',
                  autoClose: 12000, // Auto-close after longer delay for errors
                  withCloseButton: true, // Allow manual close
                  loading: false, // Remove loading indicator
                });
              }

              // Pass through to individual components for any additional handling
              setVal(parsedEvent);
              break;
            }

            case 'system_notification': {
              // Handle real-time system notifications (version updates, setting recommendations, etc.)
              const notificationData = parsedEvent.data.notification;
              if (notificationData) {
                // Import and update the notifications store
                const { default: useNotificationsStore } =
                  await import('./store/notifications');
                useNotificationsStore
                  .getState()
                  .addNotification(notificationData);

                // Show a toast notification for high priority items
                if (
                  notificationData.priority === 'high' ||
                  notificationData.priority === 'critical'
                ) {
                  const color =
                    notificationData.priority === 'critical'
                      ? 'red'
                      : notificationData.notification_type === 'version_update'
                      ? 'green'
                      : notificationData.notification_type === 'warning'
                        ? 'orange'
                        : 'blue';

                  notifications.show({
                    title: notificationData.title,
                    message: notificationData.message,
                    color,
                    autoClose: 10000,
                  });
                }
              }
              break;
            }

            case 'notification_dismissed': {
              // Handle notification dismissed from another session
              const { notification_key } = parsedEvent.data;
              if (notification_key) {
                const { default: useNotificationsStore } =
                  await import('./store/notifications');
                useNotificationsStore
                  .getState()
                  .dismissNotification(notification_key);
              }
              break;
            }

            case 'notifications_cleared': {
              // Handle bulk notification clearing (e.g., when version is updated)
              API.getNotifications();
              break;
            }

            case 'ip_lookup_complete': {
              const { type: _t, ...ipData } = parsedEvent.data;
              useSettingsStore.getState().setEnvironmentFields(ipData);
              break;
            }

            case 'plugin_task_progress': {
              const { task_id, percent, message, updatedAt } = parsedEvent.data;
              usePluginStore.getState().updatePluginTaskProgress(task_id, { percent, message, updatedAt });
              break;
            }

            case 'plugin_task_complete': {
              const { task_id, plugin, status: taskStatus, result, error, updatedAt } = parsedEvent.data;
              usePluginStore.getState().completePluginTask(task_id, { status: taskStatus, result, error, updatedAt });
              notifications.update({
                id: `plugin-task-${task_id}`,
                title: plugin,
                message: taskStatus === 'partial' ? (result?.message || 'Completed with warnings') : taskStatus === 'ok' ? (result?.message || 'Completed') : (error || 'Failed'),
                color: taskStatus === 'partial' ? 'yellow' : taskStatus === 'ok' ? 'green' : 'red',
                loading: false,
                autoClose: 5000,
              });
              break;
            }

            default:
              console.error(
                `Unknown websocket event type: ${parsedEvent.data?.type}`
              );
              break;
          }
        } catch (error) {
          console.error(
            'Error processing WebSocket message:',
            error,
            event.data
          );
        }
      };
    } catch (error) {
      console.error('Error creating WebSocket connection:', error);
      scheduleReconnect();
    }
  }, [clearReconnectTimer, getWebSocketUrl, scheduleReconnect]);

  // Always point at the latest connect implementation. Reconnect timers and the
  // auth effect call through this ref so they do not need connectWebSocket in
  // their dependency lists (which previously caused reconnect storms).
  connectRef.current = connectWebSocket;

  // Connect when authenticated. Reconnect once if the token or dev/prod URL
  // mode changes. Do not depend on connectWebSocket: isReady / attempt state
  // must not re-run this effect, or backoff timers get cleared and replaced
  // with an instant retry.
  useEffect(() => {
    if (isAuthenticated && accessToken) {
      intentionalCloseRef.current = false;
      reconnectAttemptsRef.current = 0;
      setReconnectAttempts(0);
      connectRef.current?.();
    } else {
      intentionalCloseRef.current = true;
      clearReconnectTimer();
      if (ws.current) {
        console.log('Closing WebSocket connection due to logout');
        ws.current.onclose = null;
        ws.current.close();
        ws.current = null;
      }
      isReadyRef.current = false;
      setIsReady(false);
      setConnectionError(null);
    }

    return () => {
      intentionalCloseRef.current = true;
      clearReconnectTimer();

      if (ws.current) {
        console.log('Closing WebSocket connection');
        ws.current.onclose = null;
        ws.current.close();
        ws.current = null;
      }
    };
  }, [clearReconnectTimer, isAuthenticated, accessToken, env_mode]);

  const ret = useMemo(() => {
    return [isReady, ws.current?.send.bind(ws.current), val];
  }, [isReady, val]);

  const reconnectNow = useCallback(() => {
    if (intentionalCloseRef.current) return;
    // Reset backoff for the next failure, but leave reconnectAttempts state
    // alone so the banner stays visible while this manual attempt runs.
    reconnectAttemptsRef.current = 0;
    connectRef.current?.();
  }, []);

  return (
    <WebsocketContext.Provider value={ret}>
      {connectionError && !isReady && reconnectAttempts > 0 && (
        <Alert
          color="orange"
          title="WebSocket Reconnecting"
          style={{
            position: 'fixed',
            bottom: 10,
            right: 10,
            zIndex: 1000,
            maxWidth: 350,
          }}
        >
          {connectionError}
          <Button size="xs" mt={10} onClick={reconnectNow}>
            Reconnect Now
          </Button>
        </Alert>
      )}
      {children}
    </WebsocketContext.Provider>
  );
};
