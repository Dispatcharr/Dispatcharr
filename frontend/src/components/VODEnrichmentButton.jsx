import React from 'react';
import { ActionIcon, Button, Group, Tooltip } from '@mantine/core';
import { LockKeyhole, Pencil } from 'lucide-react';

const VODEnrichmentButton = ({
  onClick,
  disabled = false,
  loading = false,
  locked = false,
  unlocking = false,
  onUnlock,
}) => (
  <Group gap={6} wrap="nowrap">
    {locked && (
      <Tooltip
        label="Unlock to include this title in automatic cleanup and TMDB matching again."
        withArrow
        multiline
        maw={300}
      >
        <ActionIcon
          size="lg"
          variant="default"
          aria-label="Unlock automatic metadata matching"
          onClick={onUnlock}
          loading={unlocking}
          disabled={unlocking || !onUnlock}
        >
          <LockKeyhole size={16} />
        </ActionIcon>
      </Tooltip>
    )}
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
