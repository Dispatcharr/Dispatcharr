import React, { useState, useEffect } from 'react';
import { Button, Group, Modal, Select, Stack, Text } from '@mantine/core';
import { showNotification } from '../../utils/notificationUtils';
import { updateProfileChannels } from '../../utils/tables/ChannelsTableUtils.js';

const AddToProfileModal = ({
  opened,
  onClose,
  channelIds = [],
  profiles = {},
  excludeProfileId,
}) => {
  const [targetProfileId, setTargetProfileId] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (opened) {
      setTargetProfileId(null);
    }
  }, [opened]);

  const closeModal = () => {
    setTargetProfileId(null);
    onClose();
  };

  const profileOptions = Object.values(profiles)
    // id 0 is the client-side "All Channels" view, not a real profile.
    .filter(
      (profile) =>
        `${profile.id}` !== '0' && `${profile.id}` !== `${excludeProfileId}`
    )
    .map((profile) => ({ label: profile.name, value: `${profile.id}` }));

  const submit = async () => {
    if (!targetProfileId || channelIds.length === 0) return;

    setSubmitting(true);
    try {
      await updateProfileChannels(channelIds, targetProfileId, true);

      const profileName = profiles[targetProfileId]?.name || 'profile';
      showNotification({
        title: 'Channels added',
        message: `${channelIds.length} channel${channelIds.length === 1 ? '' : 's'} added to ${profileName}`,
        color: 'green.5',
      });
      closeModal();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={closeModal}
      title="Add to Profile"
      size="sm"
      centered
    >
      <Stack gap="sm">
        <Text size="sm">
          Add {channelIds.length} selected channel
          {channelIds.length === 1 ? '' : 's'} to:
        </Text>

        <Select
          placeholder="Select target profile"
          data={profileOptions}
          value={targetProfileId}
          onChange={setTargetProfileId}
          data-autofocus
        />

        <Group justify="flex-end" gap="xs">
          <Button variant="default" size="xs" onClick={closeModal}>
            Cancel
          </Button>
          <Button
            size="xs"
            onClick={submit}
            disabled={!targetProfileId}
            loading={submitting}
          >
            Add
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default AddToProfileModal;
