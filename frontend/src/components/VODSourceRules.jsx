import React, { useState } from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  Group,
  Loader,
  Modal,
  NumberInput,
  Paper,
  Progress,
  ScrollArea,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  TagsInput,
  Text,
  TextInput,
  Tooltip,
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
import { Eye, GripVertical, Info, Pencil, Plus, Trash2 } from 'lucide-react';
import LanguagePicker from './LanguagePicker.jsx';
import VideoFeaturePicker from './VideoFeaturePicker.jsx';
import VODSourcePreviewTable from './VODSourcePreviewTable.jsx';
import API from '../api.js';

const RULE_DEFAULTS = {
  match_field: 'stream',
  regex_pattern: '',
  case_sensitive: false,
  enabled: true,
  required_audio_languages: [],
  required_subtitle_languages: [],
  required_video_features: [],
  min_resolution: 0,
  max_resolution: 0,
  required_genres: [],
  required_keywords: [],
  required_countries: [],
  required_age_ratings: [],
  anime_mode: 'any',
  adult_mode: 'any',
  metadata_mode: 'any',
  tmdb_mode: 'any',
  result: 'include',
};

const createRule = () => ({
  ...RULE_DEFAULTS,
  id: `rule-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
});

const normalizeRule = (rule, index) => {
  const supportedRule = { ...(rule || {}) };
  for (const field of ['min_year', 'max_year', 'min_rating', 'max_rating']) {
    delete supportedRule[field];
  }
  return {
    ...RULE_DEFAULTS,
    ...supportedRule,
    id: supportedRule.id || `rule-${index}`,
    match_field: supportedRule.match_field || 'stream',
    regex_pattern:
      supportedRule.regex_pattern ?? supportedRule.category_regex ?? '',
    result: supportedRule.result || 'include',
  };
};

const joinValues = (values) => (values || []).join(', ');

const hasFilterCondition = (rule) =>
  Boolean(
    rule.regex_pattern ||
    rule.required_audio_languages?.length ||
    rule.required_subtitle_languages?.length ||
    rule.required_video_features?.length ||
    rule.min_resolution ||
    rule.max_resolution ||
    rule.required_genres?.length ||
    rule.required_keywords?.length ||
    rule.required_countries?.length ||
    rule.required_age_ratings?.length ||
    rule.anime_mode !== 'any' ||
    rule.adult_mode !== 'any' ||
    rule.metadata_mode !== 'any' ||
    rule.tmdb_mode !== 'any'
  );

const ruleSummary = (rule) => {
  const conditions = [];
  if (rule.regex_pattern) conditions.push('Legacy title/category expression');
  if (rule.required_audio_languages?.length) {
    conditions.push(
      `DUB contains ${joinValues(rule.required_audio_languages)}`
    );
  }
  if (rule.required_subtitle_languages?.length) {
    conditions.push(
      `SUB contains ${joinValues(rule.required_subtitle_languages)}`
    );
  }
  if (rule.required_video_features?.length) {
    conditions.push(
      `Features contain ${joinValues(rule.required_video_features)}`
    );
  }
  if (rule.min_resolution || rule.max_resolution) {
    conditions.push(
      `Resolution ${rule.min_resolution || 'any'}–${rule.max_resolution || 'any'}p`
    );
  }
  for (const [field, label] of [
    ['required_genres', 'Genre'],
    ['required_keywords', 'Keywords'],
    ['required_countries', 'Country'],
    ['required_age_ratings', 'Age rating'],
  ]) {
    if (rule[field]?.length) {
      conditions.push(`${label} contains ${joinValues(rule[field])}`);
    }
  }
  if (rule.anime_mode !== 'any') conditions.push(`Anime is ${rule.anime_mode}`);
  if (rule.adult_mode !== 'any') conditions.push(`Adult is ${rule.adult_mode}`);
  if (rule.metadata_mode !== 'any') {
    conditions.push(`Content metadata is ${rule.metadata_mode}`);
  }
  if (rule.tmdb_mode !== 'any') {
    conditions.push(`TMDB ID is ${rule.tmdb_mode}`);
  }
  return conditions.length ? conditions : ['All content'];
};

const FilterLabel = ({ children, tooltip }) => (
  <Group gap={5} wrap="nowrap">
    <span>{children}</span>
    <Tooltip label={tooltip} multiline maw={330} withArrow>
      <Info size={14} aria-label={`About ${children}`} />
    </Tooltip>
  </Group>
);

const SortableRuleCard = ({ ruleId, children }) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: ruleId });
  return (
    <Paper
      ref={setNodeRef}
      withBorder
      p="sm"
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.65 : 1,
        position: 'relative',
        zIndex: isDragging ? 2 : 0,
      }}
    >
      <Group align="flex-start" wrap="nowrap">
        <ActionIcon
          aria-label="Move content filter"
          variant="subtle"
          color="gray"
          style={{ cursor: isDragging ? 'grabbing' : 'grab' }}
          {...attributes}
          {...listeners}
        >
          <GripVertical size={16} />
        </ActionIcon>
        <Box style={{ flex: 1, minWidth: 0 }}>{children}</Box>
      </Group>
    </Paper>
  );
};

const VODSourceRules = ({
  value = [],
  onChange,
  categoryRelationIds = [],
  defaultAction = 'include',
  onDefaultActionChange,
  onOpenDetails,
}) => {
  const [previewOpened, setPreviewOpened] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const [preview, setPreview] = useState({ count: 0, results: [] });
  const [previewElapsed, setPreviewElapsed] = useState(0);
  const [editorOpened, setEditorOpened] = useState(false);
  const [editorRule, setEditorRule] = useState(createRule());
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );
  const normalized = value.map(normalizeRule);

  const update = (id, changes) =>
    onChange(
      normalized.map((rule) =>
        rule.id === id ? { ...rule, ...changes } : rule
      )
    );
  const remove = (id) => onChange(normalized.filter((rule) => rule.id !== id));
  const reorder = ({ active, over }) => {
    if (!over || active.id === over.id) return;
    const from = normalized.findIndex((rule) => rule.id === active.id);
    const to = normalized.findIndex((rule) => rule.id === over.id);
    if (from >= 0 && to >= 0) onChange(arrayMove(normalized, from, to));
  };
  const openNewRule = () => {
    setEditorRule(createRule());
    setEditorOpened(true);
  };
  const openRule = (rule) => {
    setEditorRule({ ...rule });
    setEditorOpened(true);
  };
  const saveRule = () => {
    if (normalized.some((rule) => rule.id === editorRule.id)) {
      update(editorRule.id, editorRule);
    } else {
      onChange([...normalized, editorRule]);
    }
    setEditorOpened(false);
  };
  const editorInvalid = Boolean(
    !hasFilterCondition(editorRule) ||
    (editorRule.min_resolution &&
      editorRule.max_resolution &&
      Number(editorRule.min_resolution) > Number(editorRule.max_resolution))
  );

  const previewRule = async (ruleId, sourceRules = normalized) => {
    setPreviewOpened(true);
    setPreviewLoading(true);
    setPreviewError('');
    setPreviewElapsed(0);
    setPreview({ count: 0, results: [] });
    try {
      setPreview(
        await API.previewVODAccessPolicyStreamFilter({
          source_rules: sourceRules,
          target_rule_id: ruleId,
          category_relation_ids: categoryRelationIds,
          restrict_to_categories: true,
        })
      );
    } catch (error) {
      setPreviewError(error?.message || 'The filter preview could not load.');
    } finally {
      setPreviewLoading(false);
    }
  };

  React.useEffect(() => {
    if (!previewLoading) return undefined;
    const startedAt = Date.now();
    const timer = window.setInterval(
      () => setPreviewElapsed(Math.floor((Date.now() - startedAt) / 1000)),
      1000
    );
    return () => window.clearInterval(timer);
  }, [previewLoading]);
  const previewEditorRule = () => {
    const sourceRules = normalized.some((rule) => rule.id === editorRule.id)
      ? normalized.map((rule) =>
          rule.id === editorRule.id ? editorRule : rule
        )
      : [...normalized, editorRule];
    previewRule(editorRule.id, sourceRules);
  };

  return (
    <Stack>
      <Group justify="space-between" align="end" w="100%">
        <Stack gap={2}>
          <Text fw={700}>Content filters</Text>
          <Text size="xs" c="dimmed">
            Filled fields use AND. Multiple values inside one field use OR. The
            first matching filter decides the result. Preview evaluates the
            current draft without saving or rebuilding the profile.
          </Text>
        </Stack>
        <Group align="end">
          <Select
            label={
              <FilterLabel tooltip="Fallback used only when none of the enabled filters matches. Filters are evaluated from top to bottom.">
                Unmatched content
              </FilterLabel>
            }
            size="xs"
            w={170}
            data={[
              { value: 'include', label: 'Include' },
              { value: 'exclude', label: 'Exclude' },
            ]}
            value={defaultAction}
            onChange={(next) => onDefaultActionChange?.(next || 'include')}
          />
          <Button
            variant="default"
            size="xs"
            leftSection={<Plus size={14} />}
            onClick={openNewRule}
          >
            Add filter
          </Button>
        </Group>
      </Group>

      {!normalized.length ? (
        <Alert color="gray">
          No content filters configured. The unmatched-content setting is only
          applied after the first filter is added.
        </Alert>
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          modifiers={[restrictToVerticalAxis]}
          onDragEnd={reorder}
        >
          <SortableContext
            items={normalized.map((rule) => rule.id)}
            strategy={verticalListSortingStrategy}
          >
            <Stack gap="xs">
              {normalized.map((rule, index) => (
                <SortableRuleCard key={rule.id} ruleId={rule.id}>
                  <Group
                    justify="space-between"
                    align="flex-start"
                    wrap="nowrap"
                  >
                    <Stack gap={4}>
                      <Group gap="xs" align="flex-start">
                        <Badge color="gray" variant="light">
                          #{index + 1}
                        </Badge>
                        <Badge
                          color={rule.result === 'exclude' ? 'red' : 'green'}
                          variant="light"
                        >
                          {rule.result}
                        </Badge>
                        {rule.enabled === false && (
                          <Badge color="gray" variant="light">
                            Disabled
                          </Badge>
                        )}
                      </Group>
                      <Text size="sm" fw={600}>
                        {ruleSummary(rule).join(' · ')}
                      </Text>
                    </Stack>
                    <Group gap={4} wrap="nowrap">
                      <Tooltip label="Edit filter">
                        <ActionIcon
                          aria-label="Edit content filter"
                          variant="subtle"
                          onClick={() => openRule(rule)}
                        >
                          <Pencil size={15} />
                        </ActionIcon>
                      </Tooltip>
                      <Tooltip label="Preview this draft filter">
                        <ActionIcon
                          aria-label="Preview content filters"
                          color="green"
                          variant="subtle"
                          onClick={() => previewRule(rule.id)}
                        >
                          <Eye size={15} />
                        </ActionIcon>
                      </Tooltip>
                      <ActionIcon
                        aria-label="Delete content filter"
                        color="red"
                        variant="subtle"
                        onClick={() => remove(rule.id)}
                      >
                        <Trash2 size={15} />
                      </ActionIcon>
                    </Group>
                  </Group>
                </SortableRuleCard>
              ))}
            </Stack>
          </SortableContext>
        </DndContext>
      )}

      <Modal
        opened={editorOpened}
        onClose={() => setEditorOpened(false)}
        title="Content filter"
        size="xl"
      >
        <Stack>
          <Group justify="space-between" align="end">
            <Select
              label={
                <FilterLabel tooltip="This action is applied only when every filled field in this filter matches.">
                  Result
                </FilterLabel>
              }
              data={[
                { value: 'include', label: 'Include' },
                { value: 'exclude', label: 'Exclude' },
              ]}
              value={editorRule.result}
              onChange={(result) =>
                setEditorRule((current) => ({
                  ...current,
                  result: result || 'include',
                }))
              }
            />
            <Switch
              label="Enabled"
              checked={editorRule.enabled !== false}
              onChange={(event) =>
                setEditorRule((current) => ({
                  ...current,
                  enabled: event.currentTarget.checked,
                }))
              }
            />
          </Group>

          <Text fw={600}>Source metadata</Text>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <VideoFeaturePicker
              label={
                <FilterLabel tooltip="Matches when the source has at least one selected feature. Selected values are alternatives (OR).">
                  Features contain
                </FilterLabel>
              }
              value={editorRule.required_video_features || []}
              onChange={(required_video_features) =>
                setEditorRule((current) => ({
                  ...current,
                  required_video_features,
                }))
              }
            />
            <LanguagePicker
              label={
                <FilterLabel tooltip="Matches when the source has at least one selected audio language. Selected languages are alternatives (OR).">
                  DUB contains
                </FilterLabel>
              }
              value={editorRule.required_audio_languages || []}
              onChange={(required_audio_languages) =>
                setEditorRule((current) => ({
                  ...current,
                  required_audio_languages,
                }))
              }
            />
            <LanguagePicker
              label={
                <FilterLabel tooltip="Matches when the source has at least one selected subtitle language. Selected languages are alternatives (OR).">
                  SUB contains
                </FilterLabel>
              }
              value={editorRule.required_subtitle_languages || []}
              onChange={(required_subtitle_languages) =>
                setEditorRule((current) => ({
                  ...current,
                  required_subtitle_languages,
                }))
              }
            />
            <NumberInput
              label={
                <FilterLabel tooltip="Matches sources whose known vertical resolution is at least this value. Sources without a resolution do not match.">
                  Minimum resolution
                </FilterLabel>
              }
              min={0}
              step={240}
              suffix="p"
              placeholder="No minimum"
              value={editorRule.min_resolution || ''}
              onChange={(min_resolution) =>
                setEditorRule((current) => ({ ...current, min_resolution }))
              }
            />
            <NumberInput
              label={
                <FilterLabel tooltip="Matches sources whose known vertical resolution is at most this value. Sources without a resolution do not match.">
                  Maximum resolution
                </FilterLabel>
              }
              min={0}
              step={240}
              suffix="p"
              placeholder="No maximum"
              value={editorRule.max_resolution || ''}
              onChange={(max_resolution) =>
                setEditorRule((current) => ({ ...current, max_resolution }))
              }
            />
          </SimpleGrid>

          {editorRule.regex_pattern && (
            <Alert color="yellow">
              <TextInput
                label="Legacy regular expression"
                description="This existing expression remains active for compatibility. New filters use metadata conditions only."
                value={editorRule.regex_pattern}
                onChange={(event) =>
                  setEditorRule((current) => ({
                    ...current,
                    regex_pattern: event.currentTarget.value,
                  }))
                }
              />
            </Alert>
          )}

          <Text fw={600}>Content metadata</Text>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TagsInput
              label={
                <FilterLabel tooltip="Enter genre names such as Horror or Animation. A title matches at least one entered genre (OR).">
                  Genre contains
                </FilterLabel>
              }
              placeholder="e.g. Horror, Animation"
              value={editorRule.required_genres || []}
              onChange={(required_genres) =>
                setEditorRule((current) => ({ ...current, required_genres }))
              }
              splitChars={[',']}
              clearable
            />
            <TagsInput
              label={
                <FilterLabel tooltip="Enter canonical TMDB keywords. A title matches at least one entered keyword (OR).">
                  Keywords contain
                </FilterLabel>
              }
              placeholder="e.g. time travel, superhero"
              value={editorRule.required_keywords || []}
              onChange={(required_keywords) =>
                setEditorRule((current) => ({ ...current, required_keywords }))
              }
              splitChars={[',']}
              clearable
            />
            <TagsInput
              label={
                <FilterLabel tooltip="Enter stored production-country names or codes. A title matches at least one entered value (OR).">
                  Country contains
                </FilterLabel>
              }
              placeholder="e.g. Germany, US"
              value={editorRule.required_countries || []}
              onChange={(required_countries) =>
                setEditorRule((current) => ({ ...current, required_countries }))
              }
              splitChars={[',']}
              clearable
            />
            <TagsInput
              label={
                <FilterLabel tooltip="Enter the stored certification exactly as supplied, for example FSK 6, 6, PG-13, or TV-MA. Values are alternatives (OR).">
                  Age rating contains
                </FilterLabel>
              }
              placeholder="e.g. FSK 6, PG-13"
              value={editorRule.required_age_ratings || []}
              onChange={(required_age_ratings) =>
                setEditorRule((current) => ({
                  ...current,
                  required_age_ratings,
                }))
              }
              splitChars={[',']}
              clearable
            />
            <Select
              label={
                <FilterLabel tooltip="Uses the canonical Anime flag, normally derived from TMDB keywords and still manually editable.">
                  Anime
                </FilterLabel>
              }
              data={[
                { value: 'any', label: 'Any' },
                { value: 'yes', label: 'Yes' },
                { value: 'no', label: 'No' },
              ]}
              value={editorRule.anime_mode || 'any'}
              onChange={(anime_mode) =>
                setEditorRule((current) => ({
                  ...current,
                  anime_mode: anime_mode || 'any',
                }))
              }
            />
            <Select
              label={
                <FilterLabel tooltip="Uses the canonical adult-content flag from provider data, TMDB, or a manual override.">
                  Adult content
                </FilterLabel>
              }
              data={[
                { value: 'any', label: 'Any' },
                { value: 'yes', label: 'Yes' },
                { value: 'no', label: 'No' },
              ]}
              value={editorRule.adult_mode || 'any'}
              onChange={(adult_mode) =>
                setEditorRule((current) => ({
                  ...current,
                  adult_mode: adult_mode || 'any',
                }))
              }
            />
            <Select
              label={
                <FilterLabel tooltip="Content metadata is the shared title-level information such as descriptions, genres, keywords, cast, artwork, and external IDs. Missing means that no TMDB or manual content record is stored; provider-source fields alone do not count.">
                  Content metadata
                </FilterLabel>
              }
              data={[
                { value: 'any', label: 'Any' },
                { value: 'available', label: 'Available' },
                { value: 'missing', label: 'Missing' },
              ]}
              value={editorRule.metadata_mode || 'any'}
              onChange={(metadata_mode) =>
                setEditorRule((current) => ({
                  ...current,
                  metadata_mode: metadata_mode || 'any',
                }))
              }
            />
            <Select
              label={
                <FilterLabel tooltip="Checks only whether the canonical title has a TMDB ID. It does not target one specific film or series ID.">
                  TMDB ID
                </FilterLabel>
              }
              data={[
                { value: 'any', label: 'Any' },
                { value: 'available', label: 'Available' },
                { value: 'missing', label: 'Missing' },
              ]}
              value={editorRule.tmdb_mode || 'any'}
              onChange={(tmdb_mode) =>
                setEditorRule((current) => ({
                  ...current,
                  tmdb_mode: tmdb_mode || 'any',
                }))
              }
            />
          </SimpleGrid>

          {Boolean(
            editorRule.min_resolution &&
            editorRule.max_resolution &&
            Number(editorRule.min_resolution) >
              Number(editorRule.max_resolution)
          ) && (
            <Alert color="red">
              A minimum cannot be greater than its maximum.
            </Alert>
          )}
          <Group justify="space-between">
            <Button
              variant="light"
              leftSection={<Eye size={15} />}
              disabled={editorInvalid}
              onClick={previewEditorRule}
            >
              Preview draft
            </Button>
            <Group>
              <Button variant="default" onClick={() => setEditorOpened(false)}>
                Cancel
              </Button>
              <Button disabled={editorInvalid} onClick={saveRule}>
                Save filter
              </Button>
            </Group>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={previewOpened}
        onClose={() => setPreviewOpened(false)}
        title="Content filter preview"
        size="xl"
      >
        <Stack>
          <Text size="sm" c="dimmed">
            The ordered draft is applied to the sources allowed in this profile.
            Only sources for which this filter is the first match are shown.
          </Text>
          {previewLoading && (
            <Stack gap="xs" py="xl">
              <Group justify="center" gap="xs">
                <Loader size="sm" />
                <Text size="sm" fw={600}>
                  Applying the ordered filters to the selected provider sources
                </Text>
              </Group>
              <Progress value={100} animated striped />
              <Text size="xs" c="dimmed" ta="center">
                Reading source and content metadata · {previewElapsed}s elapsed
              </Text>
            </Stack>
          )}
          {previewError && <Alert color="red">{previewError}</Alert>}
          {!previewLoading && !previewError && (
            <>
              <Text fw={600}>
                {preview.truncated
                  ? `${preview.count || 0}+ matching sources (first 200 shown)`
                  : `${preview.count || 0} matching sources`}
              </Text>
              <Text size="xs" c="dimmed">
                Examined {preview.inventory_count || 0} sources from the
                currently selected provider categories.
              </Text>
              <ScrollArea h="min(62vh, 620px)" type="auto">
                <VODSourcePreviewTable
                  rows={preview.results || []}
                  getRowKey={(row) => `${row.content_type}-${row.id}`}
                  getProviderTitle={(row) => row.provider_title || row.title}
                  getCanonicalTitle={(row) => row.canonical_title}
                  getProviderName={(row) => row.m3u_account_name}
                  getCategoryName={(row) => row.category_name}
                  onOpenDetails={onOpenDetails}
                  emptyText="No source has this filter as its first match."
                  minWidth={760}
                />
              </ScrollArea>
            </>
          )}
        </Stack>
      </Modal>
    </Stack>
  );
};

export default VODSourceRules;
