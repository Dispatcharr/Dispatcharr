import React, { useMemo, useState } from 'react';
import {
  Badge,
  Box,
  Button,
  Group,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { Search } from 'lucide-react';
import { SUBSCRIPTION_EVENTS } from '../constants.js';

// Filter box only earns its keep once there's enough to filter: some
// plugins expose 10+ actions, most expose one or two. No scroll cap here:
// the page itself scrolls once the list is long, rather than boxing the
// list in its own scrollbar.
const SEARCH_THRESHOLD = 6;

const PluginActionRow = ({ action, enabled, runningActionId, handlePluginRun }) => {
  const events = Array.isArray(action?.events) ? action.events : [];
  const running = runningActionId === action.id;
  return (
    <Box
      style={{
        border: '1px solid var(--mantine-color-default-border)',
        borderRadius: 'var(--mantine-radius-sm)',
        padding: 8,
      }}
    >
      <Group justify="space-between" align="flex-start" wrap="wrap" gap="xs">
        <Box style={{ minWidth: 0, flex: '1 1 200px' }}>
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
        </Box>
        {/* Its own flex item (not a fixed-width table cell) so a long
            custom button_label can't get clipped or blow out a column. */}
        <Button
          loading={running}
          disabled={!enabled || running}
          onClick={() => handlePluginRun(action)}
          size="xs"
          variant={action.button_variant || 'filled'}
          color={action.button_color}
          style={{ flexShrink: 0 }}
        >
          {running ? 'Running…' : action.button_label || 'Run'}
        </Button>
      </Group>
    </Box>
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

export default PluginActionList;
