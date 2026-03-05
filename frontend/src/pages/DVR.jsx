import React, { useMemo, useState, useEffect, lazy, Suspense } from 'react';
import {
  ActionIcon,
  Box,
  Button,
  Badge,
  Flex,
  Group,
  Select,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Title,
  useMantineTheme,
} from '@mantine/core';
import { Search, SquarePlus, X } from 'lucide-react';
import useChannelsStore from '../store/channels';
import API from '../api';
import useSettingsStore from '../store/settings';
import useVideoStore from '../store/useVideoStore';
import RecordingForm from '../components/forms/Recording';
import { isAfter, isBefore, useTimeHelpers } from '../utils/dateTimeUtils.js';
const RecordingDetailsModal = lazy(
  () => import('../components/forms/RecordingDetailsModal')
);
import RecurringRuleModal from '../components/forms/RecurringRuleModal.jsx';
import RecordingCard from '../components/cards/RecordingCard.jsx';
import { categorizeRecordings, filterRecordings, buildChannelOptions } from '../utils/pages/DVRUtils.js';
import {
  getChannelLogoUrl,
  getPosterUrl,
  getRecordingUrl,
  getShowVideoUrl,
} from '../utils/cards/RecordingCardUtils.js';
import ErrorBoundary from '../components/ErrorBoundary.jsx';

const STATUS_OPTIONS = [
  { value: 'recording', label: 'Recording' },
  { value: 'scheduled', label: 'Scheduled' },
  { value: 'completed', label: 'Completed' },
  { value: 'interrupted', label: 'Interrupted' },
];

const RecordingList = ({
  list,
  onOpenDetails,
  onOpenRecurring,
  channelsById,
}) => {
  return list.map((rec) => (
    <RecordingCard
      key={`rec-${rec.id}`}
      recording={rec}
      onOpenDetails={onOpenDetails}
      onOpenRecurring={onOpenRecurring}
      channel={channelsById?.[rec.channel]}
    />
  ));
};

const DVRPage = () => {
  const theme = useMantineTheme();
  const recordings = useChannelsStore((s) => s.recordings);
  const fetchRecordings = useChannelsStore((s) => s.fetchRecordings);
  const fetchRecurringRules = useChannelsStore((s) => s.fetchRecurringRules);
  const [channelsById, setChannelsById] = useState({});
  const { toUserTime, userNow } = useTimeHelpers();

  const [recordingModalOpen, setRecordingModalOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [detailsRecording, setDetailsRecording] = useState(null);
  const [ruleModal, setRuleModal] = useState({ open: false, ruleId: null });
  const [editRecording, setEditRecording] = useState(null);

  // Filter state
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedChannelId, setSelectedChannelId] = useState(null);
  const [selectedStatus, setSelectedStatus] = useState(null);

  const openRecordingModal = () => {
    setRecordingModalOpen(true);
  };

  const closeRecordingModal = () => {
    setRecordingModalOpen(false);
  };

  const openDetails = (recording) => {
    setDetailsRecording(recording);
    setDetailsOpen(true);
  };
  const closeDetails = () => setDetailsOpen(false);

  const openRuleModal = (recording, isDelete) => {
    const ruleId = recording?.custom_properties?.rule?.id;
    if (!ruleId) {
      openDetails(recording);
      return;
    }
    setDetailsOpen(false);
    setDetailsRecording(null);
    setEditRecording(null);
    setRuleModal({ open: true, ruleId, recording, isDelete: isDelete || false });
  };

  const closeRuleModal = () => setRuleModal({ open: false, ruleId: null });

  useEffect(() => {
    fetchRecordings();
    fetchRecurringRules();
  }, [fetchRecordings, fetchRecurringRules]);

  // Load channel details for recordings via lightweight summary API
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const channels = await API.getChannelsSummary();
        if (cancelled) return;
        const byId = {};
        for (const ch of channels) if (ch?.id) byId[ch.id] = ch;
        setChannelsById(byId);
      } catch (e) {
        console.warn('Failed to fetch channels for DVR page', e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Re-render every second so time-based bucketing updates without a refresh
  const [now, setNow] = useState(userNow());
  useEffect(() => {
    const interval = setInterval(() => setNow(userNow()), 1000);
    return () => clearInterval(interval);
  }, [userNow]);

  useEffect(() => {
    setNow(userNow());
  }, [userNow]);

  // Categorize recordings
  const { inProgress, upcoming, completed } = useMemo(() => {
    return categorizeRecordings(recordings, toUserTime, now);
  }, [recordings, now, toUserTime]);

  // Channel options for filter dropdown (from raw unfiltered data)
  const channelOptions = useMemo(() => {
    return buildChannelOptions(channelsById, inProgress, upcoming, completed);
  }, [channelsById, inProgress, upcoming, completed]);

  // Filtered buckets
  const hasActiveFilters = searchQuery !== '' || selectedChannelId !== null || selectedStatus !== null;

  const filteredInProgress = useMemo(() => {
    if (selectedStatus && selectedStatus !== 'recording') return [];
    return filterRecordings(inProgress, searchQuery, selectedChannelId);
  }, [inProgress, searchQuery, selectedChannelId, selectedStatus]);

  const filteredUpcoming = useMemo(() => {
    if (selectedStatus && selectedStatus !== 'scheduled') return [];
    return filterRecordings(upcoming, searchQuery, selectedChannelId);
  }, [upcoming, searchQuery, selectedChannelId, selectedStatus]);

  const filteredCompleted = useMemo(() => {
    if (selectedStatus && !['completed', 'interrupted'].includes(selectedStatus)) return [];
    let filtered = filterRecordings(completed, searchQuery, selectedChannelId);
    if (selectedStatus === 'interrupted') {
      filtered = filtered.filter((rec) => rec.custom_properties?.status === 'interrupted');
    } else if (selectedStatus === 'completed') {
      // "Completed" includes both completed and stopped recordings
      filtered = filtered.filter((rec) => rec.custom_properties?.status !== 'interrupted');
    }
    return filtered;
  }, [completed, searchQuery, selectedChannelId, selectedStatus]);

  // Filter handlers
  const clearFilters = () => {
    setSearchQuery('');
    setSelectedChannelId(null);
    setSelectedStatus(null);
  };

  const handleOnWatchLive = () => {
    const rec = detailsRecording;
    const now = userNow();
    const s = toUserTime(rec.start_time);
    const e = toUserTime(rec.end_time);
    if (isAfter(now, s) && isBefore(now, e)) {
      // call into child RecordingCard behavior by constructing a URL like there
      const channel = channelsById[rec.channel];
      if (!channel) return;
      const url = getShowVideoUrl(
        channel,
        useSettingsStore.getState().environment.env_mode
      );
      useVideoStore.getState().showVideo(url, 'live');
    }
  };

  const handleOnWatchRecording = () => {
    const url = getRecordingUrl(
      detailsRecording.custom_properties,
      useSettingsStore.getState().environment.env_mode
    );
    if (!url) return;
    useVideoStore.getState().showVideo(url, 'vod', {
      name: detailsRecording.custom_properties?.program?.title || 'Recording',
      logo: {
        url: getPosterUrl(
          detailsRecording.custom_properties?.poster_logo_id,
          undefined,
          getChannelLogoUrl(channelsById[detailsRecording.channel])
        ),
      },
    });
  };
  return (
    <Box p={10}>
      <Flex gap="md" align="center" wrap="wrap" mb={12}>
        <Button
          leftSection={<SquarePlus size={18} />}
          variant="light"
          size="sm"
          onClick={openRecordingModal}
          p={5}
          color={theme.tailwind.green[5]}
          style={{
            borderWidth: '1px',
            borderColor: theme.tailwind.green[5],
            color: 'white',
          }}
        >
          New Recording
        </Button>

        <TextInput
          placeholder="Search recordings..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          w={'250px'}
          leftSection={<Search size={16} />}
          rightSection={
            searchQuery ? (
              <ActionIcon
                onClick={() => setSearchQuery('')}
                variant="subtle"
                color="gray"
                size="sm"
              >
                <X size={14} />
              </ActionIcon>
            ) : null
          }
        />

        <Select
          placeholder="Filter by channel"
          data={channelOptions}
          value={selectedChannelId}
          onChange={setSelectedChannelId}
          w={'220px'}
          clearable
          searchable
        />

        <Select
          placeholder="Filter by status"
          data={STATUS_OPTIONS}
          value={selectedStatus}
          onChange={setSelectedStatus}
          w={'180px'}
          clearable
        />

        {hasActiveFilters && (
          <Button variant="subtle" onClick={clearFilters} size="sm">
            Clear Filters
          </Button>
        )}
      </Flex>
      <Stack gap="lg">
        <div>
          <Group justify="space-between" mb={8}>
            <Title order={4}>Currently Recording</Title>
            <Badge color="red.6">
              {hasActiveFilters
                ? `${filteredInProgress.length} / ${inProgress.length}`
                : inProgress.length}
            </Badge>
          </Group>
          <SimpleGrid
            cols={3}
            spacing="md"
            breakpoints={[
              { maxWidth: '62rem', cols: 2 },
              { maxWidth: '36rem', cols: 1 },
            ]}
          >
            {
              <RecordingList
                list={filteredInProgress}
                onOpenDetails={openDetails}
                onOpenRecurring={openRuleModal}
                channelsById={channelsById}
              />
            }
            {filteredInProgress.length === 0 && (
              <Text size="sm" c="dimmed">
                {hasActiveFilters
                  ? 'No recordings match your filters.'
                  : 'Nothing recording right now.'}
              </Text>
            )}
          </SimpleGrid>
        </div>

        <div>
          <Group justify="space-between" mb={8}>
            <Title order={4}>Upcoming Recordings</Title>
            <Badge color="yellow.6">
              {hasActiveFilters
                ? `${filteredUpcoming.length} / ${upcoming.length}`
                : upcoming.length}
            </Badge>
          </Group>
          <SimpleGrid
            cols={3}
            spacing="md"
            breakpoints={[
              { maxWidth: '62rem', cols: 2 },
              { maxWidth: '36rem', cols: 1 },
            ]}
          >
            {
              <RecordingList
                list={filteredUpcoming}
                onOpenDetails={openDetails}
                onOpenRecurring={openRuleModal}
                channelsById={channelsById}
              />
            }
            {filteredUpcoming.length === 0 && (
              <Text size="sm" c="dimmed">
                {hasActiveFilters
                  ? 'No recordings match your filters.'
                  : 'No upcoming recordings.'}
              </Text>
            )}
          </SimpleGrid>
        </div>

        <div>
          <Group justify="space-between" mb={8}>
            <Title order={4}>Previously Recorded</Title>
            <Badge color="gray.6">
              {hasActiveFilters
                ? `${filteredCompleted.length} / ${completed.length}`
                : completed.length}
            </Badge>
          </Group>
          <SimpleGrid
            cols={3}
            spacing="md"
            breakpoints={[
              { maxWidth: '62rem', cols: 2 },
              { maxWidth: '36rem', cols: 1 },
            ]}
          >
            {
              <RecordingList
                list={filteredCompleted}
                onOpenDetails={openDetails}
                onOpenRecurring={openRuleModal}
                channelsById={channelsById}
              />
            }
            {filteredCompleted.length === 0 && (
              <Text size="sm" c="dimmed">
                {hasActiveFilters
                  ? 'No recordings match your filters.'
                  : 'No completed recordings yet.'}
              </Text>
            )}
          </SimpleGrid>
        </div>
      </Stack>

      <RecordingForm
        isOpen={recordingModalOpen}
        onClose={closeRecordingModal}
      />

      <RecordingForm
        isOpen={Boolean(editRecording)}
        recording={editRecording}
        onClose={() => setEditRecording(null)}
      />

      <RecurringRuleModal
        opened={ruleModal.open}
        onClose={closeRuleModal}
        ruleId={ruleModal.ruleId}
        recording={ruleModal.recording}
        onEditOccurrence={(occ) => {
          setRuleModal({ open: false, ruleId: null });
          setEditRecording(occ);
        }}
      />

      {/* Details Modal */}
      {detailsRecording && (
        <ErrorBoundary>
          <Suspense fallback={<Text>Loading...</Text>}>
            <RecordingDetailsModal
              opened={detailsOpen}
              onClose={closeDetails}
              recording={detailsRecording}
              channel={channelsById[detailsRecording.channel]}
              posterUrl={getPosterUrl(
                detailsRecording.custom_properties?.poster_logo_id,
                detailsRecording.custom_properties,
                getChannelLogoUrl(channelsById[detailsRecording.channel])
              )}
              env_mode={useSettingsStore.getState().environment.env_mode}
              onWatchLive={handleOnWatchLive}
              onWatchRecording={handleOnWatchRecording}
              onEdit={(rec) => {
                setEditRecording(rec);
                closeDetails();
              }}
            />
          </Suspense>
        </ErrorBoundary>
      )}
    </Box>
  );
};

export default DVRPage;
