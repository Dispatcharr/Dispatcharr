import React from 'react';
import { ActionIcon, Button, Group, Tooltip } from '@mantine/core';
import { LockKeyhole, LockKeyholeOpen, Pencil } from 'lucide-react';

const VODEnrichmentButton = ({
  onClick,
  disabled = false,
  loading = false,
  locked = false,
  changingLock = false,
  onUnlock,
  onLock,
}) => (
  <Group gap={6} wrap="nowrap">
    <Tooltip
      label={
        locked
          ? 'Unlock to include this title in automatic cleanup and TMDB matching again.'
          : 'Lock this title so automatic cleanup, TMDB matching, and metadata resets cannot overwrite it.'
      }
      withArrow
      multiline
      maw={320}
    >
      <ActionIcon
        size="lg"
        variant="default"
        aria-label={
          locked
            ? 'Unlock automatic metadata matching'
            : 'Lock automatic metadata matching'
        }
        onClick={locked ? onUnlock : onLock}
        loading={changingLock}
        disabled={changingLock || (locked ? !onUnlock : !onLock)}
      >
        {locked ? <LockKeyhole size={16} /> : <LockKeyholeOpen size={16} />}
      </ActionIcon>
    </Tooltip>
    <Button
      size="xs"
      variant="default"
      leftSection={<Pencil size={15} />}
      onClick={onClick}
      disabled={disabled || locked}
      loading={loading}
    >
      Edit metadata
    </Button>
  </Group>
);

export default VODEnrichmentButton;
