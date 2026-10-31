import { Badge, Group, Text, Tooltip } from '@mantine/core';
import {
  METADATA_ORIGINS,
  metadataFeatureLabel,
} from '../utils/libraryMetadataOrigins.js';
import classes from './LibraryWorkspace.module.css';

export default function MetadataOriginBadges({
  origins = {},
  field,
  size = 'sm',
}) {
  const entries = Object.entries(origins[field] || {});
  if (!entries.length)
    return (
      <Text c="dimmed" size="sm">
        —
      </Text>
    );
  return (
    <Group gap={4} className={classes.metadata}>
      {entries.map(([value, origin]) => {
        const meta = METADATA_ORIGINS[origin];
        return (
          <Tooltip key={value} label={meta?.label || 'Unspecified'} withArrow>
            <Badge
              color={meta?.color || 'gray'}
              variant="light"
              size={size}
              tabIndex={0}
              aria-label={`${value} · ${meta?.label || 'Unspecified'}`}
              className={
                field.includes('languages') ? classes.language : undefined
              }
            >
              {field === 'video_features' ? metadataFeatureLabel(value) : value}
            </Badge>
          </Tooltip>
        );
      })}
    </Group>
  );
}

export function MetadataOriginLegend() {
  return (
    <Group gap="xs" aria-label="Metadata origins">
      {Object.entries(METADATA_ORIGINS)
        // Series sources are an internal step and nothing reports playback yet.
        .filter(([origin]) => !['series', 'observed'].includes(origin))
        .map(([origin, { label, color }]) => (
          <Badge key={origin} color={color} variant="light" size="xs">
            {label}
          </Badge>
        ))}
    </Group>
  );
}
