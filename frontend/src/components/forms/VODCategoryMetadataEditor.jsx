import { useState } from 'react';
import {
  ActionIcon,
  Button,
  Checkbox,
  Group,
  Modal,
  ScrollArea,
  Select,
  Stack,
  Text,
  TextInput,
} from '@mantine/core';
import { Plus } from 'lucide-react';

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
  pickerStackId,
  onApply,
  onClose,
}) => {
  const [draft, setDraft] = useState(value);
  const [picker, setPicker] = useState(null);
  const [pending, setPending] = useState([]);
  const [query, setQuery] = useState('');
  const [custom, setCustom] = useState('');
  const isLanguage = picker !== 'video_features';

  const labelFor = (field, code) =>
    field === 'video_features'
      ? featureLabel(code)
      : languages.find((option) => option.value === code)?.label ||
        code.toUpperCase();

  const openPicker = (field) => {
    setPending(draft[field]);
    setQuery('');
    setCustom('');
    setPicker(field);
  };

  const toggle = (code) =>
    setPending((current) =>
      current.includes(code)
        ? current.filter((item) => item !== code)
        : [...current, code]
    );

  const choices = isLanguage
    ? languages.filter((option) =>
        `${option.label} ${option.value} ${option.legacyValue || ''}`
          .toLowerCase()
          .includes(query.trim().toLowerCase())
      )
    : [
        ...FEATURE_OPTIONS,
        ...pending
          .filter((feature) => feature.startsWith('custom:'))
          .map((feature) => ({ value: feature, label: featureLabel(feature) })),
      ];

  const addCustom = () => {
    const feature = customFeature(custom);
    if (feature) setPending((current) => [...new Set([...current, feature])]);
    setCustom('');
  };

  const pickerField = (field) => (
    <Stack gap={5}>
      <Text size="sm" fw={500}>
        {FIELD_LABELS[field]}
      </Text>
      <Group
        gap={5}
        p={5}
        wrap="nowrap"
        style={{
          border: '1px solid var(--mantine-color-default-border)',
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
                  setDraft((current) => ({
                    ...current,
                    [field]: current[field].filter((item) => item !== code),
                  }))
                }
              >
                {field === 'video_features' ? labelFor(field, code) : code} ×
              </Button>
            ))
          ) : (
            <Text size="sm" c="dimmed">
              Not specified
            </Text>
          )}
        </Group>
        <ActionIcon
          type="button"
          variant="subtle"
          aria-label={`Choose ${FIELD_LABELS[field]}`}
          onClick={() => openPicker(field)}
        >
          <Plus size={16} />
        </ActionIcon>
      </Group>
    </Stack>
  );

  const resolutionOptions =
    resolutions.includes(draft.resolution) || !draft.resolution
      ? resolutions
      : [...resolutions, draft.resolution];

  return (
    <>
      <Stack>
        <Text size="sm" c="dimmed">
          Import defaults only. Provider, observed and manual source metadata
          take priority.
        </Text>
        {pickerField('audio_languages')}
        {pickerField('subtitle_languages')}
        <Select
          label="Resolution"
          placeholder="Not specified"
          data={resolutionOptions}
          value={draft.resolution || null}
          onChange={(resolution) =>
            setDraft((current) => ({
              ...current,
              resolution: resolution || '',
            }))
          }
          clearable
          comboboxProps={{ keepMounted: false }}
        />
        {pickerField('video_features')}
        <Group justify="flex-end">
          <Button type="button" variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" onClick={() => onApply(draft)}>
            Apply
          </Button>
        </Group>
      </Stack>
      <Modal
        stackId={pickerStackId}
        opened={Boolean(picker)}
        onClose={() => setPicker(null)}
        title={`Select ${FIELD_LABELS[picker]}`}
        closeButtonProps={{ 'aria-label': 'Close metadata selection' }}
        size="md"
      >
        <Stack>
          {isLanguage && (
            <>
              <TextInput
                aria-label="Search languages"
                placeholder="Search languages by name or code"
                value={query}
                onChange={(event) => setQuery(event.currentTarget.value)}
              />
            </>
          )}
          <ScrollArea h={260} type="auto">
            <Stack gap={2}>
              {choices.map((option) => (
                <Checkbox
                  key={option.value}
                  label={option.label}
                  checked={pending.includes(option.value)}
                  onChange={() => toggle(option.value)}
                  py={5}
                />
              ))}
              {!choices.length && (
                <Text size="sm" c="dimmed">
                  No languages found
                </Text>
              )}
            </Stack>
          </ScrollArea>
          {!isLanguage && (
            <Group align="flex-end" wrap="nowrap">
              <TextInput
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
                type="button"
                variant="default"
                disabled={!customFeature(custom)}
                onClick={addCustom}
              >
                Add
              </Button>
            </Group>
          )}
          <Group justify="flex-end">
            <Button
              type="button"
              variant="default"
              onClick={() => setPicker(null)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              onClick={() => {
                setDraft((current) => ({ ...current, [picker]: pending }));
                setPicker(null);
              }}
            >
              Apply selection
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
};

export default VODCategoryMetadataEditor;
