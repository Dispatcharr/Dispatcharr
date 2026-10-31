import { createElement } from 'react';
import {
  Anchor,
  Button,
  Group,
  Paper,
  Stack,
  Text,
  ThemeIcon,
  Tooltip,
} from '@mantine/core';
import { Clapperboard, Film, Tv } from 'lucide-react';
import classes from './M3UAccountSummary.module.css';
import { getM3UStreamLabel } from '../../utils/forms/M3uSetupUtils.js';

const M3UCategorySummary = ({
  account,
  showCounts = true,
  onEdit,
  opening = false,
  editLabel = 'Edit selection',
  editDisabled = false,
  children,
}) => {
  const savedCounts = account.category_selection_counts;
  const live = account.channel_groups || [];
  const custom = account.custom_properties || {};
  const counts = [
    {
      label: getM3UStreamLabel(account.account_type),
      tab: 'live',
      icon: Tv,
      unit: 'streams',
      entries: custom.live_catalog_counts,
      ...(savedCounts?.live || {
        selected: live.filter((row) => row.enabled).length,
        total: live.length,
      }),
    },
    ...(account.account_type === 'XC' && account.enable_vod
      ? ['movie', 'series'].map((type) => ({
          label: type === 'movie' ? 'Movies' : 'Series',
          tab: `vod-${type}`,
          icon: type === 'movie' ? Film : Clapperboard,
          unit: type === 'movie' ? 'movies' : 'series',
          entries:
            custom.vod_catalog_counts?.[type === 'movie' ? 'movies' : 'series'],
          ...(savedCounts?.[type] || { selected: 0, total: 0 }),
        }))
      : []),
  ];

  return (
    <Paper
      component="section"
      aria-label="Category selection"
      withBorder
      radius="md"
      p="md"
      className={classes.card}
    >
      <Stack gap="md">
        {showCounts ? (
          <div className={classes.categoryGrid}>
            {counts.map(
              ({ label, tab, icon, selected, total, unit, entries }) => (
                <Paper
                  key={tab}
                  component="article"
                  aria-label={`${label} categories`}
                  withBorder
                  radius="md"
                  p="md"
                  className={`${classes.card} ${classes.categoryCard}`}
                >
                  <Group gap="sm" wrap="nowrap">
                    <ThemeIcon variant="light" size="lg" radius="md">
                      {createElement(icon, { size: 20, 'aria-hidden': true })}
                    </ThemeIcon>
                    <Text fw={600} className={classes.cardHeading}>
                      {label}
                    </Text>
                  </Group>
                  <Text size="sm" fw={500} className={classes.count}>
                    {selected} of {total} categories selected
                  </Text>
                  <Tooltip
                    label={
                      entries
                        ? 'Provider entries / imported entries from the last successful refresh'
                        : 'Entry counts are available after the first successful import'
                    }
                    multiline
                    w={280}
                  >
                    <div className={classes.catalogCounts}>
                      <Text size="xs" c="dimmed">
                        Provider / imported {unit}
                      </Text>
                      <Text size="sm" fw={500} className={classes.count}>
                        {entries
                          ? `${entries.provider_total} / ${entries.selected_total}`
                          : '— / —'}
                      </Text>
                    </div>
                  </Tooltip>
                </Paper>
              )
            )}
          </div>
        ) : (
          <Text fw={600}>Categories</Text>
        )}
        {showCounts && counts.length > 1 && (
          <Text size="sm" c="dimmed">
            Movies and series appear in the Library. Title cleanup and optional
            TMDB metadata can be set up in Settings at any time and apply to
            unprotected titles on the next refresh:{' '}
            <Anchor
              href="/settings#vod-metadata"
              target="_blank"
              rel="noopener noreferrer"
              inherit
            >
              Metadata
            </Anchor>
            {' · '}
            <Anchor
              href="/settings#vod-title-cleanup"
              target="_blank"
              rel="noopener noreferrer"
              inherit
            >
              Cleanup
            </Anchor>
          </Text>
        )}
        {onEdit && (
          <section
            aria-label="Category selection actions"
            className={classes.selectionActions}
          >
            <Button
              variant="filled"
              onClick={onEdit}
              loading={opening}
              disabled={editDisabled}
            >
              {editLabel}
            </Button>
          </section>
        )}
        {children}
      </Stack>
    </Paper>
  );
};

export default M3UCategorySummary;
