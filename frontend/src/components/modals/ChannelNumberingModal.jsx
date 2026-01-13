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
} from '@mantine/core';

const ChannelNumberingModal = ({
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
}) => {
  const title = isBulk
    ? 'Channel Numbering Options'
    : 'Channel Number Assignment';
  const confirmLabel = isBulk ? 'Create Channels' : 'Create Channel';
  const numberingLabel = isBulk ? 'Numbering Mode' : 'Number Assignment';

  // For bulk: use 'custom' mode, for single: use 'specific' mode
  const customModeValue = isBulk ? 'custom' : 'specific';

  return (
    <Modal opened={opened} onClose={onClose} title={title} size="md" centered>
      <Stack spacing="md">
        <Text size="sm" c="dimmed">
          {isBulk
            ? `Choose how to assign channel numbers to the ${streamCount} selected streams:`
            : `Choose how to assign the channel number for "${streamName}":`}
        </Text>

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

export default ChannelNumberingModal;
