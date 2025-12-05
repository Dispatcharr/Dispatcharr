import React, {
  useState,
  useEffect,
  useRef,
  createContext,
  useContext,
  useMemo,
  useCallback,
} from 'react';
import { notifications } from '@mantine/notifications';
import useChannelsStore from './store/channels';
import useLogosStore from './store/logos';
import usePlaylistsStore from './store/playlists';
import useEPGsStore from './store/epgs';
import { Box, Button, Stack, Alert, Group } from '@mantine/core';
import API from './api';
import useSettingsStore from './store/settings';
import useAuthStore from './store/auth';

export const WebsocketContext = createContext([false, () => {}, null]);

export const WebsocketProvider = ({ children }) => {
  const [isReady, setIsReady] = useState(false);
  const [val, setVal] = useState(null);
  const ws = useRef(null);
  const reconnectTimerRef = useRef(null);
  const [reconnectAttempts, setReconnectAttempts] = useState(0);
  const [connectionError, setConnectionError] = useState(null);
  const maxReconnectAttempts = 5;
  const initialBackoffDelay = 1000; // 1 second initial delay
  const env_mode = useSettingsStore((s) => s.environment.env_mode);
  const accessToken = useAuthStore((s) => s.accessToken);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  const epgs = useEPGsStore((s) => s.epgs);
  const updateEPG = useEPGsStore((s) => s.updateEPG);
  const updateEPGProgress = useEPGsStore((s) => s.updateEPGProgress);

  const updatePlaylist = usePlaylistsStore((s) => s.updatePlaylist);

  // Calculate reconnection delay with exponential backoff
  const getReconnectDelay = useCallback(() => {
    return Math.min(
      initialBackoffDelay * Math.pow(1.5, reconnectAttempts),
      30000
    ); // max 30 seconds
  }, [reconnectAttempts]);

  // Clear any existing reconnect timers
  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  // Function to get WebSocket URL that works with both HTTP and HTTPS
  const getWebSocketUrl = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.hostname;
    const appPort = window.location.port;

    // In development mode, connect directly to the WebSocket server on port 8001
    if (env_mode === 'dev') {
      return `${protocol}//${host}:8001/ws/?token=${accessToken}`;
    } else {
      // In production mode, use the same port as the main application
      // This allows nginx to handle the WebSocket forwarding
      return appPort
        ? `${protocol}//${host}:${appPort}/ws/?token=${accessToken}`
        : `${protocol}//${host}/ws/?token=${accessToken}`;
    }
  }, [env_mode, accessToken]);

  // Function to handle websocket connection
  const connectWebSocket = useCallback(() => {
    // Clear any existing timers to avoid multiple reconnection attempts
    clearReconnectTimer();

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
    }

    try {
      console.log(
        `Attempting WebSocket connection (attempt ${reconnectAttempts + 1}/${maxReconnectAttempts})...`
      );

      // Use the function to get the correct WebSocket URL
      const wsUrl = getWebSocketUrl();
      console.log(`Connecting to WebSocket at: ${wsUrl}`);

      // Create new WebSocket connection
      const socket = new WebSocket(wsUrl);

      socket.onopen = () => {
        console.log('WebSocket connected successfully');
        setIsReady(true);
        setConnectionError(null);
        setReconnectAttempts(0);
      };

      socket.onerror = (error) => {
        console.error('WebSocket connection error:', error);

        // Don't show error notification on initial page load,
        // only show it after a connection was established then lost
        if (reconnectAttempts > 0 || isReady) {
          setConnectionError('Failed to connect to WebSocket server.');
        } else {
          console.log('Initial connection attempt failed, will retry...');
        }
      };

      socket.onclose = (event) => {
        console.warn('WebSocket connection closed', event);
        setIsReady(false);

        // Only attempt reconnect if we haven't reached max attempts
        if (reconnectAttempts < maxReconnectAttempts) {
          const delay = getReconnectDelay();
          setConnectionError(
            `Connection lost. Reconnecting in ${Math.ceil(delay / 1000)} seconds...`
          );
          console.log(
            `Scheduling reconnect in ${delay}ms (attempt ${reconnectAttempts + 1}/${maxReconnectAttempts})...`
          );

          // Store timer reference so we can cancel it if needed
          reconnectTimerRef.current = setTimeout(() => {
            setReconnectAttempts((prev) => prev + 1);
            connectWebSocket();
          }, delay);
        } else {
          setConnectionError(
            'Maximum reconnection attempts reached. Please reload the page.'
          );
          console.error(
            'Maximum reconnection attempts reached. WebSocket connection failed.'
          );
        }
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
                  message: `${title} — kept ${parsedEvent.data.segments_kept} segments`,
                  color: 'green.5',
                  loading: false,
                  autoClose: 4000,
                });
                try {
                  await useChannelsStore.getState().fetchRecordings();
                } catch {}
              } else if (status === 'skipped') {
                notifications.update({
                  id,
                  title: 'No commercials to remove',
                  message: parsedEvent.data.reason || '',
                  color: 'teal',
                  loading: false,
                  autoClose: 3000,
                });
                try {
                  await useChannelsStore.getState().fetchRecordings();
                } catch {}
              } else if (status === 'error') {
                notifications.update({
                  id,
                  title: 'Comskip failed',
                  message: parsedEvent.data.reason || 'Unknown error',
                  color: 'red',
                  loading: false,
                  autoClose: 6000,
                });
                try {
                  await useChannelsStore.getState().fetchRecordings();
                } catch {}
              }
              break;
            }
            case 'epg_file':
              fetchEPGs();
              notifications.show({
                title: 'EPG File Detected',
                message: `Processing ${parsedEvent.data.filename}`,
              });
              break;

            case 'm3u_file':
              fetchPlaylists();
              notifications.show({
                title: 'M3U File Detected',
                message: `Processing ${parsedEvent.data.filename}`,
              });
              break;

            case 'm3u_refresh':
              // Update the store with progress information
              setRefreshProgress(parsedEvent.data);

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
                    fetchPlaylists(); // Refresh playlists to ensure UI is up-to-date
                    fetchChannelProfiles(); // Ensure channel profiles are updated
                  }

                  updatePlaylist(updateData);
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
              setChannelStats(JSON.parse(parsedEvent.data.stats));
              break;

            case 'epg_channels':
              notifications.show({
                message: 'EPG channels updated!',
                color: 'green.5',
              });

              // If source_id is provided, update that specific EPG's status
              if (parsedEvent.data.source_id) {
                const epg = epgs[parsedEvent.data.source_id];
                if (epg) {
                  updateEPG({
                    ...epg,
                    status: 'success',
                  });
                }
              }

              fetchEPGData();
              break;

            case 'epg_match':
              notifications.show({
                message: parsedEvent.data.message || 'EPG match is complete!',
                color: 'green.5',
              });

              // Check if we have associations data and use the more efficient batch API
              if (
                parsedEvent.data.associations &&
                parsedEvent.data.associations.length > 0
              ) {
                API.batchSetEPG(parsedEvent.data.associations);
              }
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
                  await useChannelsStore.getState().fetchChannels();

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
                  await useChannelsStore.getState().fetchChannels();
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
              setProfilePreview(
                parsedEvent.data.search_preview,
                parsedEvent.data.result
              );
              break;

            case 'recording_updated':
              try {
                await useChannelsStore.getState().fetchRecordings();
              } catch (e) {
                console.warn('Failed to refresh recordings on update:', e);
              }
              break;

            case 'recordings_refreshed':
              try {
                await useChannelsStore.getState().fetchRecordings();
              } catch (e) {
                console.warn('Failed to refresh recordings on refreshed:', e);
              }
              break;

            case 'recording_started':
              notifications.show({
                title: 'Recording started!',
                message: `Started recording channel ${parsedEvent.data.channel}`,
              });
              try {
                await useChannelsStore.getState().fetchRecordings();
              } catch (e) {
                console.warn('Failed to refresh recordings on start:', e);
              }
              break;

            case 'recording_ended':
              notifications.show({
                title: 'Recording finished!',
                message: `Stopped recording channel ${parsedEvent.data.channel}`,
              });
              try {
                await useChannelsStore.getState().fetchRecordings();
              } catch (e) {
                console.warn('Failed to refresh recordings on end:', e);
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
                const epg = epgs[parsedEvent.data.source_id];
                if (epg) {
                  updateEPG({
                    ...epg,
                    status: 'error',
                    last_message: parsedEvent.data.message,
                  });
                }
              }
              break;

            case 'epg_refresh':
              // If we have source/account info, check if EPG exists before processing
              if (parsedEvent.data.source || parsedEvent.data.account) {
                const sourceId =
                  parsedEvent.data.source || parsedEvent.data.account;
                const epg = epgs[sourceId];

                // Only update progress if the EPG still exists in the store
                // This prevents crashes when receiving updates for deleted EPGs
                if (epg) {
                  // Update the store with progress information
                  updateEPGProgress(parsedEvent.data);
                } else {
                  // EPG was deleted, ignore this update
                  console.debug(
                    `Ignoring EPG refresh update for deleted EPG ${sourceId}`
                  );
                  break;
                }

                if (epg) {
                  // Check for any indication of an error (either via status or error field)
                  const hasError =
                    parsedEvent.data.status === 'error' ||
                    !!parsedEvent.data.error ||
                    (parsedEvent.data.message &&
                      parsedEvent.data.message.toLowerCase().includes('error'));

                  if (hasError) {
                    // Handle error state
                    const errorMessage =
                      parsedEvent.data.error ||
                      parsedEvent.data.message ||
                      'Unknown error occurred';

                    updateEPG({
                      ...epg,
                      status: 'error',
                      last_message: errorMessage,
                    });

                    // Show notification for the error
                    notifications.show({
                      title: 'EPG Refresh Error',
                      message: errorMessage,
                      color: 'red.5',
                    });
                  }
                  // Update status on completion only if no errors
                  else if (parsedEvent.data.progress === 100) {
                    updateEPG({
                      ...epg,
                      status: parsedEvent.data.status || 'success',
                      last_message:
                        parsedEvent.data.message || epg.last_message,
                      // Use the timestamp from the backend if provided
                      ...(parsedEvent.data.updated_at && {
                        updated_at: parsedEvent.data.updated_at,
                      }),
                    });

                    // Only show success notification if we've finished parsing programs and had no errors
                    if (parsedEvent.data.action === 'parsing_programs') {
                      notifications.show({
                        title: 'EPG Processing Complete',
                        message: 'EPG data has been updated successfully',
                        color: 'green.5',
                      });

                      fetchEPGData();
                    }
                  }
                }
              }
              break;

            case 'epg_sources_changed':
              // A plugin or backend process signaled that the EPG sources changed
              try {
                await fetchEPGs();
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
                await fetchEPGData();
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
              fetchLogos();
              break;

            case 'account_info_refresh_success':
              notifications.show({
                title: 'Account Info Refreshed',
                message: `Successfully updated account information for ${parsedEvent.data.profile_name}`,
                color: 'green',
                autoClose: 4000,
              });
              // Trigger refresh of playlists to update the UI
              fetchPlaylists();
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
                await useChannelsStore.getState().fetchChannels();
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
              fetchPlaylists();
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

      ws.current = socket;
    } catch (error) {
      console.error('Error creating WebSocket connection:', error);
      setConnectionError(`WebSocket error: ${error.message}`);

      // Schedule a reconnect if we haven't reached max attempts
      if (reconnectAttempts < maxReconnectAttempts) {
        const delay = getReconnectDelay();
        reconnectTimerRef.current = setTimeout(() => {
          setReconnectAttempts((prev) => prev + 1);
          connectWebSocket();
        }, delay);
      }
    }
  }, [
    reconnectAttempts,
    clearReconnectTimer,
    getReconnectDelay,
    getWebSocketUrl,
    isReady,
  ]);

  // Initial connection and cleanup
  useEffect(() => {
    // Only attempt to connect if the user is authenticated
    if (isAuthenticated && accessToken) {
      connectWebSocket();
    } else if (ws.current) {
      // Close the connection if the user logs out
      clearReconnectTimer();
      console.log('Closing WebSocket connection due to logout');
      ws.current.onclose = null;
      ws.current.close();
      ws.current = null;
      setIsReady(false);
    }

    return () => {
      clearReconnectTimer(); // Clear any pending reconnect timers

      if (ws.current) {
        console.log('Closing WebSocket connection due to component unmount');
        ws.current.onclose = null; // Remove handlers to avoid reconnection
        ws.current.close();
        ws.current = null;
      }
    };
  }, [connectWebSocket, clearReconnectTimer, isAuthenticated, accessToken]);

  const setChannelStats = useChannelsStore((s) => s.setChannelStats);
  const fetchPlaylists = usePlaylistsStore((s) => s.fetchPlaylists);
  const setRefreshProgress = usePlaylistsStore((s) => s.setRefreshProgress);
  const setProfilePreview = usePlaylistsStore((s) => s.setProfilePreview);
  const fetchEPGData = useEPGsStore((s) => s.fetchEPGData);
  const fetchEPGs = useEPGsStore((s) => s.fetchEPGs);
  const fetchLogos = useLogosStore((s) => s.fetchAllLogos);
  const fetchChannelProfiles = useChannelsStore((s) => s.fetchChannelProfiles);

  const ret = useMemo(() => {
    return [isReady, ws.current?.send.bind(ws.current), val];
  }, [isReady, val]);

  return (
    <WebsocketContext.Provider value={ret}>
      {connectionError &&
        !isReady &&
        reconnectAttempts >= maxReconnectAttempts && (
          <Alert
            color="red"
            title="WebSocket Connection Failed"
            style={{
              position: 'fixed',
              bottom: 10,
              right: 10,
              zIndex: 1000,
              maxWidth: 350,
            }}
          >
            {connectionError}
            <Button
              size="xs"
              mt={10}
              onClick={() => {
                setReconnectAttempts(0);
                connectWebSocket();
              }}
            >
              Try Again
            </Button>
          </Alert>
        )}
      {connectionError &&
        !isReady &&
        reconnectAttempts < maxReconnectAttempts &&
        reconnectAttempts > 0 && (
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
          </Alert>
        )}
      {children}
    </WebsocketContext.Provider>
  );
};

export const useWebSocket = () => {
  const socket = useContext(WebsocketContext);
  return socket;
};
