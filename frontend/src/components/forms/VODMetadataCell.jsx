import { Badge, Text } from '@mantine/core';
import {
  metadataFieldItems,
  metadataFieldText,
} from '../../utils/vodSourceMetadata.js';
import classes from './VODMetadataCell.module.css';

export default function VODMetadataCell({
  values,
  field,
  title,
  emptyLabel = '—',
}) {
  const items = metadataFieldItems(values, field);
  const language =
    field === 'audio_languages' || field === 'subtitle_languages';
  const content = (
    <span className={classes.tags}>
      {items.length ? (
        items.map((item, index) => (
          <Badge
            key={`${item}-${index}`}
            size="sm"
            radius="sm"
            variant="light"
            color="gray"
            fw={400}
            tt="none"
            c="var(--mantine-color-text)"
            maw="100%"
            className={[classes.tag, language && classes.languageTag]
              .filter(Boolean)
              .join(' ')}
          >
            {item}
          </Badge>
        ))
      ) : (
        <Text component="span" size="xs" c="dimmed">
          {emptyLabel}
        </Text>
      )}
    </span>
  );
  const tooltip =
    title ||
    metadataFieldText(values, field) ||
    (emptyLabel === 'None' ? 'Explicitly empty default' : 'Not specified');
  return <span title={tooltip}>{content}</span>;
}
