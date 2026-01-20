import React, {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  Box,
  Button,
  Group,
  LoadingOverlay,
  NumberInput,
  Text,
  Title,
} from '@mantine/core';
import useChannelsStore from '../store/channels';
import useLogosStore from '../store/logos';
import useStreamProfilesStore from '../store/streamProfiles';
import useLocalStorage from '../hooks/useLocalStorage';
import SystemEvents from '../components/SystemEvents';
import ErrorBoundary from '../components/ErrorBoundary.jsx';
import {
  fetchActiveChannelStats,
  getClientStats,
  getCombinedConnections,
  getCurrentPrograms,
  getStatsByChannelId,
  getVODStats,
  stopChannel,
  stopClient,
  stopVODClient,
} from '../utils/pages/StatsUtils.js';
const VodConnectionCard = React.lazy(
  () => import('../components/cards/VodConnectionCard.jsx')
);
const StreamConnectionCard = React.lazy(
  () => import('../components/cards/StreamConnectionCard.jsx')
);

const Connections = ({
  combinedConnections,
  clients,
  channelsByUUID,
  channels,
  handleStopVODClient,
  currentPrograms,
}) => {
  const logos = useLogosStore((s) => s.logos);

  return combinedConnections.length === 0 ? (
    <Box
      ta="center"
      p={40}
      style={{
        gridColumn: '1 / -1',
      }}
    >
      <Text size="xl" c="dimmed">
        No active connections
      </Text>
    </Box>
  ) : (
    <ErrorBoundary>
      <Suspense fallback={<LoadingOverlay />}>
        {combinedConnections.map((connection) => {
          if (connection.type === 'stream') {
            return (
              <StreamConnectionCard
                key={connection.id}
                channel={connection.data}
                clients={clients}
                stopClient={stopClient}
                stopChannel={stopChannel}
                logos={logos}
                channelsByUUID={channelsByUUID}
                channels={channels}
                currentProgram={currentPrograms[connection.data.channel_id]}
              />
            );
          } else if (connection.type === 'vod') {
            return (
              <VodConnectionCard
                key={connection.id}
                vodContent={connection.data}
                stopVODClient={handleStopVODClient}
              />
            );
          }
          return null;
        })}
      </Suspense>
    </ErrorBoundary>
  );
};

const StatsPage = () => {
  const channels = useChannelsStore((s) => s.channels);
  const channelsByUUID = useChannelsStore((s) => s.channelsByUUID);
  const channelStats = useChannelsStore((s) => s.stats);
  const setChannelStats = useChannelsStore((s) => s.setChannelStats);
  const streamProfiles = useStreamProfilesStore((s) => s.profiles);

  const [clients, setClients] = useState([]);
  const [vodConnections, setVodConnections] = useState([]);
  const [channelHistory, setChannelHistory] = useState({});
  const [isPollingActive, setIsPollingActive] = useState(false);
  const [currentPrograms, setCurrentPrograms] = useState({});

  // Use refs to hold latest values without triggering effects
  const channelHistoryRef = useRef(channelHistory);
  const channelsByUUIDRef = useRef(channelsByUUID);

  // Update refs when values change
  useEffect(() => {
    channelHistoryRef.current = channelHistory;
  }, [channelHistory]);

  useEffect(() => {
    channelsByUUIDRef.current = channelsByUUID;
  }, [channelsByUUID]);

  // Use localStorage for stats refresh interval (in seconds)
  const [refreshIntervalSeconds, setRefreshIntervalSeconds] = useLocalStorage(
    'stats-refresh-interval',
    5
  );
  const refreshInterval = refreshIntervalSeconds * 1000; // Convert to milliseconds
  const channelHistoryLength = Object.keys(channelHistory).length;
  const vodConnectionsCount = vodConnections.reduce(
    (total, vodContent) => total + (vodContent.connections?.length || 0),
    0
  );

  const handleStopVODClient = async (clientId) => {
    await stopVODClient(clientId);
    // Refresh VOD stats after stopping to update the UI
    fetchVODStats();
  };

  // Function to fetch channel stats from API
  const fetchChannelStats = useCallback(async () => {
    try {
      const response = await fetchActiveChannelStats();
      if (response) {
        setChannelStats(response);
      } else {
        console.log('API response was empty or null');
      }
    } catch (error) {
      console.error('Error fetching channel stats:', error);
      console.error('Error details:', {
        message: error.message,
        status: error.status,
        body: error.body,
      });
    }
  }, [setChannelStats]);

  const fetchVODStats = useCallback(async () => {
    try {
      const response = await getVODStats();
      if (response) {
        setVodConnections(response.vod_connections || []);
      } else {
        console.log('VOD API response was empty or null');
      }
    } catch (error) {
      console.error('Error fetching VOD stats:', error);
      console.error('Error details:', {
        message: error.message,
        status: error.status,
        body: error.body,
      });
    }
  }, []);

  // Set up polling for stats when on stats page
  useEffect(() => {
    const location = window.location;
    const isOnStatsPage = location.pathname === '/stats';

    if (isOnStatsPage && refreshInterval > 0) {
      setIsPollingActive(true);

      // Initial fetch
      fetchChannelStats();
      fetchVODStats();

      // Set up interval
      const interval = setInterval(() => {
        fetchChannelStats();
        fetchVODStats();
      }, refreshInterval);

      return () => {
        clearInterval(interval);
        setIsPollingActive(false);
      };
    } else {
      setIsPollingActive(false);
    }
  }, [refreshInterval, fetchChannelStats, fetchVODStats]);

  // Fetch initial stats on component mount (for immediate data when navigating to page)
  useEffect(() => {
    fetchChannelStats();
    fetchVODStats();
  }, [fetchChannelStats, fetchVODStats]);

  useEffect(() => {
    console.log('Processing channel stats:', channelStats);
    if (
      !channelStats ||
      !channelStats.channels ||
      !Array.isArray(channelStats.channels) ||
      channelStats.channels.length === 0
    ) {
      console.log('No channel stats available:', channelStats);
      // Clear clients and channel history when there are no stats
      setClients([]);
      setChannelHistory({});
      return;
    }

    // Use functional update to access previous state without dependency
    setChannelHistory((prevChannelHistory) => {
      // Create a completely new object based only on current channel stats
      const stats = getStatsByChannelId(
        channelStats,
        prevChannelHistory,
        channelsByUUID,
        channels,
        streamProfiles
      );

      console.log('Processed active channels:', stats);

      // Update clients based on new stats
      setClients(getClientStats(stats));

      return stats; // Return only currently active channels
    });
  }, [channelStats, channels, channelsByUUID, streamProfiles]);

  // Track which channel IDs are active (only changes when channels start/stop, not on stats updates)
  const activeChannelIds = useMemo(() => {
    return Object.keys(channelHistory).sort().join(',');
  }, [channelHistory]);

  // Smart polling for current programs - only fetch when active channels change
  useEffect(() => {
    // Skip if no active channels
    if (!activeChannelIds) {
      setCurrentPrograms({});
      return;
    }

    let timer = null;

    const fetchPrograms = async () => {
      // Use refs to get latest values without adding dependencies
      const programs = await getCurrentPrograms(
        channelHistoryRef.current,
        channelsByUUIDRef.current
      );
      setCurrentPrograms(programs);

      // Schedule next fetch based on nearest program end time
      if (programs && Object.keys(programs).length > 0) {
        const now = new Date();
        let nearestEndTime = null;

        Object.values(programs).forEach((program) => {
          if (program && program.end_time) {
            const endTime = new Date(program.end_time);
            if (
              endTime > now &&
              (!nearestEndTime || endTime < nearestEndTime)
            ) {
              nearestEndTime = endTime;
            }
          }
        });

        if (nearestEndTime) {
          const timeUntilChange = nearestEndTime.getTime() - now.getTime();
          const fetchDelay = Math.max(timeUntilChange + 5000, 0);

          timer = setTimeout(fetchPrograms, fetchDelay);
        }
      }
    };

    // Initial fetch
    fetchPrograms();

    // Cleanup timer on unmount or when active channels change
    return () => {
      if (timer) clearTimeout(timer);
    };
  }, [activeChannelIds]); // Only depend on activeChannelIds

  // Combine active streams and VOD connections into a single mixed list
  const combinedConnections = useMemo(() => {
    return getCombinedConnections(channelHistory, vodConnections);
  }, [channelHistory, vodConnections]);

  return (
    <>
      <Box style={{ overflowX: 'auto' }}>
        <Box miw={520}>
          <Box p={10} style={{ borderBottom: '1px solid #444' }}>
            <Group justify="space-between" align="center">
              <Title order={3}>Active Connections</Title>
              <Group align="center">
                <Text size="sm" c="dimmed">
                  {channelHistoryLength}{' '}
                  {channelHistoryLength !== 1 ? 'streams' : 'stream'} •{' '}
                  {vodConnectionsCount}{' '}
                  {vodConnectionsCount !== 1
                    ? 'VOD connections'
                    : 'VOD connection'}
                </Text>
                <Group align="center" gap="xs">
                  <Text size="sm">Refresh Interval (seconds):</Text>
                  <NumberInput
                    value={refreshIntervalSeconds}
                    onChange={(value) => setRefreshIntervalSeconds(value || 0)}
                    min={0}
                    max={300}
                    step={1}
                    size="xs"
                    w={120}
                  />
                  {refreshIntervalSeconds === 0 && (
                    <Text size="sm" c="dimmed">
                      Refreshing disabled
                    </Text>
                  )}
                </Group>
                {isPollingActive && refreshInterval > 0 && (
                  <Text size="sm" c="dimmed">
                    Refreshing every {refreshIntervalSeconds}s
                  </Text>
                )}
                <Button
                  size="xs"
                  variant="subtle"
                  onClick={() => {
                    fetchChannelStats();
                    fetchVODStats();
                  }}
                  loading={false}
                >
                  Refresh Now
                </Button>
              </Group>
            </Group>
          </Box>
          <Box
            style={{
              gap: '1rem',
              gridTemplateColumns: 'repeat(auto-fill, minmax(500px, 1fr))',
              alignContent: 'start',
            }}
            display="grid"
            p={10}
            pb={120}
            mih={'calc(100vh - 250px)'}
          >
            <Connections
              combinedConnections={combinedConnections}
              clients={clients}
              channelsByUUID={channelsByUUID}
              channels={channels}
              handleStopVODClient={handleStopVODClient}
              currentPrograms={currentPrograms}
            />
          </Box>
        </Box>
      </Box>

      {/* System Events Section - Fixed at bottom */}
      <Box
        style={{
          zIndex: 100,
          pointerEvents: 'none',
        }}
        pos="fixed"
        bottom={0}
        left="var(--app-shell-navbar-width, 0)"
        right={0}
        p={'0 1rem 1rem 1rem'}
      >
        <Box style={{ pointerEvents: 'auto' }}>
          <SystemEvents />
        </Box>
      </Box>
    </>
  );
};

export default StatsPage;
