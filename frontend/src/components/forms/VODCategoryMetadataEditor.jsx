import { useEffect, useState } from 'react';
import {
  ActionIcon,
  Button,
  Checkbox,
  Group,
  Paper,
  Popover,
  ScrollArea,
  Select,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { Eraser, Plus } from 'lucide-react';

const FEATURE_OPTIONS = [
  { value: '3d', label: '3D' },
  { value: 'hdr', label: 'HDR' },
  { value: 'dv', label: 'Dolby Vision' },
];

const FIELD_LABELS = {
  audio_languages: 'DUB languages',
  subtitle_languages: 'SUB languages',
  video_features: 'Video features',
};

const featureLabel = (value) =>
  FEATURE_OPTIONS.find((option) => option.value === value)?.label ||
  value.replace(/^custom:/, '');

const customFeature = (value) => {
  const slug = value
    .trim()
    .toLowerCase()
    .replace(/^custom:/, '')
    .replace(/[^a-z0-9._-]+/g, '-')
    .replace(/^[-._]+|[-._]+$/g, '');
  return slug
    ? FEATURE_OPTIONS.some((option) => option.value === slug)
      ? slug
      : `custom:${slug}`
    : '';
};

const VODCategoryMetadataEditor = ({
  value,
  languages,
  resolutions,
  onApply,
  bulk = false,
  ruleMode = false,
  sourceMode = false,
  onDirtyChange,
  applyLabel,
  disabled = false,
  invalidFields = [],
  children,
}) => {
  const [draft, setDraft] = useState({
    audio_languages: [],
    subtitle_languages: [],
    resolution: '',
    video_features: [],
    ...value,
  });
  const [picker, setPicker] = useState(null);
  const [query, setQuery] = useState('');
  const [custom, setCustom] = useState('');
  const [modes, setModes] = useState(
    ruleMode
      ? Object.fromEntries(Object.keys(value).map((key) => [key, 'replace']))
      : {}
  );
  const [resolutionError, setResolutionError] = useState(false);
  const isLanguage = picker !== 'video_features';
  const direct = bulk || ruleMode;
  const initialDraft = JSON.stringify({
    audio_languages: [],
    subtitle_languages: [],
    resolution: '',
    video_features: [],
    ...value,
  });

  useEffect(() => {
    onDirtyChange?.(
      direct
        ? Object.values(modes).some((mode) => mode !== 'keep')
        : JSON.stringify(draft) !== initialDraft
    );
  }, [modes, draft, direct, initialDraft, onDirtyChange]);

  const labelFor = (field, code) =>
    field === 'video_features'
      ? featureLabel(code)
      : languages.find((option) => option.value === code)?.label ||
        code.toUpperCase();

  const updateField = (field, nextValue) => {
    setDraft((current) => ({ ...current, [field]: nextValue }));
    if (bulk)
      setModes((current) => ({
        ...current,
        [field]: sourceMode || nextValue?.length ? 'replace' : 'reset',
      }));
    else if (ruleMode)
      setModes((current) => ({
        ...current,
        [field]: field === 'resolution' && !nextValue ? 'keep' : 'replace',
      }));
  };

  const fieldHeading = (label) => (
    <Text size="sm" fw={500}>
      {label}
    </Text>
  );

  const clearToggle = (field, label) => {
    const clearing = bulk && modes[field] === 'reset';
    const action = ruleMode
      ? `Do not set ${label} with this rule`
      : clearing
        ? `Keep ${label} unchanged`
        : sourceMode
          ? `Reset ${label} override`
          : `Clear ${label} defaults`;
    return (
      <Tooltip
        label={action}
        withArrow
        events={{ hover: true, focus: true, touch: true }}
      >
        <ActionIcon
          type="button"
          variant={clearing ? 'light' : 'subtle'}
          color={clearing ? 'red' : 'gray'}
          size="input-sm"
          aria-label={action}
          aria-pressed={bulk ? clearing : undefined}
          disabled={
            (ruleMode && modes[field] !== 'replace') ||
            (!direct && !draft[field]?.length)
          }
          onClick={() => {
            if (ruleMode || clearing) {
              setModes((current) => ({ ...current, [field]: 'keep' }));
              setDraft((current) => ({
                ...current,
                [field]: field === 'resolution' ? '' : [],
              }));
            } else {
              updateField(field, field === 'resolution' ? '' : []);
              if (sourceMode)
                setModes((current) => ({ ...current, [field]: 'reset' }));
            }
          }}
        >
          <Eraser size={16} aria-hidden="true" />
        </ActionIcon>
      </Tooltip>
    );
  };

  const emptyLabel = (field) =>
    ruleMode
      ? modes[field] === 'replace'
        ? 'Empty default'
        : 'Not set by this rule'
      : bulk
        ? modes[field] === 'reset'
          ? sourceMode
            ? 'Inherit'
            : 'Clear'
          : 'Keep unchanged'
        : 'Not specified';

  const openPicker = (field) => {
    setQuery('');
    setCustom('');
    setPicker(field);
  };

  const toggle = (code) =>
    updateField(
      picker,
      draft[picker].includes(code)
        ? draft[picker].filter((item) => item !== code)
        : [...draft[picker], code]
    );

  const choices = (
    isLanguage
      ? languages
      : [
          ...FEATURE_OPTIONS,
          ...(draft.video_features || [])
            .filter((feature) => feature.startsWith('custom:'))
            .map((feature) => ({
              value: feature,
              label: featureLabel(feature),
            })),
        ]
  ).filter((option) =>
    `${option.label} ${option.value} ${option.legacyValue || ''}`
      .toLowerCase()
      .includes(query.trim().toLowerCase())
  );

  const addCustom = () => {
    const feature = customFeature(custom);
    if (feature)
      updateField('video_features', [
        ...new Set([...draft.video_features, feature]),
      ]);
    setCustom('');
  };

  const pickerField = (field) => (
    <Stack gap={5}>
      {fieldHeading(FIELD_LABELS[field])}
      <Group gap="xs" wrap="nowrap" align="flex-start">
        <Group
          gap={5}
          p={3}
          pl="xs"
          mih={36}
          wrap="nowrap"
          style={{
            flex: 1,
            minWidth: 0,
            border: `1px solid ${invalidFields.includes(field) ? 'var(--mantine-color-red-6)' : direct && modes[field] && modes[field] !== 'keep' ? 'var(--mantine-color-blue-5)' : 'var(--mantine-color-default-border)'}`,
            borderRadius: 'var(--mantine-radius-default)',
            background: 'var(--mantine-color-default)',
          }}
        >
          <Group gap={5} style={{ flex: 1, minWidth: 0 }}>
            {draft[field].length ? (
              draft[field].map((code) => (
                <Button
                  key={code}
                  type="button"
                  variant="light"
                  color="gray"
                  size="compact-xs"
                  aria-label={`Remove ${labelFor(field, code)} from ${FIELD_LABELS[field]}`}
                  title={labelFor(field, code)}
                  onClick={() =>
                    updateField(
                      field,
                      draft[field].filter((item) => item !== code)
                    )
                  }
                >
                  {field === 'video_features' ? labelFor(field, code) : code} ×
                </Button>
              ))
            ) : (
              <Tooltip
                label="Explicitly empty: later rules cannot assign this field."
                disabled={!ruleMode || modes[field] !== 'replace'}
                withArrow
                events={{ hover: true, focus: true, touch: true }}
              >
                <Text
                  size="sm"
                  c="dimmed"
                  tabIndex={
                    ruleMode && modes[field] === 'replace' ? 0 : undefined
                  }
                  role={bulk && modes[field] === 'reset' ? 'status' : undefined}
                >
                  {emptyLabel(field)}
                </Text>
              </Tooltip>
            )}
          </Group>
          <Popover
            opened={picker === field}
            onChange={(opened) => !opened && setPicker(null)}
            position="bottom-end"
            width={320}
            withArrow
            withRoles={false}
            trapFocus
            returnFocus
            zIndex={10000}
          >
            <Popover.Target>
              <ActionIcon
                type="button"
                variant="subtle"
                size="sm"
                aria-label={`Choose ${FIELD_LABELS[field]}`}
                aria-expanded={picker === field}
                aria-haspopup="dialog"
                onClick={() =>
                  picker === field ? setPicker(null) : openPicker(field)
                }
              >
                <Plus size={16} />
              </ActionIcon>
            </Popover.Target>
            <Popover.Dropdown
              data-mantine-stop-propagation="true"
              role="dialog"
              aria-label={`Select ${FIELD_LABELS[field]}`}
              onKeyDown={(event) => {
                if (event.key === 'Escape') {
                  event.stopPropagation();
                  setPicker(null);
                }
              }}
            >
              {picker === field && pickerChoices}
            </Popover.Dropdown>
          </Popover>
        </Group>
        {clearToggle(field, FIELD_LABELS[field])}
      </Group>
    </Stack>
  );

  const resolutionOptions =
    resolutions.includes(draft.resolution) || !draft.resolution
      ? resolutions
      : [...resolutions, draft.resolution];

  const apply = () => {
    if (ruleMode && modes.resolution === 'replace' && !draft.resolution) {
      setResolutionError(true);
      return;
    }
    const values = { ...draft, resolution: draft.resolution || null };
    onApply(
      bulk || ruleMode
        ? Object.fromEntries(
            Object.entries(modes)
              .filter(([, mode]) => mode !== 'keep')
              .map(([field, mode]) => [
                field,
                mode === 'reset' ? null : values[field],
              ])
          )
        : draft
    );
  };

  const pickerChoices = (
    <Stack gap="sm">
      <TextInput
        data-mantine-stop-propagation="true"
        aria-label={isLanguage ? 'Search languages' : 'Search video features'}
        placeholder={
          isLanguage
            ? 'Search languages by name or code'
            : 'Search video features'
        }
        value={query}
        onChange={(event) => setQuery(event.currentTarget.value)}
        data-autofocus
      />
      <ScrollArea.Autosize mah={240} type="auto">
        <Stack gap={2}>
          {choices.map((option) => (
            <Checkbox
              data-mantine-stop-propagation="true"
              key={option.value}
              label={option.label}
              checked={draft[picker]?.includes(option.value) || false}
              onChange={() => toggle(option.value)}
              py={5}
            />
          ))}
          {!choices.length && (
            <Text size="sm" c="dimmed">
              No matches found
            </Text>
          )}
        </Stack>
      </ScrollArea.Autosize>
      {!isLanguage && (
        <Group align="flex-end" wrap="nowrap">
          <TextInput
            data-mantine-stop-propagation="true"
            label="Custom tag"
            placeholder="For example IMAX"
            value={custom}
            onChange={(event) => setCustom(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                addCustom();
              }
            }}
            style={{ flex: 1 }}
          />
          <Button
            data-mantine-stop-propagation="true"
            type="button"
            variant="default"
            disabled={!customFeature(custom)}
            onClick={addCustom}
          >
            Add
          </Button>
        </Group>
      )}
    </Stack>
  );

  const editorFields = (
    <>
      {pickerField('audio_languages')}
      {pickerField('subtitle_languages')}
      <Stack gap={5}>
        {fieldHeading('Resolution')}
        <Group gap="xs" wrap="nowrap" align="flex-start">
          <Select
            aria-label="Resolution"
            placeholder={emptyLabel('resolution')}
            style={{ flex: 1, minWidth: 0 }}
            data={resolutionOptions}
            value={draft.resolution || null}
            error={
              invalidFields.includes('resolution') || resolutionError
                ? 'Choose a resolution or leave this field unset.'
                : undefined
            }
            onChange={(resolution) => {
              setResolutionError(false);
              updateField('resolution', resolution || '');
            }}
            styles={
              !invalidFields.includes('resolution') &&
              direct &&
              modes.resolution &&
              modes.resolution !== 'keep'
                ? { input: { borderColor: 'var(--mantine-color-blue-5)' } }
                : undefined
            }
            comboboxProps={{ keepMounted: false }}
          />
          {clearToggle('resolution', 'Resolution')}
        </Group>
      </Stack>
      {pickerField('video_features')}
    </>
  );

  return (
    <>
      <Stack gap="sm">
        <Paper
          withBorder
          p="sm"
          role="group"
          aria-label="Category content settings"
        >
          <Stack gap="xs">
            <Text fw={600}>Metadata</Text>
            {editorFields}
          </Stack>
        </Paper>
        {children}
        <Group justify="flex-end">
          <Button type="button" onClick={apply} disabled={disabled}>
            {applyLabel || (bulk ? 'Apply to selected' : 'Apply')}
          </Button>
        </Group>
      </Stack>
    </>
  );
};

export default VODCategoryMetadataEditor;
