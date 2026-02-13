import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Divider,
  Drawer,
  Group,
  Paper,
  Progress,
  ScrollArea,
  SegmentedControl,
  Select,
  Stack,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Ban, RefreshCcw, Trash2, ScanSearch } from 'lucide-react';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';

import useLibraryStore from '../../store/library';
import useMediaLibraryStore from '../../store/mediaLibrary';
import ConfirmationDialog from '../ConfirmationDialog';

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

const getScanTypeLabel = (scanType) => (scanType === 'full' ? 'Full' : 'Quick');

const LibraryScanDrawer = ({
  opened,
  onClose,
  libraryId,
  libraryIds = null,
  onCancelJob = async () => {},
  onDeleteQueuedJob = async () => {},
  onStartScan = null,
  onStartFullScan = null,
}) => {
  const libraries = useLibraryStore((s) => s.libraries);
  const fetchLibraries = useLibraryStore((s) => s.fetchLibraries);
  const scansByKey = useLibraryStore((s) => s.scans);
  const scansLoading = useLibraryStore((s) => s.scansLoading);
  const fetchScans = useLibraryStore((s) => s.fetchScans);
  const purgeCompletedScans = useLibraryStore((s) => s.purgeCompletedScans);

  const [scopeMode, setScopeMode] = useState('single');
  const [selectedLibraryId, setSelectedLibraryId] = useState(libraryId || null);
  const [loaderHold, setLoaderHold] = useState(false);
  const [purgeLoading, setPurgeLoading] = useState(false);
  const [startLoading, setStartLoading] = useState(false);
  const [confirmFullOpen, setConfirmFullOpen] = useState(false);

  const hasRunningRef = useRef(false);
  const hasQueuedRef = useRef(false);
  const lastProcessedRef = useRef(0);
  const lastLibraryRefreshRef = useRef(0);
  const refreshInFlightRef = useRef(false);

  const hasExplicitLibraryFilter = Array.isArray(libraryIds) && libraryIds.length > 0;
  const allowedLibraryIdSet = useMemo(() => {
    if (!hasExplicitLibraryFilter) return null;
    return new Set(libraryIds.map((id) => Number(id)).filter((id) => Number.isInteger(id)));
  }, [hasExplicitLibraryFilter, libraryIds]);

  const allowedLibraries = useMemo(() => {
    const all = Array.isArray(libraries) ? libraries : [];
    if (!allowedLibraryIdSet) return all;
    return all.filter((lib) => allowedLibraryIdSet.has(lib.id));
  }, [libraries, allowedLibraryIdSet]);

  const libraryOptions = useMemo(
    () => allowedLibraries.map((lib) => ({ value: String(lib.id), label: lib.name })),
    [allowedLibraries]
  );

  useEffect(() => {
    if (opened) {
      fetchLibraries();
    }
  }, [opened, fetchLibraries]);

  useEffect(() => {
    if (libraryId) {
      setSelectedLibraryId(libraryId);
      setScopeMode('single');
    }
  }, [libraryId]);

  useEffect(() => {
    if (!opened) return;
    if (!selectedLibraryId && allowedLibraries[0]?.id) {
      setSelectedLibraryId(allowedLibraries[0].id);
      return;
    }
    if (
      selectedLibraryId &&
      !allowedLibraries.some((lib) => lib.id === selectedLibraryId)
    ) {
      setSelectedLibraryId(allowedLibraries[0]?.id ?? null);
    }
  }, [opened, selectedLibraryId, allowedLibraries]);

  useEffect(() => {
    if (allowedLibraries.length <= 1 && scopeMode !== 'single') {
      setScopeMode('single');
    }
  }, [allowedLibraries.length, scopeMode]);

  const effectiveScope =
    scopeMode === 'all' && allowedLibraries.length > 1 ? 'all' : 'single';

  const selectedLibrary = useMemo(
    () => allowedLibraries.find((lib) => lib.id === selectedLibraryId) || null,
    [allowedLibraries, selectedLibraryId]
  );

  const effectiveLibraryId =
    effectiveScope === 'single' ? selectedLibrary?.id || null : null;

  const libraryNameById = useMemo(
    () => new Map(allowedLibraries.map((lib) => [lib.id, lib.name])),
    [allowedLibraries]
  );

  const scans = useMemo(() => {
    const sourceKey = effectiveLibraryId || 'all';
    const source = scansByKey[sourceKey] ?? EMPTY_SCAN_LIST;
    if (effectiveScope === 'all' && allowedLibraryIdSet) {
      return source.filter((scan) => allowedLibraryIdSet.has(scan.library));
    }
    if (effectiveScope === 'single' && effectiveLibraryId) {
      return source.filter((scan) => scan.library === effectiveLibraryId);
    }
    return source;
  }, [scansByKey, effectiveScope, effectiveLibraryId, allowedLibraryIdSet]);

  const handleRefresh = useCallback(
    () => fetchScans(effectiveLibraryId || null),
    [fetchScans, effectiveLibraryId]
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

  const scanSummary = useMemo(() => {
    let running = 0;
    let queued = 0;
    let completed = 0;
    scans.forEach((scan) => {
      if (isRunning(scan.status)) running += 1;
      else if (isQueued(scan.status)) queued += 1;
      else if (scan.status === 'completed') completed += 1;
    });
    const activeLibraries = new Set(scans.map((scan) => scan.library)).size;
    return { running, queued, completed, activeLibraries };
  }, [scans]);

  const targetLibraries = useMemo(() => {
    if (effectiveScope === 'single') {
      return selectedLibrary ? [selectedLibrary] : [];
    }
    return allowedLibraries;
  }, [effectiveScope, selectedLibrary, allowedLibraries]);

  const quickActionLabel =
    effectiveScope === 'single' && selectedLibrary
      ? `Quick scan ${selectedLibrary.name}`
      : 'Quick scan all libraries';
  const fullActionLabel =
    effectiveScope === 'single' && selectedLibrary
      ? `Full scan ${selectedLibrary.name}`
      : 'Full scan all libraries';

  const fullScanConfirmMessage = useMemo(() => {
    if (effectiveScope === 'single' && selectedLibrary) {
      return (
        <div style={{ whiteSpace: 'pre-line' }}>
          {`Run a full scan for ${selectedLibrary.name}?\n\nThis reprocesses all files and refreshes metadata/artwork for ${selectedLibrary.name}.`}
        </div>
      );
    }
    const names = targetLibraries.map((lib) => lib.name);
    const preview =
      names.length > 4 ? `${names.slice(0, 4).join(', ')}, and ${names.length - 4} more` : names.join(', ');
    return (
      <div style={{ whiteSpace: 'pre-line' }}>
        {`Run a full scan for all selected libraries?\n\n${preview}\n\nThis reprocesses all files and refreshes metadata/artwork for each library.`}
      </div>
    );
  }, [effectiveScope, selectedLibrary, targetLibraries]);

  const triggerScanAction = useCallback(
    async (full = false) => {
      const starter = full ? onStartFullScan : onStartScan;
      const targets = targetLibraries;
      if (!starter || targets.length === 0) {
        return;
      }

      setStartLoading(true);
      let queued = 0;
      let failed = 0;

      for (const library of targets) {
        try {
          const scan = await starter(library.id, {
            suppressNotification: true,
            source: 'scan-drawer',
          });
          if (scan) {
            queued += 1;
          } else {
            failed += 1;
          }
        } catch (error) {
          failed += 1;
          console.error('Failed to queue scan', error);
        }
      }

      await fetchScans(effectiveLibraryId || null, { background: true });
      setStartLoading(false);

      if (queued > 0) {
        notifications.show({
          title: full ? 'Full scans queued' : 'Scans queued',
          message:
            effectiveScope === 'single' && targets[0]
              ? `${full ? 'Full' : 'Quick'} scan queued for ${targets[0].name}.`
              : `${full ? 'Full' : 'Quick'} scans queued for ${queued} libraries.`,
          color: failed > 0 ? 'yellow' : 'blue',
        });
      } else if (failed > 0) {
        notifications.show({
          title: 'Unable to queue scans',
          message: 'No scan jobs were queued. Check logs and try again.',
          color: 'red',
        });
      }
    },
    [targetLibraries, onStartScan, onStartFullScan, fetchScans, effectiveLibraryId, effectiveScope]
  );

  const handleStartQuick = useCallback(() => {
    void triggerScanAction(false);
  }, [triggerScanAction]);

  const handleConfirmFullScan = useCallback(() => {
    setConfirmFullOpen(false);
    void triggerScanAction(true);
  }, [triggerScanAction]);

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
        await fetchScans(effectiveLibraryId || null, { background });
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
  }, [opened, effectiveLibraryId, fetchScans]);

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
      .fetchItemsIncremental(activeIds.length > 0 ? activeIds : undefined, {
        background: true,
      })
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
    const status = stage.status || 'pending';
    const isDiscoveryRunningUnknown =
      stageKey === 'discovery' &&
      status === 'running' &&
      (!total || total <= processed);

    if (isDiscoveryRunningUnknown) {
      return processed > 0 ? `${processed} files scanned` : 'Scanning files...';
    }

    if (status === 'skipped') {
      return 'Not required';
    }
    if (total > 0 && total >= processed) {
      return `${processed} / ${total}`;
    }
    if (status === 'completed' && processed === 0) {
      return 'Done';
    }

    const suffix =
      stageKey === 'discovery'
        ? 'files scanned'
        : stageKey === 'metadata'
          ? 'metadata items'
          : 'artwork assets';

    if (processed === 0) {
      return 'Waiting...';
    }

    return `${processed} ${suffix}`;
  };

  const handleClearFinished = useCallback(async () => {
    if (!hasFinishedScans) {
      return;
    }
    setPurgeLoading(true);
    try {
      if (effectiveScope === 'single') {
        await purgeCompletedScans({
          library: effectiveLibraryId ?? undefined,
        });
      } else if (hasExplicitLibraryFilter) {
        await Promise.all(
          allowedLibraries.map((library) =>
            purgeCompletedScans({ library: library.id })
          )
        );
      } else {
        await purgeCompletedScans({ library: undefined });
      }
      await fetchScans(effectiveLibraryId || null, { background: true });
    } catch (error) {
      console.error('Failed to clear library scans', error);
    } finally {
      setPurgeLoading(false);
    }
  }, [
    hasFinishedScans,
    purgeCompletedScans,
    fetchScans,
    effectiveScope,
    effectiveLibraryId,
    hasExplicitLibraryFilter,
    allowedLibraries,
  ]);

  const header = useMemo(
    () => (
      <Group justify="space-between" align="center" mb="sm">
        <Group gap="xs" align="center">
          <ScanSearch size={18} />
          <Title order={5} style={{ lineHeight: 1 }}>Library scans</Title>
        </Group>

        <Group gap="xs">
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
    [handleRefresh, hasFinishedScans, purgeLoading, handleClearFinished]
  );

  return (
    <>
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
          <Stack gap="sm" py="xs">
            <Paper withBorder radius="md" p="sm">
              <Stack gap="sm">
                {allowedLibraries.length > 1 && (
                  <SegmentedControl
                    value={effectiveScope}
                    onChange={setScopeMode}
                    data={[
                      { label: 'Single library', value: 'single' },
                      { label: 'All libraries', value: 'all' },
                    ]}
                    fullWidth
                  />
                )}

                {effectiveScope === 'single' && (
                  <Select
                    label="Library"
                    placeholder="Select library"
                    data={libraryOptions}
                    value={selectedLibraryId ? String(selectedLibraryId) : null}
                    onChange={(value) => setSelectedLibraryId(value ? Number(value) : null)}
                    searchable
                    nothingFoundMessage="No libraries"
                  />
                )}

                <Group gap="xs">
                  {onStartScan && (
                    <Button
                      size="xs"
                      variant="light"
                      onClick={handleStartQuick}
                      loading={startLoading}
                      disabled={targetLibraries.length === 0}
                    >
                      {quickActionLabel}
                    </Button>
                  )}
                  {onStartFullScan && (
                    <Button
                      size="xs"
                      variant="light"
                      color="orange"
                      onClick={() => setConfirmFullOpen(true)}
                      loading={startLoading}
                      disabled={targetLibraries.length === 0}
                    >
                      {fullActionLabel}
                    </Button>
                  )}
                </Group>

                <Text size="xs" c="dimmed">
                  Quick scan checks new/changed/removed files and backfills missing metadata/artwork. Full scan reprocesses all files and refreshes all metadata/artwork.
                </Text>

                <Group gap="xs">
                  <Badge variant="light" color="blue">
                    Running {scanSummary.running}
                  </Badge>
                  <Badge variant="light" color="gray">
                    Queued {scanSummary.queued}
                  </Badge>
                  <Badge variant="light" color="green">
                    Completed {scanSummary.completed}
                  </Badge>
                  {effectiveScope === 'all' && (
                    <Badge variant="outline" color="indigo">
                      Libraries {scanSummary.activeLibraries}
                    </Badge>
                  )}
                </Group>
              </Stack>
            </Paper>

            {isInitialLoading ? (
              <Group justify="center" py="lg">
                <Text c="dimmed">Loading scans...</Text>
              </Group>
            ) : scans.length === 0 ? (
              <Stack align="center" py="lg" gap={4}>
                <Text c="dimmed">
                  {effectiveScope === 'single' && selectedLibrary
                    ? `No scans recorded yet for ${selectedLibrary.name}.`
                    : 'No scans recorded yet.'}
                </Text>
                {onStartScan && (
                  <Button size="xs" onClick={handleStartQuick} mt="xs">
                    {quickActionLabel}
                  </Button>
                )}
              </Stack>
            ) : (
              <Stack gap="sm">
                {scans.map((scan) => {
                  const status = scan.status || 'pending';
                  const unmatchedPaths = Array.isArray(scan.extra?.unmatched_paths)
                    ? scan.extra.unmatched_paths.filter(Boolean)
                    : [];
                  const errorEntries = Array.isArray(scan.extra?.errors)
                    ? scan.extra.errors.filter(Boolean)
                    : [];
                  const scanLibraryName =
                    libraryNameById.get(scan.library) || `Library ${scan.library}`;

                  return (
                    <Card key={scan.id} withBorder shadow="sm" radius="md">
                      <Stack gap="sm">
                        <Group justify="space-between" align="flex-start">
                          <Stack gap={4} style={{ flex: 1 }}>
                            <Group gap="xs" align="center">
                              <Badge color={statusColor[status] || 'gray'} variant="light">
                                {status}
                              </Badge>
                              <Badge variant="outline" color="indigo">
                                {scanLibraryName}
                              </Badge>
                              <Badge variant="light" color="grape">
                                {getScanTypeLabel(scan.scan_type)}
                              </Badge>
                            </Group>
                            <Text size="sm" fw={600}>
                              {scan.summary || 'Scan'}
                            </Text>
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
                            const isDiscoveryRunningUnknown =
                              key === 'discovery' &&
                              stageStatus === 'running' &&
                              (!stage.total || stage.total <= stage.processed);
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
                                : stageStatus === 'skipped' || isDiscoveryRunningUnknown
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
                                {!isDiscoveryRunningUnknown && (
                                  <Progress
                                    value={percent}
                                    size="sm"
                                    striped={animated}
                                    animated={animated}
                                    color={progressColor}
                                  />
                                )}
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
                          {unmatchedPaths.length > 0 && (
                            <Stack gap={4}>
                              <Text size="xs" fw={600}>
                                Unmatched files
                              </Text>
                              <ScrollArea.Autosize mah={160}>
                                <Stack gap={2}>
                                  {unmatchedPaths.map((path) => (
                                    <Text
                                      key={path}
                                      size="xs"
                                      style={{ fontFamily: 'monospace' }}
                                    >
                                      {path}
                                    </Text>
                                  ))}
                                </Stack>
                              </ScrollArea.Autosize>
                            </Stack>
                          )}
                          {errorEntries.length > 0 && (
                            <Stack gap={4}>
                              <Text size="xs" fw={600} c="red.4">
                                Errors
                              </Text>
                              <ScrollArea.Autosize mah={160}>
                                <Stack gap={6}>
                                  {errorEntries.map((entry, index) => {
                                    const path =
                                      entry && typeof entry === 'object' ? entry.path || '' : '';
                                    const message =
                                      entry && typeof entry === 'object'
                                        ? entry.error || ''
                                        : String(entry);
                                    const key = `${path}-${message}-${index}`;
                                    return (
                                      <Stack key={key} gap={2}>
                                        {path && (
                                          <Text
                                            size="xs"
                                            style={{ fontFamily: 'monospace' }}
                                          >
                                            {path}
                                          </Text>
                                        )}
                                        <Text size="xs" c="red.4">
                                          {message || 'Unknown error'}
                                        </Text>
                                      </Stack>
                                    );
                                  })}
                                </Stack>
                              </ScrollArea.Autosize>
                            </Stack>
                          )}
                        </Stack>
                      </Stack>
                    </Card>
                  );
                })}
              </Stack>
            )}
          </Stack>
        </ScrollArea>
      </Drawer>

      <ConfirmationDialog
        opened={confirmFullOpen}
        onClose={() => setConfirmFullOpen(false)}
        onConfirm={handleConfirmFullScan}
        title="Run full scan"
        message={fullScanConfirmMessage}
        confirmLabel="Queue full scan"
        cancelLabel="Cancel"
        size="md"
        loading={startLoading}
      />
    </>
  );
};

export default LibraryScanDrawer;
