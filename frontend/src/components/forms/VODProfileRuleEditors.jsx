import React from 'react';
import {
  ActionIcon,
  Alert,
  Box,
  Button,
  Group,
  MultiSelect,
  Paper,
  Select,
  Stack,
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
import { GripVertical, Info, Plus, Trash2 } from 'lucide-react';
import {
  featureOptions,
  fieldError,
  isBlankEdition,
  languageOptions,
  newEditionRule,
  resolutionOptions,
} from '../../utils/vodProfiles';

// Items have no IDs of their own; their position identifies them.
export function SortableList({ items, onChange, children }) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );
  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      modifiers={[restrictToVerticalAxis]}
      onDragEnd={({ active, over }) => {
        if (over && active.id !== over.id)
          onChange(arrayMove(items, Number(active.id), Number(over.id)));
      }}
    >
      <SortableContext
        items={items.map((_item, index) => String(index))}
        strategy={verticalListSortingStrategy}
      >
        {children}
      </SortableContext>
    </DndContext>
  );
}

function useSortableItem(index) {
  const sortable = useSortable({ id: String(index) });
  return {
    ...sortable,
    style: {
      transform: CSS.Transform.toString(sortable.transform),
      transition: sortable.transition,
      position: 'relative',
      zIndex: sortable.isDragging ? 2 : 0,
    },
  };
}

export function SortableItem({ index, children }) {
  return children(useSortableItem(index));
}

export function DragHandle({ label, sortable }) {
  return (
    <ActionIcon
      aria-label={`Move ${label}`}
      variant="default"
      size="sm"
      color="gray"
      style={{ cursor: sortable.isDragging ? 'grabbing' : 'grab' }}
      {...sortable.attributes}
      {...sortable.listeners}
    >
      <GripVertical size={16} />
    </ActionIcon>
  );
}

function EditionRow({ rule, index, options, errors, update, remove }) {
  const sortable = useSortableItem(index);
  const label = rule.title_suffix || `edition ${index + 1}`;
  const languages = languageOptions(options.languages);
  const resolutions = resolutionOptions(options.resolutions);
  const error = (field) => fieldError(errors, 'edition_rules', index, field);
  // Highlighted like an unsaved M3U rule until it is filled in or removed.
  const blank = isBlankEdition(rule);
  return (
    <Paper
      ref={sortable.setNodeRef}
      withBorder
      p="sm"
      title={blank ? 'Unsaved changes' : undefined}
      style={{
        ...sortable.style,
        ...(blank && {
          boxShadow: 'inset 3px 0 var(--mantine-color-blue-5)',
          backgroundColor: 'var(--mantine-color-blue-light)',
        }),
      }}
      data-dirty={blank ? 'true' : undefined}
      data-invalid={errors.edition_rules?.[index] ? 'true' : undefined}
    >
      <Group align="flex-start" wrap="nowrap" gap="sm">
        <Box mt={30}>
          <DragHandle label={label} sortable={sortable} />
        </Box>
        <TextInput
          label="Suffix"
          withAsterisk
          aria-label={`Edition ${index + 1} suffix`}
          placeholder="e.g. 4K"
          value={rule.title_suffix}
          error={error('title_suffix')}
          onChange={(event) =>
            update({ title_suffix: event.currentTarget.value })
          }
          w={130}
        />
        <Select
          label="Minimum"
          aria-label={`Edition ${index + 1} minimum resolution`}
          value={String(rule.min_resolution || 0)}
          allowDeselect={false}
          onChange={(value) => update({ min_resolution: Number(value) })}
          data={resolutions}
          w={110}
        />
        <Select
          label="Maximum"
          aria-label={`Edition ${index + 1} maximum resolution`}
          value={String(rule.max_resolution || 0)}
          allowDeselect={false}
          error={error('max_resolution')}
          onChange={(value) => update({ max_resolution: Number(value) })}
          data={resolutions}
          w={110}
        />
        <MultiSelect
          label="Required DUB"
          searchable
          value={rule.required_audio_languages}
          onChange={(value) => update({ required_audio_languages: value })}
          data={languages}
          style={{ flex: 1, minWidth: 140 }}
        />
        <MultiSelect
          label="Required SUB"
          searchable
          value={rule.required_subtitle_languages}
          onChange={(value) => update({ required_subtitle_languages: value })}
          data={languages}
          style={{ flex: 1, minWidth: 140 }}
        />
        <MultiSelect
          label="Required features"
          value={rule.required_video_features}
          onChange={(value) => update({ required_video_features: value })}
          data={featureOptions(options.video_features)}
          style={{ flex: 1, minWidth: 140 }}
        />
        <ActionIcon
          aria-label={`Delete ${label}`}
          color="red"
          variant="subtle"
          mt={28}
          onClick={remove}
        >
          <Trash2 size={16} />
        </ActionIcon>
      </Group>
      {error('conditions') && (
        <Text size="xs" c="red" mt={4} ml={36}>
          {error('conditions')}
        </Text>
      )}
    </Paper>
  );
}

export function EditionRulesEditor({ rules, options, errors, onChange }) {
  const error =
    typeof errors.edition_rules === 'string' && errors.edition_rules;
  const update = (index, patch) =>
    onChange(
      rules.map((rule, item) => (item === index ? { ...rule, ...patch } : rule))
    );
  return (
    <Stack gap="sm">
      <Group align="flex-end" wrap="nowrap" gap="sm">
        <Alert
          icon={<Info size={16} />}
          color="blue"
          variant="light"
          p={6}
          mih={30}
          style={{ flex: 1, minWidth: 0 }}
          styles={{
            icon: { width: 16, height: 16, marginInlineEnd: 8 },
            wrapper: { alignItems: 'center' },
          }}
        >
          <Text size="xs" lh="16px">
            <strong>Order matters.</strong> A source matching several editions
            gets the first one.
          </Text>
        </Alert>
        <Button
          size="xs"
          leftSection={<Plus size={14} />}
          onClick={() => onChange([...rules, newEditionRule()])}
        >
          Add edition
        </Button>
      </Group>
      {error && (
        <Text size="sm" c="red">
          {error}
        </Text>
      )}
      {!rules.length ? (
        <Alert color="gray">
          No editions. Compact output keeps one entry per title.
        </Alert>
      ) : (
        <SortableList items={rules} onChange={onChange}>
          <Stack gap="sm">
            {rules.map((rule, index) => (
              <EditionRow
                key={index}
                rule={rule}
                index={index}
                options={options}
                errors={errors}
                update={(patch) => update(index, patch)}
                remove={() =>
                  onChange(rules.filter((_rule, item) => item !== index))
                }
              />
            ))}
          </Stack>
        </SortableList>
      )}
    </Stack>
  );
}
