import React, { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Code,
  Group,
  Pagination,
  ScrollArea,
  SegmentedControl,
  Select,
  Stack,
  Table,
  TableTbody,
  TableTd,
  TableTh,
  TableThead,
  TableTr,
  Text,
  TextInput,
} from '@mantine/core';
import { Info, RefreshCw } from 'lucide-react';
import API from '../../api';
import VODSourcePreviewTable from '../VODSourcePreviewTable.jsx';

const M3UDeveloperCatalog = ({
  accountId,
  initialScope = 'live',
  lockedScope = false,
  initialCategory = '',
  nameTransform = null,
  summaryOnly = false,
}) => {
  const [scope, setScope] = useState(initialScope);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState(initialCategory);
  const [page, setPage] = useState(1);
  const [result, setResult] = useState({
    count: 0,
    categories: [],
    results: [],
  });
  const [loading, setLoading] = useState(false);

  const load = async () => {
    if (!accountId) return;
    setLoading(true);
    try {
      setResult(
        (await API.getM3UDeveloperCatalog(
          accountId,
          scope,
          search,
          page,
          category
        )) || {
          count: 0,
          categories: [],
          results: [],
        }
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const timer = setTimeout(load, 250);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId, scope, search, page, category]);

  useEffect(() => {
    setPage(1);
  }, [scope, search, category]);

  const totalPages = Math.max(1, Math.ceil((result.count || 0) / 100));

  return (
    <Stack pt="md">
      <Alert
        icon={<Info size={16} />}
        color={summaryOnly ? 'blue' : 'yellow'}
        variant="light"
      >
        {summaryOnly
          ? 'Read-only preview of the original names stored for this provider and category by the last completed import.'
          : 'This read-only catalog shows the original provider names and stored provider properties from the last import.'}
      </Alert>
      <Group justify="space-between" align="end">
        {!lockedScope && (
          <SegmentedControl
            value={scope}
            onChange={(value) => {
              setScope(value);
              setCategory('');
            }}
            data={[
              { value: 'live', label: 'Live' },
              { value: 'movie', label: 'Movies' },
              { value: 'series', label: 'Series' },
            ]}
          />
        )}
        <TextInput
          label={
            summaryOnly ? 'Search provider name' : 'Search provider name or ID'
          }
          placeholder="Provider name or ID"
          value={search}
          onChange={(event) => setSearch(event.currentTarget.value)}
          style={{ flex: 1 }}
        />
        {!initialCategory && (
          <Select
            label={scope === 'live' ? 'Group' : 'Category'}
            placeholder={scope === 'live' ? 'All groups' : 'All categories'}
            searchable
            clearable
            data={result.categories || []}
            value={category || null}
            onChange={(value) => setCategory(value || '')}
            miw={240}
          />
        )}
        <Button
          variant="default"
          leftSection={<RefreshCw size={15} />}
          loading={loading}
          onClick={load}
        >
          Refresh
        </Button>
      </Group>
      <Text size="sm" c="dimmed">
        {result.count || 0}{' '}
        {summaryOnly ? 'imported content entries' : 'parsed entries'}
      </Text>
      <ScrollArea h={lockedScope ? '62vh' : '55vh'}>
        {summaryOnly ? (
          <VODSourcePreviewTable
            rows={result.results || []}
            loading={loading}
            getRowKey={(row) => `${scope}:${row.id}`}
            getProviderTitle={(row) => row.name}
            emptyText="No imported content found."
          />
        ) : (
          <Table
            striped
            highlightOnHover
            withTableBorder
            stickyHeader
            miw={760}
          >
            <TableThead>
              <TableTr>
                <TableTh>Original provider name</TableTh>
                {nameTransform && <TableTh>Output name</TableTh>}
                <TableTh w="55%">Properties</TableTh>
              </TableTr>
            </TableThead>
            <TableTbody>
              {(result.results || []).map((row, index, rows) => (
                <React.Fragment key={`${scope}:${row.id}`}>
                  {(index === 0 || rows[index - 1]?.group !== row.group) && (
                    <TableTr
                      style={{
                        position: 'sticky',
                        top: 40,
                        zIndex: 2,
                        background: 'var(--mantine-color-dark-6)',
                      }}
                    >
                      <TableTh colSpan={nameTransform ? 3 : 2}>
                        {row.group || 'Uncategorized'}
                      </TableTh>
                    </TableTr>
                  )}
                  <TableTr>
                    <TableTd>
                      <Text fw={500}>{row.name || '—'}</Text>
                      <Text size="xs" c="dimmed">
                        Provider ID: {row.provider_id || '—'} · Internal ID:{' '}
                        {row.id}
                      </Text>
                      {row.url && (
                        <Code
                          fz="xs"
                          style={{
                            wordBreak: 'break-all',
                            whiteSpace: 'normal',
                          }}
                        >
                          {row.url}
                        </Code>
                      )}
                    </TableTd>
                    {nameTransform && (
                      <TableTd>{nameTransform(row.name || '', row)}</TableTd>
                    )}
                    <TableTd>
                      <Code block>
                        {JSON.stringify(row.properties || {}, null, 2)}
                      </Code>
                    </TableTd>
                  </TableTr>
                </React.Fragment>
              ))}
              {!loading && (result.results || []).length === 0 && (
                <TableTr>
                  <TableTd colSpan={nameTransform ? 3 : 2}>
                    <Text ta="center" c="dimmed" py="xl">
                      No parsed entries found.
                    </Text>
                  </TableTd>
                </TableTr>
              )}
            </TableTbody>
          </Table>
        )}
      </ScrollArea>
      {totalPages > 1 && (
        <Pagination value={page} onChange={setPage} total={totalPages} />
      )}
    </Stack>
  );
};

export default M3UDeveloperCatalog;
