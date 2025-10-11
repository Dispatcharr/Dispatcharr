import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Divider,
  Drawer,
  Group,
  Progress,
  ScrollArea,
  Stack,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';
import { Ban, Play, RefreshCcw, Trash2, ScanSearch } from 'lucide-react';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';

import useLibraryStore from '../../store/library';
import useMediaLibraryStore from '../../store/mediaLibrary';

dayjs.extend(relativeTime);

const EMPTY_SCAN_LIST = [];

const statusColor = {
  pending: 'gray',
  queued: 'gray',
  scheduled: 'gray',
  running: 'blue',
  started: 'blue',
  discovered: 'indigo',
  progress: 'blue',
  completed: 'green',
  failed: 'red',
  cancelled: 'yellow',
};

const isRunning = (s) =>
  s === 'running' || s === 'started' || s === 'progress' || s === 'discovered';

const isQueued = (s) => s === 'pending' || s === 'queued' || s === 'scheduled';

const stageStatusLabel = {
  pending: 'Waiting',
  running: 'In progress',
  completed: 'Completed',
  skipped: 'Skipped',
};

const stageOrder = [
  { key: 'discovery', label: 'File scan' },
  { key: 'metadata', label: 'Metadata fetch' },
  { key: 'artwork', label: 'Artwork' },
];

const EMPTY_STAGE = {
  status: 'pending',
  processed: 0,
  total: 0,
};

const stageColorMap = {
  discovery: 'blue',
  metadata: 'green',
  artwork: 'red',
};

const PROGRESS_REFRESH_DELTA = 25;
const PROGRESS_REFRESH_INTERVAL_MS = 15000;

const LibraryScanDrawer = ({
  opened,
  onClose,
  libraryId,
  // Optional actions provided by parent (no-ops by default)
  onCancelJob = async () => {},
  onDeleteQueuedJob = async () => {},
  onStartScan = null,      // () => void
  onStartFullScan = null,  // () => void
}) => {
  const scansLoading = useLibraryStore((s) => s.scansLoading);
  const scans =
    useLibraryStore((s) => s.scans[libraryId || 'all']) ?? EMPTY_SCAN_LIST;
  const fetchScans = useLibraryStore((s) => s.fetchScans);
  const purgeCompletedScans = useLibraryStore((s) => s.purgeCompletedScans);
  const [loaderHold, setLoaderHold] = useState(false);
  const [purgeLoading, setPurgeLoading] = useState(false);
  const hasRunningRef = useRef(false);
  const hasQueuedRef = useRef(false);
  const lastProcessedRef = useRef(0);
  const lastLibraryRefreshRef = useRef(0);
  const refreshInFlightRef = useRef(false);

  const handleRefresh = useCallback(
    () => fetchScans(libraryId),
    [fetchScans, libraryId]
  );
  const hasRunningScan = useMemo(
    () => scans.some((scan) => isRunning(scan.status)),
    [scans]
  );
  const hasQueuedScan = useMemo(
    () => scans.some((scan) => isQueued(scan.status)),
    [scans]
  );
  const hasFinishedScans = useMemo(
    () =>
      scans.some((scan) =>
        ['completed', 'failed', 'cancelled'].includes(scan.status)
      ),
    [scans]
  );

  // Keep refs in sync for polling loop
  useEffect(() => {
    hasRunningRef.current = hasRunningScan;
  }, [hasRunningScan]);
  useEffect(() => {
    hasQueuedRef.current = hasQueuedScan;
  }, [hasQueuedScan]);

  useEffect(() => {
    if (!opened) {
      lastProcessedRef.current = 0;
      lastLibraryRefreshRef.current = 0;
      return undefined;
    }

    let cancelled = false;
    let timer;

    const runFetch = async (background) => {
      try {
        await fetchScans(libraryId, { background });
      } catch (error) {
        if (!background) {
          console.error('Failed to load library scans', error);
        }
      }
    };

    const loop = () => {
      if (cancelled) return;
      const delay = hasRunningRef.current
        ? 2000
        : hasQueuedRef.current
          ? 4000
          : 8000;
      timer = setTimeout(async () => {
        await runFetch(true);
        loop();
      }, delay);
    };

    void runFetch(false).then(loop);

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [opened, libraryId, fetchScans]);

  const totalProcessed = useMemo(
    () =>
      scans.reduce(
        (sum, scan) => sum + (Number(scan.processed_files) || 0),
        0
      ),
    [scans]
  );

  useEffect(() => {
    if (!opened) return;

    if (!hasRunningScan && !hasQueuedScan) {
      lastProcessedRef.current = totalProcessed;
      return;
    }

    const now = Date.now();
    const prevProcessed = lastProcessedRef.current;
    const processedDelta = Math.max(0, totalProcessed - prevProcessed);
    const elapsedSinceRefresh = now - lastLibraryRefreshRef.current;

    const shouldRefreshLibrary =
      processedDelta >= PROGRESS_REFRESH_DELTA ||
      elapsedSinceRefresh >= PROGRESS_REFRESH_INTERVAL_MS;

    if (!shouldRefreshLibrary || refreshInFlightRef.current) {
      return;
    }

    lastProcessedRef.current = totalProcessed;
    lastLibraryRefreshRef.current = now;
    refreshInFlightRef.current = true;

    const mediaStore = useMediaLibraryStore.getState();
    const activeIds = mediaStore.activeLibraryIds || [];

    void mediaStore
      .fetchItems(activeIds.length > 0 ? activeIds : undefined)
      .finally(() => {
        refreshInFlightRef.current = false;
      });
  }, [opened, hasRunningScan, hasQueuedScan, totalProcessed]);

  useEffect(() => {
    if (!opened) {
      setLoaderHold(false);
      return undefined;
    }
    if (scansLoading) {
      setLoaderHold(true);
      const timeout = setTimeout(() => setLoaderHold(false), 800);
      return () => clearTimeout(timeout);
    }
    setLoaderHold(false);
    return undefined;
  }, [opened, scansLoading]);

  const isInitialLoading =
    scans.length === 0 && (scansLoading || loaderHold);

  const getStagePercent = (stage) => {
    if (!stage) return 0;
    const processed = Math.max(0, Number(stage.processed) || 0);
    let total = Math.max(0, Number(stage.total) || 0);

    if (!total || total <= processed) {
      if (stage.status === 'completed') {
        total = processed || 1;
      } else {
        total = processed + 1;
      }
    }

    if (!total) return 0;
    return Math.min(100, Math.round((processed / total) * 100));
  };

  const formatStageCount = (stage, stageKey) => {
    if (!stage) return '0';
    const processed = stage.processed ?? 0;
    const total = stage.total ?? 0;

    if (stage.status === 'skipped') {
      return 'Not required';
    }
    if (total > 0 && total >= processed) {
      return `${processed} / ${total}`;
    }
    if (stage.status === 'completed' && processed === 0) {
      return 'Done';
    }

    const suffix =
      stageKey === 'discovery'
        ? 'files scanned'
        : stageKey === 'metadata'
          ? 'metadata items'
          : 'artwork assets';

    if (processed === 0) {
      return 'Waiting…';
    }

    return `${processed} ${suffix}`;
  };

  const handleClearFinished = useCallback(async () => {
    if (!hasFinishedScans) {
      return;
    }
    setPurgeLoading(true);
    try {
      await purgeCompletedScans({
        library: libraryId ?? undefined,
      });
      await fetchScans(libraryId, { background: true });
    } catch (error) {
      console.error('Failed to clear library scans', error);
    } finally {
      setPurgeLoading(false);
    }
  }, [hasFinishedScans, purgeCompletedScans, fetchScans, libraryId]);

  const header = useMemo(
    () => (
      <Group justify="space-between" align="center" mb="sm">
        <Group gap="xs" align="center">
          <ScanSearch size={18} />
          <Title order={5} style={{ lineHeight: 1 }}>Library scans</Title>
        </Group>

        <Group gap="xs">
          {onStartScan && (
            <Tooltip label="Start quick scan">
              <ActionIcon variant="light" onClick={onStartScan}>
                <Play size={16} />
              </ActionIcon>
            </Tooltip>
          )}
          {onStartFullScan && (
            <Button variant="light" size="xs" onClick={onStartFullScan}>
              Full scan
            </Button>
          )}
          {hasFinishedScans && (
            <Button
              variant="light"
              size="xs"
              onClick={handleClearFinished}
              loading={purgeLoading}
            >
              Clear finished
            </Button>
          )}
          <Tooltip label="Refresh">
            <ActionIcon variant="light" onClick={handleRefresh}>
              <RefreshCcw size={16} />
            </ActionIcon>
          </Tooltip>
        </Group>
      </Group>
    ),
    [onStartScan, onStartFullScan, handleRefresh, hasFinishedScans, purgeLoading, handleClearFinished]
  );

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      position="right"
      size="md"
      overlayProps={{ backgroundOpacity: 0.55, blur: 6 }}
      withCloseButton
      title={header}
    >
      <ScrollArea style={{ height: '100%' }}>
        {isInitialLoading ? (
          <Group justify="center" py="lg">
            <Text c="dimmed">Loading scans…</Text>
          </Group>
        ) : scans.length === 0 ? (
          <Stack align="center" py="lg" gap={4}>
            <Text c="dimmed">No scans recorded yet.</Text>
            {onStartScan && (
              <Button size="xs" onClick={onStartScan} mt="xs">
                Start a scan
              </Button>
            )}
          </Stack>
        ) : (
          <Stack gap="sm" py="xs">
            {scans.map((scan) => {
              const status = scan.status || 'pending';
              return (
                <Card key={scan.id} withBorder shadow="sm" radius="md">
                  <Stack gap="sm">
                    <Group justify="space-between" align="flex-start">
                      <Stack gap={4} style={{ flex: 1 }}>
                        <Group gap="xs" align="center">
                          <Badge color={statusColor[status] || 'gray'} variant="light">
                            {status}
                          </Badge>
                          <Text size="sm" fw={600}>
                            {scan.summary || 'Scan'}
                          </Text>
                        </Group>
                        <Text size="xs" c="dimmed">
                          {dayjs(scan.created_at).format('MMM D, YYYY HH:mm')}
                        </Text>
                      </Stack>
                      <Group gap="xs">
                        {isRunning(status) && (
                          <Tooltip label="Cancel running scan">
                            <ActionIcon
                              color="yellow"
                              variant="light"
                              onClick={() => onCancelJob(scan.id)}
                            >
                              <Ban size={16} />
                            </ActionIcon>
                          </Tooltip>
                        )}
                        {isQueued(status) && (
                          <Tooltip label="Remove from queue">
                            <ActionIcon
                              color="red"
                              variant="light"
                              onClick={() => onDeleteQueuedJob(scan.id)}
                            >
                              <Trash2 size={16} />
                            </ActionIcon>
                          </Tooltip>
                        )}
                      </Group>
                    </Group>

                    <Divider />

                    <Stack gap="sm">
                      {stageOrder.map(({ key, label }) => {
                        const stage = scan.stages?.[key] || EMPTY_STAGE;
                        const stageStatus = stage.status || 'pending';
                        const percent = getStagePercent(stage);
                        const progressColor = stageColorMap[key] || 'gray';
                        const badgeColor =
                          stageStatus === 'completed' || stageStatus === 'running'
                            ? progressColor
                            : 'gray';
                        const animated = stageStatus === 'running';
                        const percentDisplay =
                          stageStatus === 'completed'
                            ? '100%'
                            : stageStatus === 'skipped'
                              ? null
                              : `${percent}%`;
                        return (
                          <Stack gap={4} key={`${scan.id}-${key}`}>
                            <Group justify="space-between" align="center">
                              <Text size="xs" fw={500}>
                                {label}
                              </Text>
                              <Badge color={badgeColor} variant="light" size="xs">
                                {stageStatusLabel[stageStatus] || stageStatus}
                              </Badge>
                            </Group>
                            <Group justify="space-between" align="center">
                              <Text size="xs" c="dimmed">
                                {formatStageCount(stage, key)}
                              </Text>
                              {percentDisplay && (
                                <Text size="xs" c="dimmed">
                                  {percentDisplay}
                                </Text>
                              )}
                            </Group>
                            <Progress
                              value={percent}
                              size="sm"
                              striped={animated}
                              animated={animated}
                              color={progressColor}
                            />
                          </Stack>
                        );
                      })}
                    </Stack>

                    <Divider />

                    <Stack gap={4}>
                      <Text size="xs" c="dimmed">
                        Started {scan.started_at ? dayjs(scan.started_at).fromNow() : 'n/a'} · Finished{' '}
                        {scan.finished_at ? dayjs(scan.finished_at).fromNow() : 'n/a'}
                      </Text>
                      <Text size="xs" c="dimmed">
                        Files {scan.total_files ?? '—'} · New {scan.new_files ?? '—'} · Updated{' '}
                        {scan.updated_files ?? '—'} · Removed {scan.removed_files ?? '—'}
                      </Text>
                      {scan.unmatched_files > 0 && (
                        <Text size="xs" c="yellow.4">
                          Unmatched files: {scan.unmatched_files}
                        </Text>
                      )}
                      {scan.log && (
                        <Text size="xs" c="dimmed" style={{ whiteSpace: 'pre-wrap' }}>
                          {scan.log}
                        </Text>
                      )}
                    </Stack>
                  </Stack>
                </Card>
              );
            })}
          </Stack>
        )}
      </ScrollArea>
    </Drawer>
  );
};

export default LibraryScanDrawer;
