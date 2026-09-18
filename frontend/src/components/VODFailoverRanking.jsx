import React, { useMemo } from 'react';
import {
  ActionIcon,
  Group,
  Paper,
  Select,
  Stack,
  Switch,
  Text,
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
import { ChevronDown, ChevronUp, GripVertical, Trash2 } from 'lucide-react';
import { normalizeVODFailoverRanking } from '../utils/vodFailoverRanking.js';
import { LANGUAGE_OPTIONS } from '../utils/languageCodes.js';

const criterionDetails = (criterion) => {
  if (criterion === 'audio_language') {
    return {
      title: 'DUB language preference',
      description: 'Prefers the first matching language in this row.',
    };
  }
  if (criterion === 'subtitle_language') {
    return {
      title: 'SUB language preference',
      description: 'Prefers the first matching language in this row.',
    };
  }
  if (criterion === 'metadata_completeness') {
    return {
      title: 'Known metadata first',
      description: 'Prefers sources with more known technical metadata.',
    };
  }
  if (criterion === 'provider') {
    return {
      title: 'Provider preference',
      description:
        'Uses the profile-specific provider order configured in this row.',
    };
  }
  return {
    title: 'Resolution',
    description: 'Controls quality preference within the configured limits.',
  };
};

const ProviderOrder = ({ value, options, onChange, itemLabel = 'provider' }) => {
  const order = [...new Set((value || []).map(String))];
  const labels = new Map(
    (options || []).map((option) => [String(option.value), option.label])
  );
  const available = (options || []).filter(
    (option) => !order.includes(String(option.value))
  );

  const move = (index, offset) => {
    const nextIndex = index + offset;
    if (nextIndex < 0 || nextIndex >= order.length) return;
    onChange(arrayMove(order, index, nextIndex));
  };

  return (
    <Stack gap="xs" mt="xs" pl={40}>
      {order.length ? (
        order.map((providerId, index) => (
          <Paper key={providerId} withBorder px="sm" py={6}>
            <Group justify="space-between" wrap="nowrap">
              <Text size="sm" truncate>
                {labels.get(providerId) ||
                  `Unavailable ${itemLabel} (${providerId})`}
              </Text>
              <Group gap={4} wrap="nowrap">
                <ActionIcon
                  variant="subtle"
                  color="gray"
                  disabled={index === 0}
                  aria-label={`Move ${labels.get(providerId) || providerId} up`}
                  onClick={() => move(index, -1)}
                >
                  <ChevronUp size={16} />
                </ActionIcon>
                <ActionIcon
                  variant="subtle"
                  color="gray"
                  disabled={index === order.length - 1}
                  aria-label={`Move ${labels.get(providerId) || providerId} down`}
                  onClick={() => move(index, 1)}
                >
                  <ChevronDown size={16} />
                </ActionIcon>
                <ActionIcon
                  variant="subtle"
                  color="red"
                  aria-label={`Remove ${labels.get(providerId) || providerId}`}
                  onClick={() =>
                    onChange(order.filter((id) => id !== providerId))
                  }
                >
                  <Trash2 size={15} />
                </ActionIcon>
              </Group>
            </Group>
          </Paper>
        ))
      ) : itemLabel === 'language' ? (
        <Text size="xs" c="dimmed">
          Add languages from highest to lowest preference.
        </Text>
      ) : (
        <Text size="xs" c="dimmed">
          No profile-specific order. The global M3U account priority remains the
          final fallback.
        </Text>
      )}
      <Select
        aria-label={`Add ${itemLabel} preference`}
        placeholder={`Add ${itemLabel}`}
        searchable
        disabled={!available.length}
        data={available}
        value={null}
        onChange={(providerId) => {
          if (providerId) onChange([...order, String(providerId)]);
        }}
      />
    </Stack>
  );
};

const SortableCriterion = ({
  criterion,
  onDirectionChange,
  providerOrder,
  providerOptions,
  onProviderOrderChange,
  enabled,
  onEnabledChange,
  languageOrder,
  onLanguageOrderChange,
}) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: criterion });
  const details = criterionDetails(criterion);

  return (
    <Paper
      ref={setNodeRef}
      withBorder
      p="sm"
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: enabled ? (isDragging ? 0.65 : 1) : 0.55,
        position: 'relative',
        zIndex: isDragging ? 2 : 0,
        height: '100%',
      }}
    >
      <Group wrap="nowrap" align="center" justify="space-between">
        <Group wrap="nowrap" align="flex-start" style={{ flex: 1 }}>
          <ActionIcon
            variant="subtle"
            color="gray"
            aria-label={`Move ${details.title}`}
            style={{ cursor: isDragging ? 'grabbing' : 'grab' }}
            {...attributes}
            {...listeners}
          >
            <GripVertical size={17} />
          </ActionIcon>
          <Stack gap={0}>
            <Text size="sm" fw={600}>
              {details.title}
            </Text>
            <Text size="xs" c="dimmed">
              {details.description}
            </Text>
          </Stack>
        </Group>
        <Switch
          aria-label={`Enable ${details.title}`}
          checked={enabled}
          onChange={(event) => onEnabledChange(event.currentTarget.checked)}
        />
        {enabled && (criterion === 'resolution_desc' ||
          criterion === 'resolution_asc') && (
          <Select
            aria-label="Resolution preference"
            w={150}
            data={[
              { value: 'resolution_desc', label: 'Highest first' },
              { value: 'resolution_asc', label: 'Lowest first' },
            ]}
            value={criterion}
            onChange={onDirectionChange}
          />
        )}
      </Group>
      {enabled && criterion === 'provider' && (
        <ProviderOrder
          value={providerOrder}
          options={providerOptions}
          onChange={onProviderOrderChange}
        />
      )}
      {enabled && ['audio_language', 'subtitle_language'].includes(criterion) && (
        <ProviderOrder
          value={languageOrder}
          options={LANGUAGE_OPTIONS}
          onChange={onLanguageOrderChange}
          itemLabel="language"
        />
      )}
    </Paper>
  );
};

const VODFailoverRanking = ({
  value,
  onChange,
  providerOrder = [],
  providerOptions = [],
  onProviderOrderChange,
  disabled = [],
  onDisabledChange,
  audioLanguageOrder = [],
  subtitleLanguageOrder = [],
  onAudioLanguageOrderChange,
  onSubtitleLanguageOrderChange,
}) => {
  const ranking = useMemo(() => normalizeVODFailoverRanking(value), [value]);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  const moveCriterion = ({ active, over }) => {
    if (!over || active.id === over.id) return;
    const oldIndex = ranking.indexOf(active.id);
    const newIndex = ranking.indexOf(over.id);
    if (oldIndex < 0 || newIndex < 0) return;
    onChange(arrayMove(ranking, oldIndex, newIndex));
  };

  const changeDirection = (current, next) => {
    if (!next || current === next) return;
    onChange(
      ranking.map((criterion) => (criterion === current ? next : criterion))
    );
  };

  const toggleCriterion = (criterion, enabled) => {
    const next = new Set(disabled);
    if (enabled) next.delete(criterion);
    else next.add(criterion);
    onDisabledChange?.([...next]);
  };

  return (
    <Stack gap="xs">
      <Stack gap={0}>
        <Text fw={500}>Failover priority</Text>
        <Text size="sm" c="dimmed">
          Drag criteria into priority order. Categories remain access boundaries
          and are deliberately not used for failover ranking.
        </Text>
      </Stack>
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        modifiers={[restrictToVerticalAxis]}
        onDragEnd={moveCriterion}
      >
        <SortableContext items={ranking} strategy={verticalListSortingStrategy}>
          <Stack gap="sm">
            {ranking.map((criterion) => (
              <SortableCriterion
                key={criterion}
                criterion={criterion}
                onDirectionChange={(next) => changeDirection(criterion, next)}
                providerOrder={providerOrder}
                providerOptions={providerOptions}
                onProviderOrderChange={onProviderOrderChange}
                enabled={!disabled.includes(criterion)}
                onEnabledChange={(enabled) =>
                  toggleCriterion(criterion, enabled)
                }
                languageOrder={
                  criterion === 'audio_language'
                    ? audioLanguageOrder
                    : subtitleLanguageOrder
                }
                onLanguageOrderChange={
                  criterion === 'audio_language'
                    ? onAudioLanguageOrderChange
                    : onSubtitleLanguageOrderChange
                }
              />
            ))}
          </Stack>
        </SortableContext>
      </DndContext>
    </Stack>
  );
};

export default VODFailoverRanking;
