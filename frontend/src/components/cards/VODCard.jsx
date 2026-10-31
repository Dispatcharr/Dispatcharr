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
import { Clock, Play, Star } from 'lucide-react';
import React, { useState } from 'react';
import classes from '../VODLayout.module.css';
import {
  formatDuration,
  formatRating,
  getSeasonLabel,
  vodLogoSrc,
} from '../../utils/cards/VODCardUtils.js';

const VODCard = ({ vod, onClick, compact = false }) => {
  const isEpisode = vod.type === 'episode';
  const posterSrc = vodLogoSrc(vod.logo);
  const [failedPoster, setFailedPoster] = useState(null);
  const durationSeconds = vod.duration_secs ?? vod.duration;
  const hasRating = Number(vod.rating) > 0;

  const getDisplayTitle = () => {
    if (isEpisode && vod.series) {
      return (
        <Stack gap={4}>
          <Text size="sm" c="dimmed" lineClamp={1} title={vod.series.name}>
            {vod.series.name}
          </Text>
          <Text
            fw={600}
            size="sm"
            lineClamp={2}
            title={`${getSeasonLabel(vod)} - ${vod.name}`}
            className={classes.cardTitle}
          >
            {getSeasonLabel(vod)} - {vod.name}
          </Text>
        </Stack>
      );
    }
    return (
      <Text
        fw={600}
        size={compact ? 13 : 'sm'}
        lh={compact ? 1.4 : undefined}
        lineClamp={compact ? 1 : 2}
        title={compact ? undefined : vod.name}
        className={classes.cardTitle}
      >
        {vod.name}
      </Text>
    );
  };

  const handleCardClick = () => {
    onClick(vod);
  };

  return (
    <Card
      padding={0}
      radius="md"
      withBorder
      className={classes.card}
      role="button"
      tabIndex={0}
      aria-label={`Preview ${vod.name}`}
      aria-haspopup="dialog"
      onClick={handleCardClick}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          handleCardClick();
        }
      }}
    >
      <CardSection>
        <Box className={classes.cardMedia}>
          {posterSrc && failedPoster !== posterSrc ? (
            <Image
              src={posterSrc}
              className={classes.cardImage}
              alt={vod.name}
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
          <Tooltip label={vod.name} multiline maw={400} withArrow>
            {getDisplayTitle()}
          </Tooltip>
        ) : (
          getDisplayTitle()
        )}

        <Text size="xs" c="dimmed">
          {isEpisode ? 'Episode' : 'Movie'}
          {vod.year ? (
            <>
              {' '}
              · <span>{vod.year}</span>
            </>
          ) : null}
        </Text>

        {compact ? (
          <Group gap={4} wrap="nowrap" c="dimmed" mih={18}>
            <Star size={12} aria-hidden="true" />
            <Text size="xs" c="dimmed">
              {formatRating(vod.rating)}
            </Text>
          </Group>
        ) : (
          (durationSeconds > 0 || hasRating) && (
            <Group gap="sm">
              {durationSeconds > 0 && (
                <Group gap={4} wrap="nowrap" c="dimmed">
                  <Clock size={12} aria-hidden="true" />
                  <Text size="xs" c="dimmed">
                    {formatDuration(durationSeconds)}
                  </Text>
                </Group>
              )}

              {hasRating && (
                <Group gap={4} wrap="nowrap" c="dimmed">
                  <Star size={12} aria-hidden="true" />
                  <Text size="xs" c="dimmed">
                    {formatRating(vod.rating)}
                  </Text>
                </Group>
              )}
            </Group>
          )
        )}

        {!compact && vod.genre && (
          <Text size="xs" c="dimmed" lineClamp={1}>
            {vod.genre}
          </Text>
        )}
      </Stack>
    </Card>
  );
};

export default VODCard;
