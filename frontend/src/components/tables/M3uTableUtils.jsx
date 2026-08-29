import React from 'react';
import { Center, Group, Text } from '@mantine/core';
import {
  ArrowDownWideNarrow,
  ArrowUpDown,
  ArrowUpNarrowWide,
} from 'lucide-react';

export const makeHeaderCellRenderer = (sorting, onSortingChange) => (header) => {
  let sortingIcon = ArrowUpDown;
  if (sorting[0]?.id === header.id) {
    sortingIcon =
      sorting[0].desc === false ? ArrowUpNarrowWide : ArrowDownWideNarrow;
  }

  return (
    // nowrap keeps the sort control on the header's line: with the default
    // wrap, a column only a pixel or two too narrow drops the icon onto a
    // second row and doubles the header height.
    <Group gap="xs" wrap="nowrap">
      <Text size="sm" name={header.id}>
        {header.column.columnDef.header}
      </Text>
      {header.column.columnDef.sortable && (
        <Center>
          {React.createElement(sortingIcon, {
            onClick: () => onSortingChange(header.id),
            size: 14,
          })}
        </Center>
      )}
    </Group>
  );
};

export const makeSortingChangeHandler =
  (sorting, setSorting, onDataSort) => (column) => {
    const sortField = sorting[0]?.id;
    const sortDirection = sorting[0]?.desc;

    const newSorting = [];
    if (sortField === column) {
      if (sortDirection === false) {
        newSorting[0] = { id: column, desc: true };
      }
      // third click → clear (empty array)
    } else {
      newSorting[0] = { id: column, desc: false };
    }

    setSorting(newSorting);
    // Optional: tables that keep their rows in state re-sort them here. Tables
    // that derive their rows from `sorting` don't pass a callback.
    if (onDataSort && newSorting.length > 0) {
      onDataSort(newSorting[0].id, newSorting[0].desc);
    }
  };

