import React from 'react';
import { Modal, Flex, Button } from '@mantine/core';
import useChannelsStore from '../../store/channels.jsx';
import { deleteRecordingById } from '../../utils/cards/RecordingCardUtils.js';
import { deleteSeriesAndRule } from '../../utils/cards/RecordingCardUtils.js';
import { deleteSeriesRuleByTvgId } from '../../pages/guideUtils.js';

export default function ProgramRecordingModal({
  opened,
  onClose,
  program,
  recording,
  existingRuleMode,
  onRecordOne,
  onRecordSeriesAll,
  onRecordSeriesNew,
  onExistingRuleModeChange,
}) {
  const handleRemoveRecording = async () => {
    try {
      await deleteRecordingById(recording.id);
    } catch (error) {
      console.warn('Failed to delete recording', error);
    }
    try {
      await useChannelsStore.getState().fetchRecordings();
    } catch (error) {
      console.warn('Failed to refresh recordings after delete', error);
    }
    onClose();
  };

  const handleRemoveSeries = async () => {
    await deleteSeriesAndRule({
      tvg_id: program.tvg_id,
      title: program.title,
    });
    try {
      await useChannelsStore.getState().fetchRecordings();
    } catch (error) {
      console.warn('Failed to refresh recordings after series delete', error);
    }
    onClose();
  };

  const handleRemoveSeriesRule = async () => {
    await deleteSeriesRuleByTvgId(program.tvg_id);
    onExistingRuleModeChange(null);
    onClose();
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={`Record: ${program?.title}`}
      centered
      radius="md"
      zIndex={9999}
      overlayProps={{ color: '#000', backgroundOpacity: 0.55, blur: 0 }}
      styles={{
        content: { backgroundColor: '#18181B', color: 'white' },
        header: { backgroundColor: '#18181B', color: 'white' },
        title: { color: 'white' },
      }}
    >
      <Flex direction="column" gap="sm">
        <Button
          onClick={() => {
            onRecordOne();
            onClose();
          }}
        >
          Just this one
        </Button>

        <Button variant="light" onClick={() => {
          onRecordSeriesAll();
          onClose();
        }}>
          Every episode
        </Button>

        <Button variant="light" onClick={() => {
          onRecordSeriesNew();
          onClose();
        }}>
          New episodes only
        </Button>

        {recording && (
          <>
            <Button color="orange" variant="light" onClick={handleRemoveRecording}>
              Remove this recording
            </Button>
            <Button color="red" variant="light" onClick={handleRemoveSeries}>
              Remove this series (scheduled)
            </Button>
          </>
        )}

        {existingRuleMode && (
          <Button color="red" variant="subtle" onClick={handleRemoveSeriesRule}>
            Remove series rule ({existingRuleMode})
          </Button>
        )}
      </Flex>
    </Modal>
  );
}
