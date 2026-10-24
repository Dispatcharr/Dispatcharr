import {
  ActionIcon,
  Button,
  Checkbox,
  Indicator,
  Popover,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import { Filter } from 'lucide-react';

import {
  DEFAULT_CATEGORY_VISIBILITY,
  matchesCategoryVisibility,
} from '../../utils/categoryVisibility.js';

export default function CategoryVisibilityFilter({
  value,
  onChange,
  categories,
}) {
  const hiddenCount = categories.filter(
    (row) => !matchesCategoryVisibility(row, value)
  ).length;
  const active = !value.enabled || !value.disabled || hiddenCount > 0;
  return (
    <Popover position="bottom-end" withArrow trapFocus returnFocus>
      <Indicator
        inline
        color="red"
        size={10}
        offset={1}
        withBorder
        disabled={!active}
        zIndex={1}
      >
        <Popover.Target>
          <Tooltip
            label={
              hiddenCount
                ? `${hiddenCount} ${hiddenCount === 1 ? 'category' : 'categories'} filtered`
                : active
                  ? 'Category filter active'
                  : 'Filter categories'
            }
          >
            <ActionIcon
              size="input-xs"
              variant={active ? 'light' : 'default'}
              color={hiddenCount ? 'orange' : undefined}
              aria-label="Filter category status"
              aria-description={
                active ? 'Category status filter active' : undefined
              }
              data-filter-active={active || undefined}
              data-hidden-count={hiddenCount || undefined}
            >
              <Filter size={16} aria-hidden="true" />
            </ActionIcon>
          </Tooltip>
        </Popover.Target>
      </Indicator>
      <Popover.Dropdown data-mantine-stop-propagation="true">
        <Stack gap="xs">
          <Text size="sm" fw={600}>
            Show categories
          </Text>
          {hiddenCount > 0 && (
            <Text size="xs" c="dimmed">
              {hiddenCount} {hiddenCount === 1 ? 'category' : 'categories'}{' '}
              filtered
            </Text>
          )}
          {['enabled', 'disabled', 'ignored'].map((status) => (
            <Checkbox
              key={status}
              data-mantine-stop-propagation="true"
              label={status[0].toUpperCase() + status.slice(1)}
              checked={value[status]}
              onChange={(event) =>
                onChange({ ...value, [status]: event.currentTarget.checked })
              }
            />
          ))}
          <Button
            size="compact-xs"
            variant="subtle"
            data-mantine-stop-propagation="true"
            onClick={() => onChange(DEFAULT_CATEGORY_VISIBILITY)}
          >
            Reset filters
          </Button>
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
}
