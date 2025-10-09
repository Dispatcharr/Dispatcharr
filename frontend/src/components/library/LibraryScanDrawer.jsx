import React, { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
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
import { Timeline } from '@mantine/core';
import { Ban, Play, RefreshCcw, Trash2, ScanSearch } from 'lucide-react';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';

import useLibraryStore from '../../store/library';

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
  const scans = useLibraryStore((s) => s.scans[libraryId || 'all']) ?? EMPTY_SCAN_LIST;
  const fetchScans = useLibraryStore((s) => s.fetchScans);
  const [loaderHold, setLoaderHold] = useState(false);

  // Fetch once when opened (WebSockets keep it live afterward)
  useEffect(() => {
    if (opened) {
      fetchScans(libraryId);
    }
  }, [opened, libraryId, fetchScans]);

  const handleRefresh = () => fetchScans(libraryId);
  const hasRunningScan = useMemo(
    () => scans.some((scan) => isRunning(scan.status)),
    [scans]
  );
  const hasQueuedScan = useMemo(
    () => scans.some((scan) => isQueued(scan.status)),
    [scans]
  );

  useEffect(() => {
    if (!opened) return undefined;
    if (!hasRunningScan && !hasQueuedScan) return undefined;
    const interval = setInterval(() => {
      void fetchScans(libraryId, { background: true });
    }, hasRunningScan ? 2000 : 5000);
    return () => clearInterval(interval);
  }, [opened, hasRunningScan, hasQueuedScan, libraryId, fetchScans]);

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
          <Tooltip label="Refresh">
            <ActionIcon variant="light" onClick={handleRefresh}>
              <RefreshCcw size={16} />
            </ActionIcon>
          </Tooltip>
        </Group>
      </Group>
    ),
    [onStartScan, onStartFullScan, handleRefresh]
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
          <Timeline active={0} reverseActive bulletSize={18} lineWidth={2}>
            {scans.map((scan) => {
              const status = scan.status || 'pending';
              const total = scan.total_files ?? scan.files ?? 0;
              const processedRaw =
                status === 'completed'
                  ? scan.total_files ?? scan.processed_files ?? scan.processed ?? 0
                  : scan.processed_files ?? scan.processed ?? 0;
              const processed = Math.min(processedRaw || 0, total || 0);
              const percent = total ? Math.min(100, Math.round((processed / total) * 100)) : 0;

              return (
                <Timeline.Item
                  key={scan.id}
                  title={dayjs(scan.created_at).format('MMM D, YYYY HH:mm')}
                  bullet={
                    <Badge color={statusColor[status] || 'gray'} variant="filled">
                      {status}
                    </Badge>
                  }
                >
                  <Stack gap={6} mt="xs">
                    {/* Summary + row actions */}
                    <Group justify="space-between" align="center">
                      <Text size="sm" fw={500}>{scan.summary || 'Scan'}</Text>
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

                    {/* Progress */}
                    {total > 0 && (
                      <Stack gap={2}>
                        <Group justify="space-between">
                          <Text size="xs" fw={500}>
                            {processed} / {total} processed
                          </Text>
                          <Text size="xs" c="dimmed">
                            {percent}%
                          </Text>
                        </Group>
                        <Progress
                          value={percent}
                          size="md"
                          striped
                          animated={isRunning(status)}
                        />
                      </Stack>
                    )}

                    {/* Meta */}
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
                </Timeline.Item>
              );
            })}
          </Timeline>
        )}
      </ScrollArea>
    </Drawer>
  );
};

export default LibraryScanDrawer;
