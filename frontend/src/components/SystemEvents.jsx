import React, { useState, useEffect, useCallback } from 'react';
import {
  ActionIcon,
  Box,
  Button,
  Card,
  Group,
  NumberInput,
  Pagination,
  Select,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { useElementSize } from '@mantine/hooks';
import {
  ChevronDown,
  CirclePlay,
  Download,
  Gauge,
  HardDriveDownload,
  List,
  LogIn,
  LogOut,
  RefreshCw,
  Shield,
  ShieldAlert,
  SquareX,
  Timer,
  Users,
  Video,
  XCircle,
} from 'lucide-react';
import dayjs from 'dayjs';
import API from '../api';
import useLocalStorage from '../hooks/useLocalStorage';

const SystemEvents = () => {
  const [events, setEvents] = useState([]);
  const [totalEvents, setTotalEvents] = useState(0);
  const [isExpanded, setIsExpanded] = useState(false);
  const { ref: cardRef, width: cardWidth } = useElementSize();
  const isNarrow = cardWidth < 650;
  const [isLoading, setIsLoading] = useState(false);
  const [dateFormatSetting] = useLocalStorage('date-format', 'mdy');
  const dateFormat = dateFormatSetting === 'mdy' ? 'MM/DD' : 'DD/MM';
  const [eventsRefreshInterval, setEventsRefreshInterval] = useLocalStorage(
    'events-refresh-interval',
    0
  );
  const [eventsLimit, setEventsLimit] = useLocalStorage('events-limit', 100);
  const [currentPage, setCurrentPage] = useState(1);

  // Calculate offset based on current page and limit
  const offset = (currentPage - 1) * eventsLimit;
  const totalPages = Math.ceil(totalEvents / eventsLimit);

  const fetchEvents = useCallback(async () => {
    try {
      setIsLoading(true);
      const response = await API.getSystemEvents(eventsLimit, offset);
      if (response && response.events) {
        setEvents(response.events);
        setTotalEvents(response.total || 0);
      }
    } catch (error) {
      console.error('Error fetching system events:', error);
    } finally {
      setIsLoading(false);
    }
  }, [eventsLimit, offset]);

  // Fetch events on mount and when eventsRefreshInterval changes
  useEffect(() => {
    fetchEvents();

    // Set up polling if interval is set and events section is expanded
    if (eventsRefreshInterval > 0 && isExpanded) {
      const interval = setInterval(fetchEvents, eventsRefreshInterval * 1000);
      return () => clearInterval(interval);
    }
  }, [fetchEvents, eventsRefreshInterval, isExpanded]);

  // Reset to first page when limit changes
  useEffect(() => {
    setCurrentPage(1);
  }, [eventsLimit]);

  const getEventIcon = (eventType) => {
    switch (eventType) {
      case 'channel_start':
        return <CirclePlay size={16} />;
      case 'channel_stop':
        return <SquareX size={16} />;
      case 'channel_reconnect':
        return <RefreshCw size={16} />;
      case 'channel_buffering':
        return <Timer size={16} />;
      case 'channel_failover':
        return <HardDriveDownload size={16} />;
      case 'client_connect':
        return <Users size={16} />;
      case 'client_disconnect':
        return <Users size={16} />;
      case 'recording_start':
        return <Video size={16} />;
      case 'recording_end':
        return <Video size={16} />;
      case 'stream_switch':
        return <HardDriveDownload size={16} />;
      case 'm3u_refresh':
        return <RefreshCw size={16} />;
      case 'm3u_download':
        return <Download size={16} />;
      case 'epg_refresh':
        return <RefreshCw size={16} />;
      case 'epg_download':
        return <Download size={16} />;
      case 'login_success':
        return <LogIn size={16} />;
      case 'login_failed':
        return <ShieldAlert size={16} />;
      case 'logout':
        return <LogOut size={16} />;
      case 'm3u_blocked':
        return <XCircle size={16} />;
      case 'epg_blocked':
        return <XCircle size={16} />;
      default:
        return <Gauge size={16} />;
    }
  };

  const getEventColor = (eventType) => {
    switch (eventType) {
      case 'channel_start':
      case 'client_connect':
      case 'recording_start':
      case 'login_success':
        return 'green';
      case 'channel_reconnect':
        return 'yellow';
      case 'channel_stop':
      case 'client_disconnect':
      case 'recording_end':
      case 'logout':
        return 'gray';
      case 'channel_buffering':
        return 'yellow';
      case 'channel_failover':
      case 'channel_error':
        return 'orange';
      case 'stream_switch':
        return 'blue';
      case 'm3u_refresh':
      case 'epg_refresh':
        return 'cyan';
      case 'm3u_download':
      case 'epg_download':
        return 'teal';
      case 'login_failed':
      case 'm3u_blocked':
      case 'epg_blocked':
        return 'red';
      default:
        return 'gray';
    }
  };

  return (
    <Card
      ref={cardRef}
      shadow="sm"
      padding="sm"
      radius="md"
      withBorder
      style={{
        color: '#fff',
        backgroundColor: '#27272A',
        width: '100%',
        maxWidth: isExpanded ? '100%' : '800px',
        marginLeft: 'auto',
        marginRight: 'auto',
        transition: 'max-width 0.3s ease',
      }}
    >
      <Group justify="space-between" mb={isExpanded ? 'sm' : 0}>
        <Group gap="xs">
          <Gauge size={20} />
          <Title order={4}>System Events</Title>
        </Group>
        <Group gap="xs">
          {(isExpanded || !isNarrow) && (
            <>
              <NumberInput
                size="xs"
                label="Events Per Page"
                value={eventsLimit}
                onChange={(value) => setEventsLimit(value || 10)}
                min={10}
                max={1000}
                step={10}
                style={{ width: 130 }}
              />
              <Select
                size="xs"
                label="Auto Refresh"
                value={eventsRefreshInterval.toString()}
                onChange={(value) => setEventsRefreshInterval(parseInt(value))}
                data={[
                  { value: '0', label: 'Manual' },
                  { value: '5', label: '5s' },
                  { value: '10', label: '10s' },
                  { value: '30', label: '30s' },
                  { value: '60', label: '1m' },
                ]}
                style={{ width: 120 }}
              />
              <Button
                size="xs"
                variant="subtle"
                onClick={fetchEvents}
                loading={isLoading}
                style={{ marginTop: 'auto' }}
              >
                Refresh
              </Button>
            </>
          )}
          <ActionIcon
            variant="subtle"
            onClick={() => setIsExpanded(!isExpanded)}
          >
            <ChevronDown
              size={18}
              style={{
                transform: isExpanded ? 'rotate(180deg)' : 'rotate(0deg)',
                transition: 'transform 0.2s',
              }}
            />
          </ActionIcon>
        </Group>
      </Group>

      {isExpanded && (
        <>
          {totalEvents > eventsLimit && (
            <Group justify="space-between" align="center" mt="sm" mb="xs">
              <Text size="xs" c="dimmed">
                Showing {offset + 1}-
                {Math.min(offset + eventsLimit, totalEvents)} of {totalEvents}
              </Text>
              <Pagination
                total={totalPages}
                value={currentPage}
                onChange={setCurrentPage}
                size="sm"
              />
            </Group>
          )}
          <Stack
            gap="xs"
            mt="sm"
            style={{
              maxHeight: '60vh',
              overflowY: 'auto',
            }}
          >
            {events.length === 0 ? (
              <Text size="sm" c="dimmed" ta="center" py="xl">
                No events recorded yet
              </Text>
            ) : (
              events.map((event) => (
                <Box
                  key={event.id}
                  p="xs"
                  style={{
                    backgroundColor: '#1A1B1E',
                    borderRadius: '4px',
                    borderLeft: `3px solid var(--mantine-color-${getEventColor(event.event_type)}-6)`,
                  }}
                >
                  <Group justify="space-between" wrap="nowrap">
                    <Group gap="xs" style={{ flex: 1, minWidth: 0 }}>
                      <Box c={`${getEventColor(event.event_type)}.6`}>
                        {getEventIcon(event.event_type)}
                      </Box>
                      <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
                        <Group gap="xs" wrap="nowrap">
                          <Text size="sm" fw={500}>
                            {event.event_type_display || event.event_type}
                          </Text>
                          {event.channel_name && (
                            <Text
                              size="sm"
                              c="dimmed"
                              truncate
                              style={{ maxWidth: '300px' }}
                            >
                              {event.channel_name}
                            </Text>
                          )}
                        </Group>
                        {event.details &&
                          Object.keys(event.details).length > 0 && (
                            <Text size="xs" c="dimmed">
                              {Object.entries(event.details)
                                .filter(
                                  ([key]) =>
                                    !['stream_url', 'new_url'].includes(key)
                                )
                                .map(([key, value]) => `${key}: ${value}`)
                                .join(', ')}
                            </Text>
                          )}
                      </Stack>
                    </Group>
                    <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
                      {dayjs(event.timestamp).format(`${dateFormat} HH:mm:ss`)}
                    </Text>
                  </Group>
                </Box>
              ))
            )}
          </Stack>
        </>
      )}
    </Card>
  );
};

export default SystemEvents;
