// Per-group "advanced config" modal opened from the gear icon on each row
// in LiveGroupFilter / M3UGroupFilter. The inline row keeps only the core
// Sync toggle, Numbering Mode, and Start/End inputs. This modal renders
// the full Advanced Options MultiSelect plus its conditional fields,
// passed in as children by the parent so it continues to own the group
// list and field logic.

import React from 'react';
import { Modal, Stack, Group, Text } from '@mantine/core';

const GroupConfigureModal = ({ opened, onClose, group, children }) => {
  if (!group) return null;
  const streamCount =
    typeof group.stream_count === 'number' ? group.stream_count : null;

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      size="lg"
      title={
        <Group gap="xs">
          <Text fw={600}>Configure: {group.name}</Text>
          {streamCount !== null && (
            <Text size="xs" c="dimmed">
              ({streamCount} stream{streamCount === 1 ? '' : 's'} available)
            </Text>
          )}
        </Group>
      }
      styles={{ content: { '--mantine-color-body': '#27272A' } }}
    >
      <Stack gap="md">{children}</Stack>
    </Modal>
  );
};

export default GroupConfigureModal;
