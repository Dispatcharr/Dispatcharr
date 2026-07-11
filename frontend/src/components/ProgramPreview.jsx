import React, { useState } from 'react';
import {
  ActionIcon,
  Box,
  Group,
  Progress,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import { ChevronDown, ChevronRight, Radio } from 'lucide-react';

const formatProgramTime = (seconds) => {
  const absSeconds = Math.abs(seconds);
  const hours = Math.floor(absSeconds / 3600);
  const minutes = Math.floor((absSeconds % 3600) / 60);
  const secs = Math.floor(absSeconds % 60);
  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  }
  return `${minutes}:${secs.toString().padStart(2, '0')}`;
};

const formatAirWindow = (startTime, endTime) => {
  if (!startTime || !endTime) {
    return null;
  }
  const start = new Date(startTime);
  const end = new Date(endTime);
  const dateOpts = { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' };
  const endOpts = { hour: '2-digit', minute: '2-digit' };
  return `${start.toLocaleString(undefined, dateOpts)} to ${end.toLocaleTimeString(undefined, endOpts)}`;
};

const getTimelineState = ({
  timelineMode,
  program,
  playbackElapsedSeconds,
  now,
}) => {
  const startTime = program.start_time ? new Date(program.start_time) : null;
  const endTime = program.end_time ? new Date(program.end_time) : null;
  if (!startTime || !endTime) {
    return { hasValidTime: false };
  }

  const totalDuration = (endTime - startTime) / 1000;
  if (totalDuration <= 0) {
    return { hasValidTime: false };
  }

  if (timelineMode === 'catchup') {
    const watched = Math.max(0, Math.floor(playbackElapsedSeconds ?? 0));
    const cappedWatched = Math.min(watched, totalDuration);
    const remaining = Math.max(0, totalDuration - cappedWatched);
    return {
      hasValidTime: true,
      elapsed: cappedWatched,
      remaining,
      percentage: Math.min(100, (cappedWatched / totalDuration) * 100),
      elapsedLabel: 'watched',
      remainingLabel: 'remaining',
      airWindow: formatAirWindow(program.start_time, program.end_time),
    };
  }

  const elapsed = (now - startTime) / 1000;
  const remaining = (endTime - now) / 1000;
  return {
    hasValidTime: true,
    elapsed,
    remaining,
    percentage: Math.min(100, Math.max(0, (elapsed / totalDuration) * 100)),
    elapsedLabel: 'elapsed',
    remainingLabel: 'remaining',
    airWindow: null,
  };
};

const ProgramPreview = ({
  program,
  loading,
  fetched,
  label = 'Now Playing:',
  timelineMode = 'live',
  playbackElapsedSeconds = 0,
}) => {
  const [isExpanded, setIsExpanded] = useState(false);

  if (loading) {
    return (
      <Group gap={5}>
        <Radio size="14" style={{ color: '#22c55e', flexShrink: 0 }} />
        <Text size="xs" c="dimmed">Loading EPG data...</Text>
      </Group>
    );
  }

  if (fetched && !program) {
    return (
      <Group gap={5}>
        <Radio size="14" style={{ color: '#6b7280', flexShrink: 0 }} />
        <Text size="xs" c="dimmed">No current program (EPG may need refresh)</Text>
      </Group>
    );
  }

  if (!program) {
    return null;
  }

  const timeline = getTimelineState({
    timelineMode,
    program,
    playbackElapsedSeconds,
    now: new Date(),
  });

  return (
    <>
      <Group gap={5} wrap="nowrap">
        <Radio size="14" style={{ color: '#22c55e', flexShrink: 0 }} />
        <Text size="xs" fw={500} c="green.5" style={{ flexShrink: 0 }}>
          {label}
        </Text>
        <Tooltip label={program.title}>
          <Text size="xs" c="dimmed" truncate>
            {program.title}
          </Text>
        </Tooltip>
        <ActionIcon
          size="xs"
          variant="subtle"
          onClick={() => setIsExpanded(!isExpanded)}
          style={{ flexShrink: 0 }}
        >
          {isExpanded ? <ChevronDown size="14" /> : <ChevronRight size="14" />}
        </ActionIcon>
      </Group>

      {isExpanded && program.description && (
        <Box mt={4} ml={24}>
          <Text size="xs" c="dimmed" style={{ fontStyle: 'italic' }}>
            {program.description}
          </Text>
        </Box>
      )}

      {isExpanded && timeline.hasValidTime && (
        <Stack gap="xs" mt={4} ml={24}>
          {timeline.airWindow && (
            <Text size="xs" c="dimmed">
              Aired {timeline.airWindow}
            </Text>
          )}
          <Group justify="space-between" align="center">
            <Text size="xs" c="dimmed">
              {formatProgramTime(timeline.elapsed)} {timeline.elapsedLabel}
            </Text>
            <Text size="xs" c="dimmed">
              {formatProgramTime(timeline.remaining)} {timeline.remainingLabel}
            </Text>
          </Group>
          <Progress
            value={timeline.percentage}
            size="sm"
            color="#3BA882"
            style={{
              backgroundColor: 'rgba(255, 255, 255, 0.1)',
            }}
          />
        </Stack>
      )}
    </>
  );
};

export default ProgramPreview;
