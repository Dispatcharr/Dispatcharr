import React, { useMemo, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Group,
  Modal,
  Progress,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { Eye, EyeOff, Search } from 'lucide-react';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import { SUBSCRIPTION_EVENTS } from '../constants.js';

dayjs.extend(relativeTime);

// Filter box only earns its keep once there's enough to filter: some
// plugins expose 10+ actions, most expose one or two. No scroll cap here:
// the page itself scrolls once the list is long, rather than boxing the
// list in its own scrollbar.
const SEARCH_THRESHOLD = 6;

// Shared box/group shell for one row in the Actions or Running Tasks list -
// both are a bordered box with a left content column and a right-aligned
// action element (a Run button, or a Dismiss button + progress bar).
const PluginListRow = ({ left, right, footer }) => (
  <Box
    style={{
      border: '1px solid var(--mantine-color-default-border)',
      borderRadius: 'var(--mantine-radius-sm)',
      padding: 8,
    }}
  >
    <Group justify="space-between" align="flex-start" wrap="wrap" gap="xs">
      <Box style={{ minWidth: 0, flex: '1 1 200px' }}>{left}</Box>
      {/* Its own flex item (not a fixed-width table cell) so a long
          custom button_label can't get clipped or blow out a column. */}
      {right && <Box style={{ flexShrink: 0 }}>{right}</Box>}
    </Group>
    {footer}
  </Box>
);

const PluginActionRow = ({ action, enabled, runningActionId, handlePluginRun }) => {
  const events = Array.isArray(action?.events) ? action.events : [];
  const running = runningActionId === action.id;
  return (
    <PluginListRow
      left={
        <>
          <Group gap={6} wrap="wrap" align="center">
            <Text size="xs" fw={500}>
              {action.label}
            </Text>
            {events.length > 0 && (
              <Tooltip
                multiline
                label={`Triggers on: ${events.map((e) => SUBSCRIPTION_EVENTS[e] || e).join(', ')}`}
              >
                <Badge
                  size="xs"
                  variant="light"
                  color="green"
                  style={{ cursor: 'default' }}
                >
                  {events.length} trigger{events.length > 1 ? 's' : ''}
                </Badge>
              </Tooltip>
            )}
          </Group>
          {/* Full text, wraps rather than truncating; these can be long
              and cutting them off hides the point of having one. */}
          {action.description && (
            <Text size="xs" c="dimmed" style={{ whiteSpace: 'normal' }}>
              {action.description}
            </Text>
          )}
        </>
      }
      right={
        <Button
          loading={running}
          disabled={!enabled || running}
          onClick={() => handlePluginRun(action)}
          size="xs"
          variant={action.button_variant || 'filled'}
          color={action.button_color}
        >
          {running ? 'Running…' : action.button_label || 'Run'}
        </Button>
      }
    />
  );
};

export const PluginActionList = ({
  plugin,
  enabled,
  runningActionId,
  handlePluginRun,
}) => {
  const [query, setQuery] = useState('');
  const actions = plugin.actions || [];

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return plugin.actions || [];
    return (plugin.actions || []).filter(
      (a) =>
        a.label?.toLowerCase().includes(q) ||
        a.description?.toLowerCase().includes(q)
    );
  }, [plugin.actions, query]);

  const rows = (
    <Stack gap="xs">
      {filtered.map((action) => (
        <PluginActionRow
          key={action.id}
          action={action}
          enabled={enabled}
          runningActionId={runningActionId}
          handlePluginRun={handlePluginRun}
        />
      ))}
      {filtered.length === 0 && (
        <Text size="xs" c="dimmed">
          No actions match your filter.
        </Text>
      )}
    </Stack>
  );

  return (
    <>
      {actions.length > SEARCH_THRESHOLD && (
        <TextInput
          placeholder="Filter actions…"
          leftSection={<Search size={14} />}
          value={query}
          onChange={(e) => setQuery(e.currentTarget.value)}
          size="xs"
          mb="xs"
        />
      )}
      {rows}
    </>
  );
};

export const PluginActionStatus = ({ running, lastResult }) => {
  return (
    <>
      {running && (
        <Text size="xs" c="dimmed">
          Running action… please wait
        </Text>
      )}
      {!running && lastResult?.file && (
        <Text size="xs" c="dimmed">
          Output: {lastResult.file}
        </Text>
      )}
      {!running && lastResult?.error && (
        <Text size="xs" c="red">
          Error: {String(lastResult.error)}
        </Text>
      )}
    </>
  );
};

const TASK_STATUS_COLOR = { running: 'blue', ok: 'green', error: 'red' };

// Relative for anything recent, absolute HH:mm beyond a day (a bare "3d ago"
// on a stale row isn't much more useful than the badge already showing it's
// done), hover always shows the full local date/time via the tooltip.
const formatRelativeOrAbsolute = (ms) => {
  const d = dayjs(ms);
  const diffHours = dayjs().diff(d, 'hour');
  return diffHours < 24 ? d.fromNow() : d.format('MMM D, HH:mm');
};

const PluginTaskTimestamp = ({ label, ms }) => {
  if (!ms) return null;
  const d = dayjs(ms);
  return (
    <Tooltip label={d.format('YYYY-MM-DD HH:mm:ss')}>
      <Text size="xs" c="dimmed" style={{ cursor: 'default' }}>
        {label} {formatRelativeOrAbsolute(ms)}
      </Text>
    </Tooltip>
  );
};

// One individual run, used both inline (a group with a single run) and as
// a row inside PluginTaskGroupModal (a group with more than one run).
const PluginTaskRunRow = ({ taskId, task, onDismiss }) => {
  const isDone = task.status !== 'running';
  return (
    <PluginListRow
      left={
        <>
          <Group gap={6} wrap="wrap" align="center">
            <Text size="xs" fw={500}>{task.actionLabel}</Text>
            <Badge size="xs" variant="light" color={TASK_STATUS_COLOR[task.status] || 'gray'}>
              {task.status}
            </Badge>
          </Group>
          <Group gap={10} wrap="wrap">
            <PluginTaskTimestamp label="Started" ms={task.startedAt} />
            {isDone && <PluginTaskTimestamp label="Finished" ms={task.updatedAt} />}
          </Group>
          {task.message && (
            <Text size="xs" c="dimmed" style={{ whiteSpace: 'normal' }}>
              {task.message}
            </Text>
          )}
          {task.status === 'error' && task.error && (
            <Text size="xs" c="red" style={{ whiteSpace: 'normal' }}>
              {String(task.error)}
            </Text>
          )}
        </>
      }
      right={
        isDone && !task.dismissed && (
          <Button size="xs" variant="subtle" color="gray" onClick={() => onDismiss(taskId)}>
            Dismiss
          </Button>
        )
      }
      footer={
        !isDone && (
          <Progress
            mt={6}
            size="xs"
            value={typeof task.percent === 'number' ? task.percent : 100}
            animated={typeof task.percent !== 'number'}
            color="blue"
          />
        )
      }
    />
  );
};

// Groups tasks by action (actionId when known, falling back to actionLabel)
// so concurrent/historical runs of the same action stack into one row
// instead of piling up as separate unlabeled rows. Newest run first. Groups
// where every run has been dismissed are still returned (not dropped) so
// history stays reachable via the "View" modal rather than disappearing.
const groupPluginTasks = (tasks) => {
  const groups = {};
  for (const [taskId, task] of Object.entries(tasks || {})) {
    const groupKey = task.actionId ?? task.actionLabel;
    if (!groups[groupKey]) {
      groups[groupKey] = { groupKey, actionLabel: task.actionLabel, runs: [] };
    }
    groups[groupKey].runs.push({ taskId, ...task });
  }
  return Object.values(groups)
    .map((g) => {
      const runs = [...g.runs].sort((a, b) => (b.startedAt ?? 0) - (a.startedAt ?? 0));
      return {
        ...g,
        runs,
        latest: runs[0],
        runningCount: runs.filter((r) => r.status === 'running').length,
        visibleRuns: runs.filter((r) => !r.dismissed),
      };
    })
    .sort((a, b) => (b.latest?.startedAt ?? 0) - (a.latest?.startedAt ?? 0));
};

const PluginTaskGroupModal = ({ group, opened, onClose, onDismiss }) => {
  const dismissedCount = group.runs.length - group.visibleRuns.length;
  // Nothing but history to show (e.g. a single dismissed run reopened from
  // its "View history" button); default to showing it rather than an
  // empty state the user has to click through.
  const [showDismissed, setShowDismissed] = useState(group.visibleRuns.length === 0);
  const runsToShow = showDismissed ? group.runs : group.visibleRuns;
  return (
    <Modal opened={opened} onClose={onClose} title={`${group.actionLabel} — ${group.runs.length} run${group.runs.length > 1 ? 's' : ''}`} size="lg">
      <Stack gap="xs">
        {dismissedCount > 0 && (
          <Group justify="flex-end">
            <ActionIcon
              size="sm"
              variant="subtle"
              color="gray"
              onClick={() => setShowDismissed((v) => !v)}
              title={showDismissed ? 'Hide dismissed runs' : `Show ${dismissedCount} dismissed run${dismissedCount > 1 ? 's' : ''}`}
            >
              {showDismissed ? <EyeOff size={14} /> : <Eye size={14} />}
            </ActionIcon>
          </Group>
        )}
        {runsToShow.map((run) => (
          <PluginTaskRunRow key={run.taskId} taskId={run.taskId} task={run} onDismiss={onDismiss} />
        ))}
        {runsToShow.length === 0 && (
          <Text size="xs" c="dimmed">No runs to show.</Text>
        )}
      </Stack>
    </Modal>
  );
};

const PluginTaskGroupRow = ({ group, onDismiss }) => {
  const [modalOpened, setModalOpened] = useState(false);

  // A single non-dismissed run: render exactly as before, no extra click to
  // reach it. Once that lone run is dismissed (or a second run exists),
  // fall through to the stacked row so history stays reachable.
  if (group.runs.length === 1 && !group.latest.dismissed) {
    return <PluginTaskRunRow taskId={group.latest.taskId} task={group.latest} onDismiss={onDismiss} />;
  }

  const { latest, runningCount, runs, visibleRuns } = group;
  const isHistoryOnly = visibleRuns.length === 0;
  return (
    <>
      <PluginListRow
        left={
          <>
            <Group gap={6} wrap="wrap" align="center">
              <Text size="xs" fw={500} c={isHistoryOnly ? 'dimmed' : undefined}>{group.actionLabel}</Text>
              {runningCount > 0 ? (
                <Badge size="xs" variant="light" color="blue">Running ({runningCount})</Badge>
              ) : (
                <Badge size="xs" variant="light" color={isHistoryOnly ? 'gray' : (TASK_STATUS_COLOR[latest.status] || 'gray')}>
                  {isHistoryOnly ? 'dismissed' : latest.status}
                </Badge>
              )}
              {runs.length > 1 && (
                <Badge size="xs" variant="outline" color="gray">{runs.length} runs</Badge>
              )}
            </Group>
            <Group gap={10} wrap="wrap">
              <PluginTaskTimestamp label="Latest started" ms={latest.startedAt} />
              {latest.status !== 'running' && <PluginTaskTimestamp label="Finished" ms={latest.updatedAt} />}
            </Group>
          </>
        }
        right={
          <Button size="xs" variant="light" color={isHistoryOnly ? 'gray' : undefined} onClick={() => setModalOpened(true)}>
            {isHistoryOnly ? 'View history' : `View ${runs.length} runs`}
          </Button>
        }
      />
      <PluginTaskGroupModal
        group={group}
        opened={modalOpened}
        onClose={() => setModalOpened(false)}
        onDismiss={onDismiss}
      />
    </>
  );
};

export const PluginTaskList = ({ tasks, onDismiss }) => {
  const groups = useMemo(() => groupPluginTasks(tasks), [tasks]);
  if (groups.length === 0) return null;
  return (
    <Stack gap="xs">
      {groups.map((group) => (
        <PluginTaskGroupRow key={group.groupKey} group={group} onDismiss={onDismiss} />
      ))}
    </Stack>
  );
};

export default PluginActionList;
