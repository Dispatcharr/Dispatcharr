import React from 'react';
import {
  ActionIcon,
  Alert,
  Box,
  Button,
  Group,
  Paper,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
} from '@mantine/core';
import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { restrictToVerticalAxis } from '@dnd-kit/modifiers';
import { GripVertical, Plus, Trash2 } from 'lucide-react';
import LanguagePicker from './LanguagePicker.jsx';
import VideoFeaturePicker from './VideoFeaturePicker.jsx';
import { RESOLUTION_LIMIT_OPTIONS } from '../utils/vodMetadataOptions.js';

const RULE_DEFAULTS = {
  title_suffix: '',
  enabled: true,
  min_resolution: 0,
  max_resolution: 0,
  required_audio_languages: [],
  required_subtitle_languages: [],
  required_video_features: [],
};

const createRule = () => ({
  ...RULE_DEFAULTS,
  id: `edition-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
});

const SortableEdition = ({ rule, update, remove }) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: rule.id });
  return (
    <Paper
      ref={setNodeRef}
      withBorder
      p="sm"
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.65 : rule.enabled ? 1 : 0.55,
        position: 'relative',
        zIndex: isDragging ? 2 : 0,
      }}
    >
      <Group align="flex-end" wrap="nowrap">
        <ActionIcon
          aria-label={`Move suffix rule ${rule.title_suffix || 'rule'}`}
          variant="subtle"
          color="gray"
          mb={3}
          style={{ cursor: isDragging ? 'grabbing' : 'grab' }}
          {...attributes}
          {...listeners}
        >
          <GripVertical size={17} />
        </ActionIcon>
        <TextInput
          label="Output suffix"
          placeholder="For example 3D or 4K"
          value={rule.title_suffix}
          onChange={(event) =>
            update({ title_suffix: event.currentTarget.value })
          }
          required
          w={150}
        />
        <Select
          label="Minimum"
          data={RESOLUTION_LIMIT_OPTIONS}
          value={String(rule.min_resolution || 0)}
          onChange={(value) => update({ min_resolution: Number(value || 0) })}
          w={112}
        />
        <Select
          label="Maximum"
          data={RESOLUTION_LIMIT_OPTIONS}
          value={String(rule.max_resolution || 0)}
          onChange={(value) => update({ max_resolution: Number(value || 0) })}
          w={112}
        />
        <Box w={210}>
          <LanguagePicker
            label="Required DUB"
            size="xs"
            value={rule.required_audio_languages}
            onChange={(required_audio_languages) =>
              update({ required_audio_languages })
            }
          />
        </Box>
        <Box w={210}>
          <LanguagePicker
            label="Required SUB"
            size="xs"
            value={rule.required_subtitle_languages}
            onChange={(required_subtitle_languages) =>
              update({ required_subtitle_languages })
            }
          />
        </Box>
        <Box w={210}>
          <VideoFeaturePicker
            label="Required features"
            size="xs"
            value={rule.required_video_features}
            onChange={(required_video_features) =>
              update({ required_video_features })
            }
            emptyLabel="Any feature"
          />
        </Box>
        <Switch
          label="Enabled"
          checked={rule.enabled}
          onChange={(event) => update({ enabled: event.currentTarget.checked })}
          mb={8}
        />
        <ActionIcon
          aria-label={`Delete suffix rule ${rule.title_suffix || 'rule'}`}
          color="red"
          variant="subtle"
          mb={3}
          onClick={remove}
        >
          <Trash2 size={16} />
        </ActionIcon>
      </Group>
    </Paper>
  );
};

const VODEditionRules = ({ value = [], onChange }) => {
  const rules = value.map((rule, index) => ({
    ...RULE_DEFAULTS,
    ...rule,
    id: rule.id || `edition-${index}`,
  }));
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );
  const update = (id, changes) =>
    onChange(
      rules.map((rule) => (rule.id === id ? { ...rule, ...changes } : rule))
    );
  const remove = (id) => onChange(rules.filter((rule) => rule.id !== id));
  const reorder = ({ active, over }) => {
    if (!over || active.id === over.id) return;
    const from = rules.findIndex((rule) => rule.id === active.id);
    const to = rules.findIndex((rule) => rule.id === over.id);
    if (from >= 0 && to >= 0) onChange(arrayMove(rules, from, to));
  };

  return (
    <Stack>
      <Group justify="space-between" align="center" w="100%">
        <Text fw={700}>Suffix rules</Text>
        <Button
          variant="default"
          size="xs"
          leftSection={<Plus size={14} />}
          onClick={() => onChange([...rules, createRule()])}
        >
          Add suffix rule
        </Button>
      </Group>
      {!rules.length ? (
        <Alert color="gray">
          No suffix rules. Compact keeps one entry per canonical title.
        </Alert>
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          modifiers={[restrictToVerticalAxis]}
          onDragEnd={reorder}
        >
          <SortableContext
            items={rules.map((rule) => rule.id)}
            strategy={verticalListSortingStrategy}
          >
            <Stack gap="sm">
              {rules.map((rule) => (
                <SortableEdition
                  key={rule.id}
                  rule={rule}
                  update={(changes) => update(rule.id, changes)}
                  remove={() => remove(rule.id)}
                />
              ))}
            </Stack>
          </SortableContext>
        </DndContext>
      )}
    </Stack>
  );
};

export default VODEditionRules;
