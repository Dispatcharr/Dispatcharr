import { Group, Pagination, Select, Text } from '@mantine/core';

const ListPagination = ({
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
  pageSizeOptions = [10, 25, 50, 100],
  itemLabel = 'Rows',
  disabled = false,
}) => (
  <Group gap="xs" justify="center" wrap="wrap">
    <Text size="xs">{itemLabel}</Text>
    <Select
      aria-label={`${itemLabel} per page`}
      size="xs"
      value={String(pageSize)}
      onChange={(value) => onPageSizeChange(Number(value))}
      data={pageSizeOptions.map((value) => ({
        value: String(value),
        label: String(value),
      }))}
      allowDeselect={false}
      disabled={disabled}
      w={70}
    />
    {total > 0 && (
      <Pagination
        value={page}
        onChange={onPageChange}
        total={Math.max(1, Math.ceil(total / pageSize))}
        size="xs"
        withEdges
        disabled={disabled}
        getControlProps={(control) => ({
          'aria-label': {
            first: 'First page',
            previous: 'Previous page',
            next: 'Next page',
            last: 'Last page',
          }[control],
        })}
      />
    )}
    <Text size="xs" c="dimmed">
      {total ? (page - 1) * pageSize + 1 : 0}–{Math.min(page * pageSize, total)}{' '}
      of {total}
    </Text>
  </Group>
);

export default ListPagination;
