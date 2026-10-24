import {
  Box,
  Card,
  CardSection,
  Group,
  Image,
  Stack,
  Text,
} from '@mantine/core';
import { Clock, Play, Star } from 'lucide-react';
import React from 'react';
import classes from '../VODLayout.module.css';
import {
  formatDuration,
  getSeasonLabel,
  vodLogoSrc,
} from '../../utils/cards/VODCardUtils.js';

const VODCard = ({ vod, onClick }) => {
  const isEpisode = vod.type === 'episode';
  const posterSrc = vodLogoSrc(vod.logo);
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
        size="sm"
        lineClamp={2}
        title={vod.name}
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
          {posterSrc ? (
            <Image
              src={posterSrc}
              className={classes.cardImage}
              alt={vod.name}
              fit="cover"
              loading="lazy"
            />
          ) : (
            <Box className={classes.placeholder} h="100%" display="flex">
              <Play size={36} aria-hidden="true" />
            </Box>
          )}
        </Box>
      </CardSection>

      <Stack gap={2} className={classes.cardInfo}>
        {getDisplayTitle()}

        <Text size="xs" c="dimmed">
          {isEpisode ? 'Episode' : 'Movie'}
          {vod.year ? (
            <>
              {' '}
              · <span>{vod.year}</span>
            </>
          ) : null}
        </Text>

        {(durationSeconds > 0 || hasRating) && (
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
                  {vod.rating}
                </Text>
              </Group>
            )}
          </Group>
        )}

        {vod.genre && (
          <Text size="xs" c="dimmed" lineClamp={1}>
            {vod.genre}
          </Text>
        )}
      </Stack>
    </Card>
  );
};

export default VODCard;
