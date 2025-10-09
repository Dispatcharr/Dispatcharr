import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Divider,
  Drawer,
  Group,
  Loader,
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

const stageStatusColor = {
  pending: 'gray',
  running: 'blue',
  completed: 'green',
  skipped: 'gray',
};

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
    const now = Date.now();
    const prevProcessed = lastProcessedRef.current;
    const shouldRefreshLibrary =
      (hasRunningScan || hasQueuedScan) &&
      (totalProcessed > prevProcessed ||
        now - lastLibraryRefreshRef.current > 15000);

    if (!shouldRefreshLibrary) {
      if (totalProcessed > prevProcessed) {
        lastProcessedRef.current = totalProcessed;
      }
      return;
    }

    lastProcessedRef.current = totalProcessed;
    lastLibraryRefreshRef.current = now;

    const mediaStore = useMediaLibraryStore.getState();
    const activeIds = mediaStore.activeLibraryIds || [];
    void mediaStore.fetchItems(
      activeIds.length > 0 ? activeIds : undefined
    );
  }, [opened, hasRunningScan, hasQueuedScan, totalProcessed]);

  useEffect(() => {
    if (!opened) {
      setLoaderHold(false);
      return undefined;
    }
    if (!scansLoading) {
      return undefined;
    }
    setLoaderHold(true);
    const timeout = setTimeout(() => setLoaderHold(false), 800);
    return () => clearTimeout(timeout);
  }, [opened, scansLoading]);

  const showLoader = scansLoading || loaderHold;

  const getStagePercent = (stage) => {
    if (!stage) return 0;
    if (stage.total > 0) {
      const denominator = stage.total === 0 ? 1 : stage.total;
      return Math.min(
        100,
        Math.round((stage.processed / denominator) * 100)
      );
    }
    if (stage.status === 'completed') return 100;
    if (stage.status === 'skipped') return 0;
    if (stage.status === 'running') return 100;
    return stage.processed > 0 ? 100 : 0;
  };

  const formatStageCount = (stage) => {
    if (!stage) return '0';
    if (stage.total > 0) {
      return `${stage.processed} / ${stage.total}`;
    }
    if (stage.status === 'skipped') {
      return 'Not required';
    }
    if (stage.status === 'completed' && stage.processed === 0) {
      return 'Done';
    }
    return `${stage.processed} item${stage.processed === 1 ? '' : 's'}`;
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
        {showLoader ? (
          <Group justify="center" py="lg">
            <Loader />
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
                        const color = stageStatusColor[stageStatus] || 'gray';
                        const animated = stageStatus === 'running';
                        return (
                          <Stack gap={4} key={`${scan.id}-${key}`}>
                            <Group justify="space-between" align="center">
                              <Text size="xs" fw={500}>
                                {label}
                              </Text>
                              <Badge color={color} variant="light" size="xs">
                                {stageStatusLabel[stageStatus] || stageStatus}
                              </Badge>
                            </Group>
                            <Group justify="space-between" align="center">
                              <Text size="xs" c="dimmed">
                                {formatStageCount(stage)}
                              </Text>
                              {stage.total > 0 && (
                                <Text size="xs" c="dimmed">
                                  {percent}%
                                </Text>
                              )}
                            </Group>
                            <Progress
                              value={percent}
                              size="sm"
                              striped={animated}
                              animated={animated}
                              color={color}
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
