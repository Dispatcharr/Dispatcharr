import { Group, Text, Tooltip } from '@mantine/core';
import { metadataSummary } from '../utils/vodSourceMetadata.js';

const LABELS = {
  audio_languages: 'DUB',
  subtitle_languages: 'SUB',
  resolution: 'Resolution',
  video_features: 'Features',
};
const ORIGINS = {
  category: 'Category default',
  series: 'Series source',
  provider: 'Provider',
  observed: 'Observed',
  manual: 'Manual override',
};

export default function VODSourceMetadata({ source }) {
  const metadata = source?.effective_metadata;
  const summary = metadataSummary(metadata?.values);
  if (!summary) return null;
  const details = Object.entries(metadata.values)
    .map(([field, value]) => {
      const origin = ORIGINS[metadata.provenance?.[field]] || 'Unspecified';
      return `${LABELS[field] || field}: ${Array.isArray(value) ? value.join(', ') || 'Not specified' : value} — ${origin}`;
    })
    .join('\n');
  return (
    <Group mt="xs" gap="xs">
      <Tooltip
        label={details}
        multiline
        maw={420}
        withArrow
        events={{ hover: true, focus: true, touch: true }}
      >
        <Text
          size="xs"
          c="dimmed"
          tabIndex={0}
          aria-label={`Selected source metadata: ${summary}`}
        >
          {summary}
        </Text>
      </Tooltip>
    </Group>
  );
}
