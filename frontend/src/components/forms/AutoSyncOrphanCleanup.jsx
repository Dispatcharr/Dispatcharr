import React, { useEffect, useState } from 'react';
import { updatePlaylist } from '../../utils/forms/M3uUtils.js';
import { showNotification } from '../../utils/notificationUtils.js';
import { Box, Group, SegmentedControl, Text, Tooltip } from '@mantine/core';

const OrphanCleanupControl = ({ playlist }) => {
  // Local state mirrors the persisted mode so the SegmentedControl
  // reflects clicks immediately even when the parent's playlist prop is
  // a stale snapshot from before the PATCH lands.
  const [orphanCleanupMode, setOrphanCleanupMode] = useState(
    (playlist?.custom_properties || {}).orphan_channel_cleanup || 'always'
  );

  useEffect(() => {
    setOrphanCleanupMode(
      (playlist?.custom_properties || {}).orphan_channel_cleanup || 'always'
    );
  }, [playlist?.id, playlist?.custom_properties?.orphan_channel_cleanup]);

  const handleOrphanCleanupChange = async (mode) => {
    if (!playlist?.id) return;
    const previousMode = orphanCleanupMode;
    setOrphanCleanupMode(mode);
    const nextProps = {
      ...(playlist.custom_properties || {}),
      orphan_channel_cleanup: mode,
    };
    try {
      await updatePlaylist(playlist, { custom_properties: nextProps });
    } catch (err) {
      setOrphanCleanupMode(previousMode);
      showNotification({
        title: 'Failed to update cleanup mode',
        message: err?.body?.detail || err?.message || 'Please try again.',
        color: 'red',
      });
    }
  };

  return (
    <Box>
      <Group gap="sm" align="center" wrap="nowrap">
        <Tooltip
          label="Controls what sync does with auto-synced channels whose source streams have been removed from this provider. Manual channels and hidden channels are never affected by this setting."
          withArrow
          multiline
          w={320}
          openDelay={400}
        >
          <Text size="sm" fw={500}>
            Auto-sync orphan cleanup
          </Text>
        </Tooltip>
        <SegmentedControl
          size="xs"
          value={orphanCleanupMode}
          onChange={handleOrphanCleanupChange}
          data={[
            { label: 'Always remove', value: 'always' },
            { label: 'Preserve customized', value: 'preserve_customized' },
            { label: 'Never remove', value: 'never' },
          ]}
        />
      </Group>
      <Text size="xs" c="dimmed" mt={4}>
        {orphanCleanupMode === 'always' &&
          'Removes any auto-synced channel whose source stream is gone from this provider.'}
        {orphanCleanupMode === 'preserve_customized' &&
          'Removes orphaned auto-synced channels except those with active overrides.'}
        {orphanCleanupMode === 'never' &&
          'Keeps all orphaned auto-synced channels. You can clean up manually from the channels page.'}
      </Text>
    </Box>
  );
};

export default OrphanCleanupControl;
