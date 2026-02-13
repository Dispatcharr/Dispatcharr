import React from 'react';
import {
  Modal,
  Stack,
  Text,
  Radio,
  NumberInput,
  Checkbox,
  Group,
  Button,
  MultiSelect,
  Divider,
} from '@mantine/core';

const CreateChannelModal = ({
  opened,
  onClose,
  mode,
  onModeChange,
  numberValue,
  onNumberValueChange,
  rememberChoice,
  onRememberChoiceChange,
  onConfirm,
  // Props for customizing the modal behavior
  isBulk = false,
  streamCount = 1,
  streamName = '',
  // Channel profile props
  selectedProfileIds,
  onProfileIdsChange,
  channelProfiles = [],
}) => {
  const title = isBulk ? 'Create Channels Options' : 'Create Channel';
  const confirmLabel = isBulk ? 'Create Channels' : 'Create Channel';
  const numberingLabel = isBulk ? 'Numbering Mode' : 'Number Assignment';

  // For bulk: use 'custom' mode, for single: use 'specific' mode
  const customModeValue = isBulk ? 'custom' : 'specific';

  // Convert channel profiles to MultiSelect data format with groups
  // Filter out the "All" profile (id '0') and add our own special options
  const profileOptions = [
    {
      group: 'Special',
      items: [
        { value: 'all', label: 'All Profiles' },
        { value: 'none', label: 'No Profiles' },
      ],
    },
    {
      group: 'Profiles',
      items: channelProfiles
        .filter((profile) => profile.id.toString() !== '0')
        .map((profile) => ({
          value: profile.id.toString(),
          label: profile.name,
        })),
    },
  ];

  // Handle profile selection with mutual exclusivity
  const handleProfileChange = (newValue) => {
    const lastSelected = newValue[newValue.length - 1];

    // If 'all' or 'none' was just selected, clear everything else and keep only that
    if (lastSelected === 'all' || lastSelected === 'none') {
      onProfileIdsChange([lastSelected]);
    }
    // If a specific profile was selected, remove 'all' and 'none'
    else if (newValue.includes('all') || newValue.includes('none')) {
      onProfileIdsChange(newValue.filter((v) => v !== 'all' && v !== 'none'));
    }
    // Otherwise just update normally
    else {
      onProfileIdsChange(newValue);
    }
  };

  return (
    <Modal opened={opened} onClose={onClose} title={title} size="md" centered>
      <Stack spacing="md">
        <Text size="sm" c="dimmed">
          {isBulk
            ? `Configure options for creating ${streamCount} channels from selected streams:`
            : `Configure options for creating a channel from "${streamName}":`}
        </Text>

        <Divider label="Channel Profiles" labelPosition="left" />

        <MultiSelect
          label="Channel Profiles"
          description="Select 'All Profiles' to add to all profiles, 'No Profiles' to not add to any profile, or choose specific profiles"
          placeholder="Select profiles..."
          data={profileOptions}
          value={selectedProfileIds}
          onChange={handleProfileChange}
          searchable
          clearable
        />

        <Divider label="Channel Number" labelPosition="left" />

        <Radio.Group
          value={mode}
          onChange={onModeChange}
          label={numberingLabel}
        >
          <Stack mt="xs" spacing="xs">
            <Radio
              value="provider"
              label={isBulk ? 'Use Provider Numbers' : 'Use Provider Number'}
              description={
                isBulk
                  ? 'Use tvg-chno or channel-number from stream metadata, auto-assign for conflicts'
                  : 'Use tvg-chno or channel-number from stream metadata, auto-assign if not available'
              }
            />
            <Radio
              value="auto"
              label={
                isBulk ? 'Auto-Assign Sequential' : 'Auto-Assign Next Available'
              }
              description={
                isBulk
                  ? 'Start from the lowest available channel number and increment by 1'
                  : 'Automatically assign the next available channel number'
              }
            />
            <Radio
              value={customModeValue}
              label={
                isBulk ? 'Start from Custom Number' : 'Use Specific Number'
              }
              description={
                isBulk
                  ? 'Start sequential numbering from a specific channel number'
                  : 'Use a specific channel number'
              }
            />
          </Stack>
        </Radio.Group>

        {mode === customModeValue && (
          <NumberInput
            label={isBulk ? 'Starting Channel Number' : 'Channel Number'}
            description={
              isBulk
                ? 'Channel numbers will be assigned starting from this number'
                : 'The specific channel number to assign'
            }
            value={numberValue}
            onChange={onNumberValueChange}
            min={1}
            placeholder={
              isBulk ? 'Enter starting number...' : 'Enter channel number...'
            }
          />
        )}

        <Checkbox
          checked={rememberChoice}
          onChange={(event) =>
            onRememberChoiceChange(event.currentTarget.checked)
          }
          label="Remember this choice and don't ask again"
        />

        <Group justify="flex-end" mt="md">
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={onConfirm}>{confirmLabel}</Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default CreateChannelModal;
