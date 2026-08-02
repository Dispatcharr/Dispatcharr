import React, { useMemo, useState } from 'react';
import {
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
import { Search } from 'lucide-react';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import { SUBSCRIPTION_EVENTS } from '../constants.js';

dayjs.extend(relativeTime);

// Filter box only earns its keep once there's enough to filter: some
// plugins expose 10+ actions, most expose one or two. No scroll cap here:
// the page itself scrolls once the list is long, rather than boxing the
// list in its own scrollbar.
const SEARCH_THRESHOLD = 6;

// Shared box/group shell for one row in the Actions or Tasks list: both are
// a bordered box with a left content column and a right-aligned action
// element (a Run button, or a status/progress footer).
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

// A single compact "Started 2m ago" / "Finished 1m ago" line, whichever
// moment is most relevant right now, rather than showing both start and
// finish side by side, which reads as noise once a run is done and was
// prone to wrapping mid-phrase in the narrow group row. Hover for the exact
// start (and finish, once done) timestamps.
const PluginTaskTimestamp = ({ task }) => {
  const isDone = task.status !== 'running';
  const ms = isDone ? (task.updatedAt ?? task.startedAt) : task.startedAt;
  if (!ms) return null;
  const tooltipLines = [];
  if (task.startedAt) tooltipLines.push(`Started: ${dayjs(task.startedAt).format('YYYY-MM-DD HH:mm:ss')}`);
  if (isDone && task.updatedAt) tooltipLines.push(`Finished: ${dayjs(task.updatedAt).format('YYYY-MM-DD HH:mm:ss')}`);
  return (
    <Tooltip label={tooltipLines.join('\n')} multiline>
      <Text size="xs" c="dimmed" style={{ cursor: 'default', whiteSpace: 'nowrap' }}>
        {isDone ? 'Finished' : 'Started'} {formatRelativeOrAbsolute(ms)}
      </Text>
    </Tooltip>
  );
};

// One individual run, shown inside PluginTaskGroupModal's history list.
const PluginTaskRunRow = ({ task }) => {
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
          <PluginTaskTimestamp task={task} />
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
// instead of piling up as separate unlabeled rows. Newest run first.
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
      const runningRuns = runs.filter((r) => r.status === 'running');
      return {
        ...g,
        runs,
        latest: runs[0],
        runningCount: runningRuns.length,
        runningRun: runningRuns[0],
      };
    })
    .sort((a, b) => (b.latest?.startedAt ?? 0) - (a.latest?.startedAt ?? 0));
};

const PluginTaskGroupModal = ({ group, opened, onClose }) => (
  <Modal opened={opened} onClose={onClose} title={`${group.actionLabel} (${group.runs.length} run${group.runs.length > 1 ? 's' : ''})`} size="lg">
    <Stack gap="xs">
      {group.runs.map((run) => (
        <PluginTaskRunRow key={run.taskId} task={run} />
      ))}
    </Stack>
  </Modal>
);

// One row per action, regardless of run count: status/timestamp at a
// glance, full history (every run, its own progress/timestamps/message)
// a click away behind the single "View history" button.
const PluginTaskGroupRow = ({ group }) => {
  const [modalOpened, setModalOpened] = useState(false);
  const { latest, runningCount, runningRun } = group;
  return (
    <>
      <PluginListRow
        left={
          <>
            <Group gap={6} wrap="wrap" align="center">
              <Text size="xs" fw={500}>{group.actionLabel}</Text>
              {runningCount > 0 ? (
                <Badge size="xs" variant="light" color="blue">Running ({runningCount})</Badge>
              ) : (
                <Badge size="xs" variant="light" color={TASK_STATUS_COLOR[latest.status] || 'gray'}>
                  {latest.status}
                </Badge>
              )}
            </Group>
            <PluginTaskTimestamp task={latest} />
          </>
        }
        right={
          <Button size="xs" variant="light" color="gray" onClick={() => setModalOpened(true)}>
            View history
          </Button>
        }
        footer={
          runningRun && (
            <Progress
              mt={6}
              size="xs"
              value={typeof runningRun.percent === 'number' ? runningRun.percent : 100}
              animated={typeof runningRun.percent !== 'number'}
              color="blue"
            />
          )
        }
      />
      <PluginTaskGroupModal
        group={group}
        opened={modalOpened}
        onClose={() => setModalOpened(false)}
      />
    </>
  );
};

export const PluginTaskList = ({ tasks }) => {
  const groups = useMemo(() => groupPluginTasks(tasks), [tasks]);
  if (groups.length === 0) return null;
  return (
    <Stack gap="xs">
      {groups.map((group) => (
        <PluginTaskGroupRow key={group.groupKey} group={group} />
      ))}
    </Stack>
  );
};

export default PluginActionList;
