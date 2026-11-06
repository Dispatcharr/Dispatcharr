import React, { useMemo, useState, useEffect, lazy, Suspense } from 'react';
import {
  ActionIcon,
  Box,
  Button,
  Badge,
  Flex,
  Group,
  Progress,
  Select,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Title,
  Tooltip,
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
import {
  categorizeRecordings,
  filterRecordings,
  buildChannelOptions,
} from '../utils/pages/DVRUtils.js';
import {
  getChannelLogoUrl,
  getPosterUrl,
  getRecordingUrl,
  getShowVideoUrl,
} from '../utils/cards/RecordingCardUtils.js';
import ErrorBoundary from '../components/ErrorBoundary.jsx';
import useAuthStore from '../store/auth';
import { canManageDvr, canRequestDvr } from '../utils/dvrAccess';

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
  canManage,
  canRequest,
  authUserId,
}) => {
  return list.map((rec) => {
    // Request-tier (non-manager) users may only act on recordings they own;
    // manager/admin can act on all of them.
    const isOwner = canRequest && rec.owner?.id === authUserId;
    return (
      <RecordingCard
        key={`rec-${rec.id}`}
        recording={rec}
        onOpenDetails={onOpenDetails}
        onOpenRecurring={onOpenRecurring}
        channel={channelsById?.[rec.channel]}
        canManage={canManage || isOwner}
      />
    );
  });
};

const DVRPage = () => {
  const theme = useMantineTheme();
  const recordings = useChannelsStore((s) => s.recordings);
  const fetchRecordings = useChannelsStore((s) => s.fetchRecordings);
  const fetchRecurringRules = useChannelsStore((s) => s.fetchRecurringRules);
  const authUser = useAuthStore((s) => s.user);
  const canManage = canManageDvr(authUser);
  const canRequest = canRequestDvr(authUser);
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
    if (!canManage) {
      openDetails(recording);
      return;
    }
    const ruleId = recording?.custom_properties?.rule?.id;
    if (!ruleId) {
      openDetails(recording);
      return;
    }
    setDetailsOpen(false);
    setDetailsRecording(null);
    setEditRecording(null);
    setRuleModal({
      open: true,
      ruleId,
      recording,
      isDelete: isDelete || false,
    });
  };

  const closeRuleModal = () => setRuleModal({ open: false, ruleId: null });

  useEffect(() => {
    fetchRecordings();
    if (canManage) {
      fetchRecurringRules();
    }
  }, [fetchRecordings, fetchRecurringRules, canManage]);

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

  // Server-wide DVR storage disk space -- informational for anyone who can
  // see this page; the server can run out of room even for a user with no
  // per-user quota, so this is independent of quotaInfo below.
  const [diskUsage, setDiskUsage] = useState(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const usage = await API.getDvrDiskUsage();
        if (!cancelled) setDiskUsage(usage || null);
      } catch (e) {
        console.warn('Failed to fetch DVR disk usage', e);
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

  // Per-user quota usage, request-tier only (manage/admin have no quota
  // concept -- they can already act on everything). Recordings here are
  // already scoped server-side to just this user's own (see
  // recordings_queryset_for_user), so a client-side sum is accurate
  // without a dedicated endpoint. In-progress recordings haven't finished
  // writing yet, so their contribution is an underestimate until they
  // complete -- consistent with how the backend itself only knows a
  // recording's real size once it's done. Shown even with no quota set
  // (quotaMb null) so a user can still see how much they're using.
  const quotaInfo = useMemo(() => {
    if (!canRequest || canManage) return null;
    const quotaMbRaw = Number(authUser?.custom_properties?.dvr_quota_mb) || 0;
    const quotaMb = quotaMbRaw > 0 ? quotaMbRaw : null;
    const usedBytes = recordings.reduce(
      (sum, rec) => sum + (Number(rec.custom_properties?.bytes_written) || 0),
      0
    );
    const usedMb = usedBytes / (1024 * 1024);
    return {
      quotaMb,
      usedMb,
      percent: quotaMb ? Math.min(100, (usedMb / quotaMb) * 100) : null,
    };
  }, [canRequest, canManage, authUser, recordings]);

  // Server-wide free disk space for the DVR storage root. Only shown to
  // admins/managers (who can already see/manage everything) or request-tier
  // users with no personal quota set -- a user who DOES have a quota is
  // capped well below server-wide free space, so showing it to them would
  // be misleading ("I have room" when their own quota says otherwise).
  // null while loading/unavailable or not applicable to this user.
  const diskUsageInfo = useMemo(() => {
    if (!diskUsage) return null;
    if (!canManage && !(quotaInfo && !quotaInfo.quotaMb)) return null;
    const toGb = (bytes) => Number(bytes) / (1024 * 1024 * 1024);
    const totalGb = toGb(diskUsage.total_bytes);
    const freeGb = toGb(diskUsage.free_bytes);
    return {
      freeGb,
      totalGb,
      percentUsed: totalGb ? Math.min(100, ((totalGb - freeGb) / totalGb) * 100) : 0,
    };
  }, [diskUsage, canManage, quotaInfo]);

  // Filtered buckets
  const hasActiveFilters =
    searchQuery !== '' || selectedChannelId !== null || selectedStatus !== null;

  const filteredInProgress = useMemo(() => {
    if (selectedStatus && selectedStatus !== 'recording') return [];
    return filterRecordings(inProgress, searchQuery, selectedChannelId);
  }, [inProgress, searchQuery, selectedChannelId, selectedStatus]);

  const filteredUpcoming = useMemo(() => {
    if (selectedStatus && selectedStatus !== 'scheduled') return [];
    return filterRecordings(upcoming, searchQuery, selectedChannelId);
  }, [upcoming, searchQuery, selectedChannelId, selectedStatus]);

  const filteredCompleted = useMemo(() => {
    if (
      selectedStatus &&
      !['completed', 'interrupted'].includes(selectedStatus)
    )
      return [];
    let filtered = filterRecordings(completed, searchQuery, selectedChannelId);
    if (selectedStatus === 'interrupted') {
      filtered = filtered.filter(
        (rec) => rec.custom_properties?.status === 'interrupted'
      );
    } else if (selectedStatus === 'completed') {
      // "Completed" includes both completed and stopped recordings
      filtered = filtered.filter(
        (rec) => rec.custom_properties?.status !== 'interrupted'
      );
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
      useVideoStore.getState().showVideo(url, 'live', { name: channel.name });
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
        {(canManage || canRequest) && (
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
        )}

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

      {(quotaInfo || diskUsageInfo) && (
        <Stack gap={4} mb={12}>
          {quotaInfo && (
            <Tooltip
              label={
                quotaInfo.quotaMb
                  ? `${quotaInfo.usedMb.toFixed(1)} MB used of ${quotaInfo.quotaMb} MB. Scheduling a new recording is blocked at/over quota; your oldest finished recording is automatically removed if a recording's final size pushes you over.`
                  : `${quotaInfo.usedMb.toFixed(1)} MB used. No per-user quota is set for your account -- you're only limited by the server's remaining disk space (see "Server storage" below).`
              }
              multiline
              w={280}
            >
              <Group gap={6} wrap="nowrap" miw={160} w="fit-content">
                <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
                  DVR quota
                </Text>
                {quotaInfo.quotaMb ? (
                  <>
                    <Progress
                      value={quotaInfo.percent}
                      color={quotaInfo.percent >= 100 ? 'red' : quotaInfo.percent >= 80 ? 'yellow' : 'teal'}
                      w={80}
                      size="sm"
                    />
                    <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
                      {quotaInfo.usedMb.toFixed(0)}/{quotaInfo.quotaMb} MB
                    </Text>
                  </>
                ) : (
                  <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
                    {quotaInfo.usedMb.toFixed(0)} MB used (unlimited)
                  </Text>
                )}
              </Group>
            </Tooltip>
          )}

          {diskUsageInfo && (
            <Tooltip
              label={`${diskUsageInfo.freeGb.toFixed(1)} GB free of ${diskUsageInfo.totalGb.toFixed(1)} GB on the server's DVR storage. This is shared by every user's recordings, independent of any per-user quota.`}
              multiline
              w={280}
            >
              <Group gap={6} wrap="nowrap" miw={170} w="fit-content">
                <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
                  Server storage
                </Text>
                <Progress
                  value={diskUsageInfo.percentUsed}
                  color={
                    diskUsageInfo.percentUsed >= 95
                      ? 'red'
                      : diskUsageInfo.percentUsed >= 85
                        ? 'yellow'
                        : 'teal'
                  }
                  w={80}
                  size="sm"
                />
                <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
                  {diskUsageInfo.freeGb.toFixed(0)} GB free
                </Text>
              </Group>
            </Tooltip>
          )}
        </Stack>
      )}

      <Stack gap="lg">
        <div>
          <Group gap="xs" align="center" mb={8}>
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
                canManage={canManage}
                canRequest={canRequest}
                authUserId={authUser?.id}
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
          <Group gap="xs" align="center" mb={8}>
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
                canManage={canManage}
                canRequest={canRequest}
                authUserId={authUser?.id}
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
          <Group gap="xs" align="center" mb={8}>
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
                canManage={canManage}
                canRequest={canRequest}
                authUserId={authUser?.id}
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

      {(canManage || canRequest) && (
        <RecordingForm
          isOpen={recordingModalOpen}
          onClose={closeRecordingModal}
        />
      )}

      {canManage && (
        <RecordingForm
          isOpen={Boolean(editRecording)}
          recording={editRecording}
          onClose={() => setEditRecording(null)}
        />
      )}

      {canManage && (
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
      )}

      {/* Details Modal */}
      {detailsRecording && (
        <ErrorBoundary inline>
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
              canManage={canManage}
              onEdit={
                canManage
                  ? (rec) => {
                      setEditRecording(rec);
                      closeDetails();
                    }
                  : undefined
              }
            />
          </Suspense>
        </ErrorBoundary>
      )}
    </Box>
  );
};

export default DVRPage;
