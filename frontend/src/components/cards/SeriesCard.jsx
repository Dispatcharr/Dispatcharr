import {
  Box,
  Card,
  CardSection,
  Group,
  Image,
  Stack,
  Text,
} from '@mantine/core';
import { Play, Star } from 'lucide-react';
import React from 'react';
import classes from '../VODLayout.module.css';
import { vodLogoSrc } from '../../utils/cards/VODCardUtils.js';

const SeriesCard = ({ series, onClick }) => {
  const posterSrc = vodLogoSrc(series.logo);
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
          {posterSrc ? (
            <Image
              src={posterSrc}
              className={classes.cardImage}
              alt={series.name}
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
        <Text
          fw={600}
          size="sm"
          lineClamp={2}
          title={series.name}
          className={classes.cardTitle}
        >
          {series.name}
        </Text>

        <Text size="xs" c="dimmed">
          Series
          {series.year ? (
            <>
              {' '}
              · <span>{series.year}</span>
            </>
          ) : null}
        </Text>
        {Number(series.rating) > 0 && (
          <Group gap={4} wrap="nowrap" c="dimmed">
            <Star size={12} aria-hidden="true" />
            <Text size="xs" c="dimmed">
              {series.rating}
            </Text>
          </Group>
        )}

        {series.genre && (
          <Text size="xs" c="dimmed" lineClamp={1}>
            {series.genre}
          </Text>
        )}
      </Stack>
    </Card>
  );
};

export default SeriesCard;
