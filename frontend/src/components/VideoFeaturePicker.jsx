import React, { useMemo, useState } from 'react';
import {
  ActionIcon,
  Box,
  Button,
  Checkbox,
  Group,
  Modal,
  Stack,
  Text,
  TextInput,
} from '@mantine/core';
import { Plus } from 'lucide-react';
import {
  VIDEO_FEATURE_OPTIONS,
  videoFeatureLabel,
} from '../utils/vodMetadataOptions.js';

const normalizeFeature = (value) => {
  const raw = String(value || '')
    .trim()
    .toLowerCase();
  if (!raw) return '';
  if (['3d', 'hdr', 'dv'].includes(raw)) return raw;
  const slug = raw
    .replace(/^custom:/, '')
    .replace(/[^a-z0-9._-]+/g, '-')
    .replace(/^[-._]+|[-._]+$/g, '');
  return slug ? `custom:${slug}` : '';
};

const normalizeFeatures = (values) => [
  ...new Set((values || []).map(normalizeFeature).filter(Boolean)),
];

const VideoFeaturePicker = ({
  label = 'Video features',
  value = [],
  onChange,
  disabled = false,
  size,
  description,
  emptyLabel = 'No features selected',
}) => {
  const normalized = useMemo(() => normalizeFeatures(value), [value]);
  const [opened, setOpened] = useState(false);
  const [pending, setPending] = useState([]);
  const [custom, setCustom] = useState('');

  const openPicker = () => {
    setPending(normalized);
    setCustom('');
    setOpened(true);
  };
  const toggle = (feature) =>
    setPending((current) =>
      current.includes(feature)
        ? current.filter((item) => item !== feature)
        : [...current, feature]
    );
  const addCustom = () => {
    const feature = normalizeFeature(custom);
    if (!feature) return;
    setPending((current) =>
      current.includes(feature) ? current : [...current, feature]
    );
    setCustom('');
  };

  return (
    <Stack gap={5}>
      {label && (
        <Stack gap={0}>
          <Text component="label" size={size === 'xs' ? 'xs' : 'sm'} fw={500}>
            {label}
          </Text>
          {description && (
            <Text size="xs" c="dimmed">
              {description}
            </Text>
          )}
        </Stack>
      )}
      <Box
        style={{
          minHeight: size === 'xs' ? 30 : 36,
          border: '1px solid var(--mantine-color-default-border)',
          borderRadius: 'var(--mantine-radius-default)',
          background: 'var(--mantine-color-default)',
          display: 'flex',
          alignItems: 'center',
          overflow: 'hidden',
        }}
      >
        <Group gap={5} px="xs" py={3} style={{ flex: 1, minWidth: 0 }}>
          {normalized.length ? (
            normalized.map((feature) => (
              <Button
                key={feature}
                aria-label={`Remove ${videoFeatureLabel(feature)}`}
                variant="light"
                color="gray"
                size="compact-xs"
                disabled={disabled}
                onClick={() =>
                  onChange?.(
                    normalized.filter((current) => current !== feature)
                  )
                }
              >
                {videoFeatureLabel(feature)} ×
              </Button>
            ))
          ) : (
            <Text size={size === 'xs' ? 'xs' : 'sm'} c="dimmed">
              {emptyLabel}
            </Text>
          )}
        </Group>
        <ActionIcon
          aria-label={label ? `Add ${label}` : 'Add video feature'}
          disabled={disabled}
          size={size === 'xs' ? 28 : 32}
          m={2}
          variant="subtle"
          onClick={openPicker}
        >
          <Plus size={15} />
        </ActionIcon>
      </Box>
      <Modal
        opened={opened}
        onClose={() => setOpened(false)}
        title={label || 'Select video features'}
        size="md"
      >
        <Stack>
          {VIDEO_FEATURE_OPTIONS.map((option) => (
            <Checkbox
              key={option.value}
              label={option.label}
              checked={pending.includes(option.value)}
              onChange={() => toggle(option.value)}
            />
          ))}
          <Group align="flex-end" wrap="nowrap">
            <TextInput
              label="Custom tag"
              description="Stored as a reusable custom feature filter."
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
              variant="default"
              onClick={addCustom}
              disabled={!custom.trim()}
            >
              Add
            </Button>
          </Group>
          {pending
            .filter((feature) => feature.startsWith('custom:'))
            .map((feature) => (
              <Checkbox
                key={feature}
                label={videoFeatureLabel(feature)}
                checked
                onChange={() => toggle(feature)}
              />
            ))}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setOpened(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                onChange?.(normalizeFeatures(pending));
                setOpened(false);
              }}
            >
              Apply
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
};

export default VideoFeaturePicker;
