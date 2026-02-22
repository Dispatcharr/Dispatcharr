import React, { useCallback, useEffect, useMemo, useState } from 'react';
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
  Stack,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Ban, RefreshCcw, ScanSearch, Trash2 } from 'lucide-react';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';

import API from '../api';

dayjs.extend(relativeTime);

const statusColorMap = {
  pending: 'gray',
  queued: 'gray',
  running: 'blue',
  completed: 'green',
  failed: 'red',
  cancelled: 'yellow',
};

const isRunning = (status) => status === 'running';
const isQueued = (status) => status === 'pending' || status === 'queued';

const stageStatusLabel = {
  pending: 'Waiting',
  running: 'In progress',
  completed: 'Completed',
  skipped: 'Skipped',
  failed: 'Failed',
  cancelled: 'Cancelled',
};

const stageOrder = [
  { key: 'discovery', label: 'Discovery' },
  { key: 'import', label: 'Import' },
  { key: 'cleanup', label: 'Cleanup' },
];

const stageColorMap = {
  discovery: 'blue',
  import: 'green',
  cleanup: 'orange',
};

const EMPTY_STAGE = {
  status: 'pending',
  processed: 0,
  total: 0,
};

function getStagePercent(stage) {
  if (!stage) return 0;
  const status = String(stage.status || 'pending');
  const processed = Math.max(0, Number(stage.processed) || 0);
  let total = Math.max(0, Number(stage.total) || 0);

  if (!total || total <= processed) {
    if (status === 'completed') {
      total = processed || 1;
    } else {
      total = processed + 1;
    }
  }

  if (!total) return 0;
  return Math.min(100, Math.round((processed / total) * 100));
}

function formatStageCount(stage) {
  if (!stage) return 'Waiting...';
  const status = String(stage.status || 'pending');
  const processed = Math.max(0, Number(stage.processed) || 0);
  const total = Math.max(0, Number(stage.total) || 0);

  if (status === 'skipped') return 'Not required';
  if (status === 'failed') return 'Failed';
  if (status === 'cancelled') return 'Cancelled';
  if (status === 'completed' && processed === 0 && total === 0) return 'Done';

  if (total > 0) {
    return `${processed} / ${total}`;
  }
  if (status === 'running' && processed === 0) {
    return 'Working...';
  }
  return processed > 0 ? String(processed) : 'Waiting...';
}

function hasFinishedStatus(status) {
  return ['completed', 'failed', 'cancelled'].includes(status);
}

export default function MediaServerSyncDrawer({
  opened,
  onClose,
  integration = null,
  onRefreshIntegrations = async () => {},
  onRunSync = null,
}) {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(false);
  const [purging, setPurging] = useState(false);
  const [startingSync, setStartingSync] = useState(false);
  const [actionLoadingById, setActionLoadingById] = useState({});

  const integrationId = integration?.id || null;

  const setActionLoading = (runId, value) => {
    setActionLoadingById((prev) => ({ ...prev, [runId]: value }));
  };

  const fetchRuns = useCallback(
    async ({ background = false } = {}) => {
      if (!integrationId) {
        setRuns([]);
        return;
      }
      if (!background) {
        setLoading(true);
      }
      try {
        const response = await API.getMediaServerSyncRuns(integrationId);
        setRuns(Array.isArray(response) ? response : []);
      } catch (error) {
        if (!background) {
          console.error('Failed to load media server scans', error);
        }
      } finally {
        if (!background) {
          setLoading(false);
        }
      }
    },
    [integrationId]
  );

  useEffect(() => {
    if (!opened) return;
    void fetchRuns({ background: false });
  }, [opened, fetchRuns]);

  useEffect(() => {
    if (!opened || !integrationId) return undefined;

    const handleSyncUpdate = (event) => {
      const incoming = event?.detail;
      if (!incoming?.id || incoming.integration !== integrationId) return;
      setRuns((prev) => {
        const list = Array.isArray(prev) ? [...prev] : [];
        const index = list.findIndex((entry) => entry.id === incoming.id);
        if (index >= 0) {
          list[index] = incoming;
        } else {
          list.unshift(incoming);
        }
        return list;
      });
    };

    window.addEventListener('media_server_sync_updated', handleSyncUpdate);
    return () => {
      window.removeEventListener('media_server_sync_updated', handleSyncUpdate);
    };
  }, [opened, integrationId]);

  const hasActiveRuns = useMemo(
    () => runs.some((run) => ['pending', 'queued', 'running'].includes(run.status)),
    [runs]
  );

  useEffect(() => {
    if (!opened || !integrationId) return undefined;

    let cancelled = false;
    let timer = null;

    const loop = async () => {
      if (cancelled) return;
      await fetchRuns({ background: true });
      if (cancelled) return;

      const delay = hasActiveRuns ? 2000 : 8000;
      timer = window.setTimeout(loop, delay);
    };

    timer = window.setTimeout(loop, 1500);

    return () => {
      cancelled = true;
      if (timer) {
        window.clearTimeout(timer);
      }
    };
  }, [opened, integrationId, fetchRuns, hasActiveRuns]);

  const runSummary = useMemo(() => {
    let running = 0;
    let queued = 0;
    let completed = 0;
    runs.forEach((run) => {
      if (isRunning(run.status)) running += 1;
      else if (isQueued(run.status)) queued += 1;
      else if (run.status === 'completed') completed += 1;
    });
    return { running, queued, completed };
  }, [runs]);

  const hasFinishedRuns = useMemo(
    () => runs.some((run) => hasFinishedStatus(run.status)),
    [runs]
  );

  const handleCancel = useCallback(
    async (runId) => {
      setActionLoading(runId, true);
      try {
        const updated = await API.cancelMediaServerSyncRun(runId);
        setRuns((prev) =>
          prev.map((entry) => (entry.id === runId ? updated : entry))
        );
        await onRefreshIntegrations();
      } catch (error) {
        console.error('Failed to cancel media server scan', error);
      } finally {
        setActionLoading(runId, false);
      }
    },
    [onRefreshIntegrations]
  );

  const handleDeleteQueued = useCallback(async (runId) => {
    setActionLoading(runId, true);
    try {
      await API.deleteMediaServerSyncRun(runId);
      setRuns((prev) => prev.filter((entry) => entry.id !== runId));
    } catch (error) {
      console.error('Failed to remove queued media server scan', error);
    } finally {
      setActionLoading(runId, false);
    }
  }, []);

  const handleClearFinished = useCallback(async () => {
    if (!integrationId || !hasFinishedRuns) return;
    setPurging(true);
    try {
      await API.purgeMediaServerSyncRuns(integrationId);
      await fetchRuns({ background: true });
    } catch (error) {
      console.error('Failed to clear finished media server scans', error);
    } finally {
      setPurging(false);
    }
  }, [integrationId, hasFinishedRuns, fetchRuns]);

  const handleStartSync = useCallback(async () => {
    if (!integration || !onRunSync) return;
    setStartingSync(true);
    try {
      await onRunSync(integration, { suppressRefresh: true });
      await fetchRuns({ background: true });
      await onRefreshIntegrations();
    } catch (error) {
      console.error('Failed to start media server sync', error);
      notifications.show({
        title: 'Unable to start sync',
        message: 'Check integration settings and try again.',
        color: 'red',
      });
    } finally {
      setStartingSync(false);
    }
  }, [integration, onRunSync, fetchRuns, onRefreshIntegrations]);

  const handleRefresh = useCallback(async () => {
    await fetchRuns({ background: false });
  }, [fetchRuns]);

  const header = (
    <Group justify="space-between" align="center" mb="sm">
      <Group gap="xs" align="center">
        <ScanSearch size={18} />
        <Title order={5} style={{ lineHeight: 1 }}>
          {integration?.name ? `${integration.name} scan status` : 'Scan status'}
        </Title>
      </Group>

      <Group gap="xs">
        {hasFinishedRuns ? (
          <Button
            variant="light"
            size="xs"
            onClick={handleClearFinished}
            loading={purging}
          >
            Clear finished
          </Button>
        ) : null}
        <Tooltip label="Refresh">
          <ActionIcon variant="light" onClick={handleRefresh}>
            <RefreshCcw size={16} />
          </ActionIcon>
        </Tooltip>
      </Group>
    </Group>
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
        <Stack gap="sm" py="xs">
          <Paper withBorder radius="md" p="sm">
            <Stack gap="sm">
              <Group gap="xs">
                <Badge variant="light" color="blue">
                  Running {runSummary.running}
                </Badge>
                <Badge variant="light" color="gray">
                  Queued {runSummary.queued}
                </Badge>
                <Badge variant="light" color="green">
                  Completed {runSummary.completed}
                </Badge>
              </Group>

              {onRunSync ? (
                <Button
                  size="xs"
                  variant="light"
                  onClick={handleStartSync}
                  loading={startingSync}
                >
                  Start sync
                </Button>
              ) : null}

              <Text size="xs" c="dimmed">
                Discovery identifies source libraries, import updates movies/series/episodes, and cleanup removes stale VOD relations.
              </Text>
            </Stack>
          </Paper>

          {loading && runs.length === 0 ? (
            <Group justify="center" py="lg">
              <Text c="dimmed">Loading scans...</Text>
            </Group>
          ) : runs.length === 0 ? (
            <Stack align="center" py="lg" gap={4}>
              <Text c="dimmed">No scans recorded yet.</Text>
              {onRunSync ? (
                <Button size="xs" onClick={handleStartSync} loading={startingSync}>
                  Start first sync
                </Button>
              ) : null}
            </Stack>
          ) : (
            <Stack gap="sm">
              {runs.map((run) => {
                const status = run.status || 'queued';
                const busy = !!actionLoadingById[run.id];

                return (
                  <Card key={run.id} withBorder shadow="sm" radius="md">
                    <Stack gap="sm">
                      <Group justify="space-between" align="flex-start">
                        <Stack gap={4} style={{ flex: 1 }}>
                          <Group gap="xs" align="center">
                            <Badge
                              color={statusColorMap[status] || 'gray'}
                              variant="light"
                            >
                              {status}
                            </Badge>
                          </Group>
                          <Text size="sm" fw={600}>
                            {run.summary || 'Scan'}
                          </Text>
                          <Text size="xs" c="dimmed">
                            {dayjs(run.created_at).format('MMM D, YYYY HH:mm')}
                          </Text>
                        </Stack>
                        <Group gap="xs">
                          {isRunning(status) ? (
                            <Tooltip label="Cancel running scan">
                              <ActionIcon
                                color="yellow"
                                variant="light"
                                onClick={() => handleCancel(run.id)}
                                disabled={busy}
                              >
                                <Ban size={16} />
                              </ActionIcon>
                            </Tooltip>
                          ) : null}
                          {isQueued(status) ? (
                            <Tooltip label="Remove from queue">
                              <ActionIcon
                                color="red"
                                variant="light"
                                onClick={() => handleDeleteQueued(run.id)}
                                disabled={busy}
                              >
                                <Trash2 size={16} />
                              </ActionIcon>
                            </Tooltip>
                          ) : null}
                        </Group>
                      </Group>

                      <Divider />

                      <Stack gap="sm">
                        {stageOrder.map(({ key, label }) => {
                          const stage = run.stages?.[key] || EMPTY_STAGE;
                          const stageStatus = stage.status || 'pending';
                          const percent = getStagePercent(stage);
                          const color = stageColorMap[key] || 'gray';
                          const animated = stageStatus === 'running';
                          const hideProgress =
                            stageStatus === 'skipped' ||
                            stageStatus === 'failed' ||
                            stageStatus === 'cancelled';
                          const percentLabel =
                            stageStatus === 'completed'
                              ? '100%'
                              : hideProgress
                                ? null
                                : `${percent}%`;

                          return (
                            <Stack gap={4} key={`${run.id}-${key}`}>
                              <Group justify="space-between" align="center">
                                <Text size="xs" fw={500}>
                                  {label}
                                </Text>
                                <Badge
                                  color={
                                    stageStatus === 'running' || stageStatus === 'completed'
                                      ? color
                                      : stageStatus === 'failed'
                                        ? 'red'
                                        : stageStatus === 'cancelled'
                                          ? 'yellow'
                                          : 'gray'
                                  }
                                  variant="light"
                                  size="xs"
                                >
                                  {stageStatusLabel[stageStatus] || stageStatus}
                                </Badge>
                              </Group>
                              <Group justify="space-between" align="center">
                                <Text size="xs" c="dimmed">
                                  {formatStageCount(stage)}
                                </Text>
                                {percentLabel ? (
                                  <Text size="xs" c="dimmed">
                                    {percentLabel}
                                  </Text>
                                ) : null}
                              </Group>
                              {!hideProgress ? (
                                <Progress
                                  value={percent}
                                  size="sm"
                                  striped={animated}
                                  animated={animated}
                                  color={color}
                                />
                              ) : null}
                            </Stack>
                          );
                        })}
                      </Stack>

                      <Divider />

                      <Stack gap={4}>
                        <Text size="xs" c="dimmed">
                          Started {run.started_at ? dayjs(run.started_at).fromNow() : 'n/a'} ·
                          Finished {run.finished_at ? ` ${dayjs(run.finished_at).fromNow()}` : ' n/a'}
                        </Text>
                        <Text size="xs" c="dimmed">
                          Processed {run.processed_items ?? 0} · Created {run.created_items ?? 0} ·
                          Updated {run.updated_items ?? 0} · Removed {run.removed_items ?? 0} ·
                          Skipped {run.skipped_items ?? 0}
                        </Text>
                        {(run.error_count || 0) > 0 ? (
                          <Text size="xs" c="red">
                            Errors: {run.error_count}
                          </Text>
                        ) : null}
                        {run.message ? (
                          <Text size="xs" c="dimmed" style={{ whiteSpace: 'pre-wrap' }}>
                            {run.message}
                          </Text>
                        ) : null}
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
  );
}
