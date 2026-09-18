import React from 'react';
import {
  ActionIcon,
  Table,
  TableTbody,
  TableTd,
  TableTh,
  TableThead,
  TableTr,
  Text,
  Tooltip,
} from '@mantine/core';
import { Eye } from 'lucide-react';

const VODSourcePreviewTable = ({
  rows = [],
  loading = false,
  getRowKey = (row) => row.id,
  getProviderTitle = (row) => row.provider_title || row.name || '',
  getCanonicalTitle = null,
  getProviderName = null,
  getCategoryName = null,
  onOpenDetails = null,
  emptyText = 'No imported content found.',
  minWidth = 420,
}) => {
  const showOrigin =
    typeof getProviderName === 'function' ||
    typeof getCategoryName === 'function';
  const showDetails = typeof onOpenDetails === 'function';
  const columnCount = 1 + Number(showOrigin) + Number(showDetails);

  return (
    <Table striped highlightOnHover withTableBorder stickyHeader miw={minWidth}>
      <TableThead>
        <TableTr>
          <TableTh>Provider title</TableTh>
          {showOrigin && <TableTh>Provider / category</TableTh>}
          {showDetails && <TableTh w={70}>Details</TableTh>}
        </TableTr>
      </TableThead>
      <TableTbody>
        {rows.map((row) => (
          <TableTr key={getRowKey(row)}>
            <TableTd>
              <Text size="sm">{getProviderTitle(row) || '—'}</Text>
              {typeof getCanonicalTitle === 'function' && (
                <Text size="xs" c="dimmed">
                  {getCanonicalTitle(row) || '—'}
                </Text>
              )}
            </TableTd>
            {showOrigin && (
              <TableTd>
                <Text size="sm">{getProviderName?.(row) || '—'}</Text>
                <Text size="xs" c="dimmed">
                  {getCategoryName?.(row) || 'Uncategorized'}
                </Text>
              </TableTd>
            )}
            {showDetails && (
              <TableTd>
                <Tooltip label="Open VOD details">
                  <ActionIcon
                    variant="subtle"
                    aria-label={`Open details for ${getProviderTitle(row) || 'VOD source'}`}
                    onClick={() => onOpenDetails(row)}
                  >
                    <Eye size={16} />
                  </ActionIcon>
                </Tooltip>
              </TableTd>
            )}
          </TableTr>
        ))}
        {!loading && rows.length === 0 && (
          <TableTr>
            <TableTd colSpan={columnCount}>
              <Text ta="center" c="dimmed" py="lg">
                {emptyText}
              </Text>
            </TableTd>
          </TableTr>
        )}
      </TableTbody>
    </Table>
  );
};

export default VODSourcePreviewTable;
