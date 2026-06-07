import React, { useState } from 'react';
import { Modal, Stack, Text, Flex, Group, Button, Badge } from '@mantine/core';
import useChannelsStore from '../../store/channels.jsx';
import { deleteSeriesAndRule } from '../../utils/cards/RecordingCardUtils.js';
import {
  evaluateSeriesRulesByTvgId,
  fetchRules,
} from '../../utils/guideUtils.js';
import { showNotification } from '../../utils/notificationUtils.js';
import SeriesRuleEditorModal from './SeriesRuleEditorModal.jsx';

const TITLE_MODE_LABEL = {
  exact: 'Exact title',
  contains: 'Title contains',
  search: 'Whole word title',
  regex: 'Title regex',
};

const renderRuleSummary = (r) => {
  const titleMode = (r.title_mode || 'exact').toLowerCase();
  const parts = [];
  parts.push(r.mode === 'new' ? 'New episodes' : 'Every episode');
  if (r.title) {
    parts.push(`${TITLE_MODE_LABEL[titleMode] || titleMode}: "${r.title}"`);
  }
  if (r.description) {
    parts.push(`Description: "${r.description}"`);
  }
  return parts.join(' | ');
};

export default function SeriesRecordingModal({
  opened,
  onClose,
  rules,
  onRulesUpdate,
}) {
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorRule, setEditorRule] = useState(null);

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

  const openEditor = (rule) => {
    setEditorRule(rule || null);
    setEditorOpen(true);
  };

  const handleEditorSaved = async () => {
    const updated = await fetchRules();
    onRulesUpdate(updated);
  };

  return (
    <>
      <Modal
        opened={opened}
        onClose={onClose}
        title="Series Recording Rules"
        centered
        size="lg"
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
          <Group justify="flex-end">
            <Button size="xs" onClick={() => openEditor(null)}>
              Add rule
            </Button>
          </Group>

          {(!rules || rules.length === 0) && (
            <Text size="sm" c="dimmed">
              No series rules configured
            </Text>
          )}
          {rules &&
            rules.map((r) => (
              <Flex
                key={`${r.tvg_id}-${r.mode}-${r.title || ''}`}
                justify="space-between"
                align="center"
                gap="sm"
              >
                <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
                  <Group gap="xs" wrap="nowrap">
                    <Text size="sm" fw={500} truncate>
                      {r.title || r.tvg_id}
                    </Text>
                    {r.channel_id && (
                      <Badge size="xs" variant="light" color="blue">
                        Pinned channel
                      </Badge>
                    )}
                  </Group>
                  <Text size="xs" c="dimmed" truncate>
                    {renderRuleSummary(r)}
                  </Text>
                </Stack>
                <Group gap="xs">
                  <Button
                    size="xs"
                    variant="subtle"
                    onClick={() => openEditor(r)}
                  >
                    Edit
                  </Button>
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
                    Remove
                  </Button>
                </Group>
              </Flex>
            ))}
        </Stack>
      </Modal>

      <SeriesRuleEditorModal
        opened={editorOpen}
        onClose={() => setEditorOpen(false)}
        initialRule={editorRule}
        onSaved={handleEditorSaved}
      />
    </>
  );
}
