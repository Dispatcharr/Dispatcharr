import React, { useMemo, useState, useEffect, lazy, Suspense } from 'react';
import {
  Box,
  Button,
  Badge,
  Group,
  SimpleGrid,
  Stack,
  Text,
  Title,
  useMantineTheme,
} from '@mantine/core';
import {
  SquarePlus,
} from 'lucide-react';
import useChannelsStore from '../store/channels';
import useSettingsStore from '../store/settings';
import useVideoStore from '../store/useVideoStore';
import RecordingForm from '../components/forms/Recording';
import {
  useTimeHelpers,
} from '../utils/dateTimeUtils.js';
const RecordingDetailsModal = lazy(() => import('../components/forms/RecordingDetailsModal'));
import RecurringRuleModal from '../components/forms/RecurringRuleModal.jsx';
import RecordingCard from '../components/cards/RecordingCard.jsx';
import { categorizeRecordings } from '../utils/pages/DVRUtils.js';
import { getPosterUrl } from '../utils/cards/RecordingCardUtils.js';
import ErrorBoundary from '../components/ErrorBoundary.jsx';

const DVRPage = () => {
  const theme = useMantineTheme();
  const recordings = useChannelsStore((s) => s.recordings);
  const fetchRecordings = useChannelsStore((s) => s.fetchRecordings);
  const channels = useChannelsStore((s) => s.channels);
  const fetchChannels = useChannelsStore((s) => s.fetchChannels);
  const fetchRecurringRules = useChannelsStore((s) => s.fetchRecurringRules);
  const { toUserTime, userNow } = useTimeHelpers();

  const [recordingModalOpen, setRecordingModalOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [detailsRecording, setDetailsRecording] = useState(null);
  const [ruleModal, setRuleModal] = useState({ open: false, ruleId: null });
  const [editRecording, setEditRecording] = useState(null);

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

  const openRuleModal = (recording) => {
    const ruleId = recording?.custom_properties?.rule?.id;
    if (!ruleId) {
      openDetails(recording);
      return;
    }
    setDetailsOpen(false);
    setDetailsRecording(null);
    setEditRecording(null);
    setRuleModal({ open: true, ruleId });
  };

  const closeRuleModal = () => setRuleModal({ open: false, ruleId: null });

  useEffect(() => {
    if (!channels || Object.keys(channels).length === 0) {
      fetchChannels();
    }
    fetchRecordings();
    fetchRecurringRules();
  }, [channels, fetchChannels, fetchRecordings, fetchRecurringRules]);

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

  const RecordingList = ({ list }) => {
    return list.map((rec) => (
      <RecordingCard
        key={`rec-${rec.id}`}
        recording={rec}
        onOpenDetails={openDetails}
        onOpenRecurring={openRuleModal}
      />
    ));
  };

  const handleOnWatchLive = () => {
    const rec = detailsRecording;
    const now = userNow();
    const s = toUserTime(rec.start_time);
    const e = toUserTime(rec.end_time);
    if (now.isAfter(s) && now.isBefore(e)) {
      // call into child RecordingCard behavior by constructing a URL like there
      const channel = channels[rec.channel];
      if (!channel) return;
      let url = `/proxy/ts/stream/${channel.uuid}`;
      if (useSettingsStore.getState().environment.env_mode === 'dev') {
        url = `${window.location.protocol}//${window.location.hostname}:5656${url}`;
      }
      useVideoStore.getState().showVideo(url, 'live');
    }
  }

  const handleOnWatchRecording = () => {
    let fileUrl =
      detailsRecording.custom_properties?.file_url ||
      detailsRecording.custom_properties?.output_file_url;
    if (!fileUrl) return;
    if (
      useSettingsStore.getState().environment.env_mode === 'dev' &&
      fileUrl.startsWith('/')
    ) {
      fileUrl = `${window.location.protocol}//${window.location.hostname}:5656${fileUrl}`;
    }
    useVideoStore.getState().showVideo(fileUrl, 'vod', {
      name:
        detailsRecording.custom_properties?.program?.title ||
        'Recording',
      logo: {
        url: getPosterUrl(
          detailsRecording.custom_properties?.poster_logo_id,
          undefined,
          channels[detailsRecording.channel]?.logo?.cache_url
        )
      },
    });
  }
  return (
    <Box p={10}>
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
      <Stack gap="lg" style={{ paddingTop: 12 }}>
        <div>
          <Group justify="space-between" mb={8}>
            <Title order={4}>Currently Recording</Title>
            <Badge color="red.6">{inProgress.length}</Badge>
          </Group>
          <SimpleGrid
            cols={3}
            spacing="md"
            breakpoints={[
              { maxWidth: '62rem', cols: 2 },
              { maxWidth: '36rem', cols: 1 },
            ]}
          >
            {<RecordingList list={inProgress} />}
            {inProgress.length === 0 && (
              <Text size="sm" c="dimmed">
                Nothing recording right now.
              </Text>
            )}
          </SimpleGrid>
        </div>

        <div>
          <Group justify="space-between" mb={8}>
            <Title order={4}>Upcoming Recordings</Title>
            <Badge color="yellow.6">{upcoming.length}</Badge>
          </Group>
          <SimpleGrid
            cols={3}
            spacing="md"
            breakpoints={[
              { maxWidth: '62rem', cols: 2 },
              { maxWidth: '36rem', cols: 1 },
            ]}
          >
            {<RecordingList list={upcoming} />}
            {upcoming.length === 0 && (
              <Text size="sm" c="dimmed">
                No upcoming recordings.
              </Text>
            )}
          </SimpleGrid>
        </div>

        <div>
          <Group justify="space-between" mb={8}>
            <Title order={4}>Previously Recorded</Title>
            <Badge color="gray.6">{completed.length}</Badge>
          </Group>
          <SimpleGrid
            cols={3}
            spacing="md"
            breakpoints={[
              { maxWidth: '62rem', cols: 2 },
              { maxWidth: '36rem', cols: 1 },
            ]}
          >
            {<RecordingList list={completed} />}
            {completed.length === 0 && (
              <Text size="sm" c="dimmed">
                No completed recordings yet.
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
              channel={channels[detailsRecording.channel]}
              posterUrl={getPosterUrl(
                detailsRecording.custom_properties?.poster_logo_id,
                detailsRecording.custom_properties,
                channels[detailsRecording.channel]?.logo?.cache_url
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