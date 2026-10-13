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
    // nowrap: default wrap drops the sort icon onto a second row when the
    // column is only a pixel or two too narrow, doubling the header height.
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
      // third click clears sort
    } else {
      newSorting[0] = { id: column, desc: false };
    }

    setSorting(newSorting);
    // Optional: tables that keep rows in state re-sort here. Tables that
    // derive rows from `sorting` omit the callback.
    if (onDataSort && newSorting.length > 0) {
      onDataSort(newSorting[0].id, newSorting[0].desc);
    }
  };
