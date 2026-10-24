// Per-group settings opened from the gear icon. The parent owns the draft
// and restores its open-time snapshot when the user discards changes.

import React, { useEffect, useState } from 'react';
import { Button, Stack, Group, Text } from '@mantine/core';
import StackedModal from '../StackedModal.jsx';
import ConfirmationDialog from '../ConfirmationDialog.jsx';

const GroupConfigureModal = ({
  opened,
  onDone,
  onCancel,
  group,
  children,
  dirty = false,
  content,
  onRetryContent,
}) => {
  const [discardOpen, setDiscardOpen] = useState(false);
  useEffect(() => setDiscardOpen(false), [opened, group?.channel_group]);
  if (!group) return null;
  const importedCount =
    content?.source === 'imported' ? content.count : group.stream_count;
  const close = () => (dirty ? setDiscardOpen(true) : onCancel());

  return (
    <>
      <StackedModal
        stackId="m3u-live-category-settings"
        keepVisibleInStack
        opened={opened}
        onClose={close}
        closeOnEscape={!discardOpen}
        closeOnClickOutside={!discardOpen}
        trapFocus={!discardOpen}
        closeButtonProps={{ 'aria-label': 'Close category settings' }}
        size="lg"
        title={
          <Group gap="xs">
            <Text fw={600}>Configure: {group.name}</Text>
            <Text size="xs" c="dimmed" role="status">
              {content?.source === 'provider' &&
                `${content.count} in preview · `}
              {Number.isFinite(importedCount) ? importedCount : '—'} imported
              {content?.loading && ' · loading…'}
            </Text>
          </Group>
        }
        styles={{ content: { '--mantine-color-body': '#27272A' } }}
      >
        <Stack gap="md">
          {content?.error && (
            <Group gap="xs">
              <Text size="sm" c="red" role="alert">
                {content.error}
              </Text>
              <Button
                size="compact-xs"
                variant="light"
                onClick={onRetryContent}
              >
                Retry category preview
              </Button>
            </Group>
          )}
          {children}
        </Stack>
        {/* Apply keeps the local draft; the parent Categories Save persists it. */}
        <Group justify="flex-end" gap="xs" mt="md">
          <Button variant="filled" color="blue" onClick={onDone} size="xs">
            Apply
          </Button>
        </Group>
      </StackedModal>
      <ConfirmationDialog
        opened={opened && discardOpen}
        onClose={() => setDiscardOpen(false)}
        onConfirm={() => {
          setDiscardOpen(false);
          onCancel();
        }}
        title="Unsaved changes"
        message="Discard changes to this category? Saved category selections are unchanged."
        cancelLabel="Keep editing"
        confirmLabel="Discard"
        zIndex={300}
      />
    </>
  );
};

export default GroupConfigureModal;
