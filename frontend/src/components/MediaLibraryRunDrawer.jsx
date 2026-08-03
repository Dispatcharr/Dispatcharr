import React, { useCallback, useEffect, useMemo, useState } from 'react';
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
  Tooltip,
} from '@mantine/core';
import { Ban, RefreshCw, ScanSearch, Trash2 } from 'lucide-react';

import API from '../api';

const stageOrder = [
  ['discovery', 'Discovery', 'blue'],
  ['import', 'Import', 'green'],
  ['cleanup', 'Cleanup', 'orange'],
];

const activeStatuses = new Set(['pending', 'queued', 'running']);
const finishedStatuses = new Set(['completed', 'failed', 'cancelled']);

const statusColor = (status) =>
  status === 'completed'
    ? 'green'
    : status === 'failed'
      ? 'red'
      : status === 'running'
        ? 'blue'
        : status === 'cancelled'
          ? 'orange'
          : 'gray';

const stagePercent = (stage) => {
  if (stage?.status === 'completed') return 100;
  const processed = Math.max(0, Number(stage?.processed) || 0);
  const total = Math.max(0, Number(stage?.total) || 0);
  if (!total) return 0;
  return Math.min(100, Math.round((processed / total) * 100));
};

const formatDate = (value) =>
  value ? new Date(value).toLocaleString() : 'Not available';

export default function MediaLibraryRunDrawer({
  opened,
  onClose,
  source,
  onRun,
  onChanged,
}) {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const [purging, setPurging] = useState(false);

  const sourceId = source?.id;

  const fetchRuns = useCallback(
    async ({ quiet = false } = {}) => {
      if (!sourceId) {
        setRuns([]);
        return;
      }
      if (!quiet) setLoading(true);
      try {
        setRuns(await API.getMediaLibraryImportRuns(sourceId));
      } finally {
        if (!quiet) setLoading(false);
      }
    },
    [sourceId]
  );

  useEffect(() => {
    if (opened) fetchRuns();
  }, [fetchRuns, opened]);

  useEffect(() => {
    if (!opened || !sourceId) return undefined;
    const handleUpdate = (event) => {
      const incoming = event.detail;
      const incomingSource = incoming?.source ?? incoming?.integration;
      if (!incoming?.id || Number(incomingSource) !== Number(sourceId)) return;
      setRuns((current) => {
        const next = [...current];
        const index = next.findIndex((run) => run.id === incoming.id);
        if (index === -1) next.unshift(incoming);
        else next[index] = incoming;
        return next;
      });
      onChanged?.();
    };
    window.addEventListener('media_library_import_updated', handleUpdate);
    return () =>
      window.removeEventListener('media_library_import_updated', handleUpdate);
  }, [onChanged, opened, sourceId]);

  const hasActive = useMemo(
    () => runs.some((run) => activeStatuses.has(run.status)),
    [runs]
  );
  const hasFinished = useMemo(
    () => runs.some((run) => finishedStatuses.has(run.status)),
    [runs]
  );

  useEffect(() => {
    if (!opened || !sourceId) return undefined;
    const timer = window.setInterval(
      () => fetchRuns({ quiet: true }),
      hasActive ? 2500 : 8000
    );
    return () => window.clearInterval(timer);
  }, [fetchRuns, hasActive, opened, sourceId]);

  const cancel = async (run) => {
    setBusyId(run.id);
    try {
      const updated = await API.cancelMediaLibraryImportRun(run.id);
      setRuns((current) =>
        current.map((item) => (item.id === run.id ? updated : item))
      );
      onChanged?.();
    } finally {
      setBusyId(null);
    }
  };

  const removeQueued = async (run) => {
    setBusyId(run.id);
    try {
      await API.deleteMediaLibraryImportRun(run.id);
      setRuns((current) => current.filter((item) => item.id !== run.id));
    } finally {
      setBusyId(null);
    }
  };

  const purge = async () => {
    setPurging(true);
    try {
      await API.purgeMediaLibraryImportRuns(sourceId);
      await fetchRuns({ quiet: true });
    } finally {
      setPurging(false);
    }
  };

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      position="right"
      size="lg"
      title={
        <Group gap="xs">
          <ScanSearch size={18} />
          <Text fw={700}>{source?.name || 'Media source'} import activity</Text>
        </Group>
      }
    >
      <Stack h="100%">
        <Group justify="space-between">
          <Group gap="xs">
            <Button
              size="xs"
              onClick={async () => {
                await onRun?.(source);
                await fetchRuns({ quiet: true });
              }}
              disabled={hasActive}
            >
              Import now
            </Button>
            {hasFinished && (
              <Button
                size="xs"
                variant="light"
                onClick={purge}
                loading={purging}
              >
                Clear finished
              </Button>
            )}
          </Group>
          <Tooltip label="Refresh">
            <ActionIcon variant="light" onClick={() => fetchRuns()}>
              <RefreshCw size={16} />
            </ActionIcon>
          </Tooltip>
        </Group>

        <Text size="xs" c="dimmed">
          Discovery validates the selected libraries, import creates or updates
          normalized VOD content, and cleanup removes stale relations only after
          an authoritative scan.
        </Text>

        <ScrollArea style={{ flex: 1 }}>
          <Stack gap="sm">
            {!loading && runs.length === 0 && (
              <Text c="dimmed" ta="center" py="xl">
                No imports have been recorded for this source.
              </Text>
            )}
            {runs.map((run) => (
              <Card key={run.id} withBorder>
                <Stack gap="sm">
                  <Group justify="space-between" align="flex-start">
                    <div>
                      <Group gap="xs">
                        <Badge color={statusColor(run.status)}>
                          {run.status}
                        </Badge>
                        <Text fw={600} size="sm">
                          {run.summary || 'Media import'}
                        </Text>
                      </Group>
                      <Text size="xs" c="dimmed" mt={4}>
                        Queued {formatDate(run.created_at)}
                      </Text>
                    </div>
                    {run.status === 'running' ? (
                      <Tooltip label="Cancel import">
                        <ActionIcon
                          color="orange"
                          variant="light"
                          loading={busyId === run.id}
                          onClick={() => cancel(run)}
                        >
                          <Ban size={16} />
                        </ActionIcon>
                      </Tooltip>
                    ) : ['pending', 'queued'].includes(run.status) ? (
                      <Tooltip label="Remove queued import">
                        <ActionIcon
                          color="red"
                          variant="light"
                          loading={busyId === run.id}
                          onClick={() => removeQueued(run)}
                        >
                          <Trash2 size={16} />
                        </ActionIcon>
                      </Tooltip>
                    ) : null}
                  </Group>

                  <Divider />

                  {stageOrder.map(([key, label, color]) => {
                    const stage = run.stages?.[key] || {};
                    const value = stagePercent(stage);
                    return (
                      <Stack key={key} gap={4}>
                        <Group justify="space-between">
                          <Text size="xs" fw={600}>
                            {label}
                          </Text>
                          <Text size="xs" c="dimmed">
                            {stage.status || 'pending'} ·{' '}
                            {Number(stage.processed) || 0}
                            {Number(stage.total) > 0
                              ? ` / ${Number(stage.total)}`
                              : ''}
                          </Text>
                        </Group>
                        <Progress
                          value={value}
                          color={color}
                          size="sm"
                          striped={stage.status === 'running'}
                          animated={stage.status === 'running'}
                        />
                      </Stack>
                    );
                  })}

                  <Divider />

                  <Group gap="xs">
                    <Badge variant="light">
                      Processed {run.processed_items || 0}
                    </Badge>
                    <Badge variant="light" color="green">
                      Created {run.created_items || 0}
                    </Badge>
                    <Badge variant="light" color="blue">
                      Updated {run.updated_items || 0}
                    </Badge>
                    <Badge variant="light" color="orange">
                      Removed {run.removed_items || 0}
                    </Badge>
                    <Badge variant="light" color="yellow">
                      Skipped {run.skipped_items || 0}
                    </Badge>
                    <Badge
                      variant="light"
                      color={run.ambiguous_items ? 'red' : 'gray'}
                    >
                      Ambiguous {run.ambiguous_items || 0}
                    </Badge>
                  </Group>

                  {Object.keys(run.scope_results || {}).length > 0 && (
                    <Stack gap={3}>
                      <Text size="xs" fw={600}>
                        Libraries and locations
                      </Text>
                      {Object.entries(run.scope_results).map(([id, scope]) => (
                        <Group key={id} justify="space-between">
                          <Text size="xs">{scope.name || id}</Text>
                          <Badge
                            size="xs"
                            color={
                              scope.authoritative
                                ? 'green'
                                : statusColor(scope.status)
                            }
                          >
                            {scope.authoritative
                              ? 'authoritative'
                              : scope.status || 'pending'}
                          </Badge>
                        </Group>
                      ))}
                    </Stack>
                  )}

                  {run.message && (
                    <Text size="xs" c={run.error_count ? 'red' : 'dimmed'}>
                      {run.message}
                    </Text>
                  )}
                  <Text size="xs" c="dimmed">
                    Started {formatDate(run.started_at)} · Finished{' '}
                    {formatDate(run.finished_at)}
                  </Text>
                </Stack>
              </Card>
            ))}
          </Stack>
        </ScrollArea>
      </Stack>
    </Drawer>
  );
}
