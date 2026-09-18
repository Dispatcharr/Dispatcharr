import React from 'react';
import { Group, Pagination, Select, Text } from '@mantine/core';

const ListPagination = ({
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
  pageSizes = [10, 25, 50, 100],
}) => {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const first = total > 0 ? (page - 1) * pageSize + 1 : 0;
  const last = total > 0 ? Math.min(page * pageSize, total) : 0;

  return (
    <Group gap={5} justify="center" wrap="nowrap">
      <Text size="xs">Rows</Text>
      <Select
        aria-label="Rows"
        size="xs"
        value={String(pageSize)}
        onChange={(value) => onPageSizeChange(Number(value))}
        data={pageSizes.map((value) => ({
          value: String(value),
          label: String(value),
        }))}
        allowDeselect={false}
        w={70}
      />
      {total > 0 && (
        <Pagination
          value={page}
          onChange={onPageChange}
          total={pageCount}
          size="xs"
          withEdges
        />
      )}
      <Text size="xs" c="dimmed">
        {first}–{last} of {total}
      </Text>
    </Group>
  );
};

export default ListPagination;
