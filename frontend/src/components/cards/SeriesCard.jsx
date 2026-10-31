import {
  Box,
  Card,
  CardSection,
  Group,
  Image,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import { Play, Star } from 'lucide-react';
import React, { useState } from 'react';
import classes from '../VODLayout.module.css';
import { formatRating, vodLogoSrc } from '../../utils/cards/VODCardUtils.js';

const SeriesCard = ({ series, onClick, compact = false }) => {
  const posterSrc = vodLogoSrc(series.logo);
  const [failedPoster, setFailedPoster] = useState(null);
  const title = (
    <Text
      fw={600}
      size={compact ? 13 : 'sm'}
      lh={compact ? 1.4 : undefined}
      lineClamp={compact ? 1 : 2}
      title={compact ? undefined : series.name}
      className={classes.cardTitle}
    >
      {series.name}
    </Text>
  );
  return (
    <Card
      padding={0}
      radius="md"
      withBorder
      className={classes.card}
      role="button"
      tabIndex={0}
      aria-label={`Preview ${series.name}`}
      aria-haspopup="dialog"
      onClick={() => onClick(series)}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onClick(series);
        }
      }}
    >
      <CardSection>
        <Box className={classes.cardMedia}>
          {posterSrc && failedPoster !== posterSrc ? (
            <Image
              src={posterSrc}
              className={classes.cardImage}
              alt={series.name}
              fit="cover"
              loading="lazy"
              onError={() => setFailedPoster(posterSrc)}
            />
          ) : (
            <Box className={classes.placeholder} h="100%" display="flex">
              <Play size={36} aria-hidden="true" />
            </Box>
          )}
        </Box>
      </CardSection>

      <Stack gap={2} className={classes.cardInfo}>
        {compact ? (
          <Tooltip label={series.name} multiline maw={400} withArrow>
            {title}
          </Tooltip>
        ) : (
          title
        )}

        <Text size="xs" c="dimmed">
          Series
          {series.year ? (
            <>
              {' '}
              · <span>{series.year}</span>
            </>
          ) : null}
        </Text>
        {(compact || Number(series.rating) > 0) && (
          <Group gap={4} wrap="nowrap" c="dimmed">
            <Star size={12} aria-hidden="true" />
            <Text size="xs" c="dimmed">
              {formatRating(series.rating)}
            </Text>
          </Group>
        )}

        {!compact && series.genre && (
          <Text size="xs" c="dimmed" lineClamp={1}>
            {series.genre}
          </Text>
        )}
      </Stack>
    </Card>
  );
};

export default SeriesCard;
