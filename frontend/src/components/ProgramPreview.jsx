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

const ProgramPreview = ({ program, loading, fetched, label = 'Now Playing:' }) => {
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

  const now = new Date();
  const startTime = program.start_time ? new Date(program.start_time) : null;
  const endTime = program.end_time ? new Date(program.end_time) : null;

  let elapsed = 0, remaining = 0, percentage = 0;
  let hasValidTime = false;
  if (startTime && endTime) {
    const totalDuration = (endTime - startTime) / 1000;
    if (totalDuration > 0) {
      hasValidTime = true;
      elapsed = (now - startTime) / 1000;
      remaining = (endTime - now) / 1000;
      percentage = Math.min(100, Math.max(0, (elapsed / totalDuration) * 100));
    }
  }

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

      {isExpanded && hasValidTime && (
        <Stack gap="xs" mt={4} ml={24}>
          <Group justify="space-between" align="center">
            <Text size="xs" c="dimmed">
              {formatProgramTime(elapsed)} elapsed
            </Text>
            <Text size="xs" c="dimmed">
              {formatProgramTime(remaining)} remaining
            </Text>
          </Group>
          <Progress
            value={percentage}
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
