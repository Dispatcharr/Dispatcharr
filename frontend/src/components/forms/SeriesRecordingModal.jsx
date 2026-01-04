import React from 'react';
import { Modal, Stack, Text, Flex, Group, Button } from '@mantine/core';
import useChannelsStore from '../../store/channels.jsx';
import { deleteSeriesAndRule } from '../../utils/cards/RecordingCardUtils.js';
import { evaluateSeriesRulesByTvgId, fetchRules } from '../../pages/guideUtils.js';
import { showNotification } from '../../utils/notificationUtils.js';

export default function SeriesRecordingModal({
 opened,
 onClose,
 rules,
 onRulesUpdate
}) {
  const handleEvaluateNow = async (r) => {
    await evaluateSeriesRulesByTvgId(r.tvg_id);
    try {
      await useChannelsStore.getState().fetchRecordings();
    } catch (error) {
      console.warn('Failed to refresh recordings after evaluation', error);
    }
    showNotification({
      title: 'Evaluated',
      message: 'Checked for episodes',
    });
  };

  const handleRemoveSeries = async (r) => {
    await deleteSeriesAndRule({ tvg_id: r.tvg_id, title: r.title });
    try {
      await useChannelsStore.getState().fetchRecordings();
    } catch (error) {
      console.warn('Failed to refresh recordings after bulk removal', error);
    }
    const updated = await fetchRules();
    onRulesUpdate(updated);
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title="Series Recording Rules"
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
      <Stack gap="sm">
        {(!rules || rules.length === 0) && (
          <Text size="sm" c="dimmed">
            No series rules configured
          </Text>
        )}
        {rules && rules.map((r) => (
          <Flex
            key={`${r.tvg_id}-${r.mode}`}
            justify="space-between"
            align="center"
          >
            <Text size="sm">
              {r.title || r.tvg_id} —{' '}
              {r.mode === 'new' ? 'New episodes' : 'Every episode'}
            </Text>
            <Group gap="xs">
              <Button
                size="xs"
                variant="subtle"
                onClick={() => handleEvaluateNow(r)}
              >
                Evaluate Now
              </Button>
              <Button
                size="xs"
                variant="light"
                color="orange"
                onClick={() => handleRemoveSeries(r)}
              >
                Remove this series (scheduled)
              </Button>
            </Group>
          </Flex>
        ))}
      </Stack>
    </Modal>
  );
}
