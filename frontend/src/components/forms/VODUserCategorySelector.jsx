import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Button,
  Checkbox,
  Group,
  Modal,
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
import { flattenVODCategoryRelations } from './VODUserCategorySelector.utils.js';

const PAGE_SIZE = 50;

const metadataValue = (metadata, field) => {
  const value = metadata?.[field];
  if (Array.isArray(value)) return value.length ? value.join(', ') : '—';
  return value || '—';
};

const VODUserCategorySelector = ({
  opened,
  onClose,
  categories,
  selectedIds,
  onChange,
}) => {
  const rows = useMemo(
    () => flattenVODCategoryRelations(categories),
    [categories]
  );
  const [allowedIds, setAllowedIds] = useState(new Set());
  const [selectedRows, setSelectedRows] = useState(new Set());
  const [search, setSearch] = useState('');
  const [account, setAccount] = useState('');
  const [type, setType] = useState('all');
  const [status, setStatus] = useState('all');
  const [page, setPage] = useState(1);
  const initializedForOpen = useRef(false);

  useEffect(() => {
    if (!opened) {
      initializedForOpen.current = false;
      return;
    }
    if (initializedForOpen.current || rows.length === 0) return;
    const explicit = new Set((selectedIds || []).map(String));
    const availableExplicit = new Set(
      rows.filter((row) => explicit.has(row.id)).map((row) => row.id)
    );
    setAllowedIds(
      availableExplicit.size
        ? availableExplicit
        : new Set(rows.map((row) => row.id))
    );
    setSelectedRows(new Set());
    setSearch('');
    setAccount('');
    setType('all');
    setStatus('all');
    setPage(1);
    initializedForOpen.current = true;
    // Changes from profile polling must not overwrite an open editor.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, rows]);

  const accountOptions = useMemo(
    () =>
      [...new Map(rows.map((row) => [row.accountId, row.accountName]))]
        .map(([value, label]) => ({ value, label }))
        .sort((left, right) => left.label.localeCompare(right.label)),
    [rows]
  );

  const filteredRows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return rows.filter((row) => {
      const allowed = allowedIds.has(row.id);
      return (
        (!needle ||
          `${row.accountName} ${row.categoryName}`
            .toLowerCase()
            .includes(needle)) &&
        (!account || row.accountId === account) &&
        (type === 'all' || row.categoryType === type) &&
        (status === 'all' || (status === 'allowed' ? allowed : !allowed))
      );
    });
  }, [account, allowedIds, rows, search, status, type]);

  useEffect(() => {
    setPage(1);
    setSelectedRows(new Set());
  }, [account, search, status, type]);

  const pageCount = Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE));

  useEffect(() => {
    setPage((current) => Math.min(current, pageCount));
  }, [pageCount]);

  const pageRows = filteredRows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const allFilteredSelected =
    filteredRows.length > 0 &&
    filteredRows.every((row) => selectedRows.has(row.id));

  const toggleAllFiltered = (checked) => {
    setSelectedRows((current) => {
      const next = new Set(current);
      filteredRows.forEach((row) =>
        checked ? next.add(row.id) : next.delete(row.id)
      );
      return next;
    });
  };

  const setSelectedAllowed = (allowed) => {
    setAllowedIds((current) => {
      const next = new Set(current);
      selectedRows.forEach((id) => (allowed ? next.add(id) : next.delete(id)));
      return next;
    });
    setSelectedRows(new Set());
  };

  const apply = () => {
    // Persist the exact visible choice.  An empty rule list is retained only
    // as a backwards-compatible meaning for profiles that have never saved a
    // category allowlist; collapsing an explicit "all" choice back to [] made
    // freshly added categories appear to disappear after reopening.
    onChange([...allowedIds]);
    onClose();
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title="VOD category access"
      size="95vw"
      styles={{
        content: { height: '96vh', overflowX: 'hidden' },
        body: { height: 'calc(96vh - 60px)', overflowX: 'hidden' },
      }}
      scrollAreaComponent={Modal.NativeScrollArea}
      lockScroll={false}
      yOffset="2vh"
    >
      <Stack h="100%" gap="sm">
        <Alert color="blue" variant="light">
          Profiles without a saved category selection initially include every
          enabled source category. Applying this dialog stores the exact
          selection shown here. Search and filters also define the scope of
          “select all”.
        </Alert>

        <Group align="flex-end" wrap="wrap">
          <TextInput
            label="Search"
            placeholder="M3U account or category"
            value={search}
            onChange={(event) => setSearch(event.currentTarget.value)}
            style={{ flex: 1, minWidth: 240 }}
          />
          <Select
            label="M3U account"
            placeholder="All accounts"
            clearable
            searchable
            data={accountOptions}
            value={account || null}
            onChange={(value) => setAccount(value || '')}
            miw={220}
          />
          <SegmentedControl
            value={type}
            onChange={setType}
            data={[
              { value: 'all', label: 'Movies & series' },
              { value: 'movie', label: 'Movies' },
              { value: 'series', label: 'Series' },
            ]}
          />
          <SegmentedControl
            value={status}
            onChange={setStatus}
            data={[
              { value: 'all', label: 'All' },
              { value: 'allowed', label: 'Allowed' },
              { value: 'blocked', label: 'Blocked' },
            ]}
          />
        </Group>

        <Group justify="space-between" wrap="wrap">
          <Text size="sm" c="dimmed">
            {allowedIds.size} of {rows.length} categories allowed ·{' '}
            {filteredRows.length} matching current filters
          </Text>
          <Group gap="xs">
            <Button
              variant="default"
              size="xs"
              onClick={() => setAllowedIds(new Set(rows.map((row) => row.id)))}
            >
              Use all enabled
            </Button>
            <Button
              size="xs"
              color="green"
              disabled={!selectedRows.size}
              onClick={() => setSelectedAllowed(true)}
            >
              Allow selected ({selectedRows.size})
            </Button>
            <Button
              size="xs"
              color="red"
              variant="light"
              disabled={!selectedRows.size}
              onClick={() => setSelectedAllowed(false)}
            >
              Block selected ({selectedRows.size})
            </Button>
          </Group>
        </Group>

        <ScrollArea style={{ flex: 1 }} type="auto">
          <Table striped highlightOnHover withTableBorder stickyHeader>
            <TableThead>
              <TableTr>
                <TableTh w={44}>
                  <Checkbox
                    aria-label="Select all filtered categories"
                    checked={allFilteredSelected}
                    onChange={(event) =>
                      toggleAllFiltered(event.currentTarget.checked)
                    }
                  />
                </TableTh>
                <TableTh w={100}>Allowed</TableTh>
                <TableTh>M3U account</TableTh>
                <TableTh>Category</TableTh>
                <TableTh w={100}>Type</TableTh>
                <TableTh w={150}>DUB</TableTh>
                <TableTh w={150}>SUB</TableTh>
                <TableTh w={120}>Resolution</TableTh>
              </TableTr>
            </TableThead>
            <TableTbody>
              {pageRows.map((row) => (
                <TableTr key={row.id}>
                  <TableTd>
                    <Checkbox
                      aria-label={`Select ${row.accountName} ${row.categoryName}`}
                      checked={selectedRows.has(row.id)}
                      onChange={(event) => {
                        const checked = event.currentTarget.checked;
                        setSelectedRows((current) => {
                          const next = new Set(current);
                          checked ? next.add(row.id) : next.delete(row.id);
                          return next;
                        });
                      }}
                    />
                  </TableTd>
                  <TableTd>
                    <Button
                      size="compact-xs"
                      color={allowedIds.has(row.id) ? 'green' : 'gray'}
                      variant={allowedIds.has(row.id) ? 'filled' : 'light'}
                      aria-pressed={allowedIds.has(row.id)}
                      onClick={() => {
                        setAllowedIds((current) => {
                          const next = new Set(current);
                          next.has(row.id)
                            ? next.delete(row.id)
                            : next.add(row.id);
                          return next;
                        });
                      }}
                    >
                      {allowedIds.has(row.id) ? 'Allowed' : 'Blocked'}
                    </Button>
                  </TableTd>
                  <TableTd>{row.accountName}</TableTd>
                  <TableTd>{row.categoryName}</TableTd>
                  <TableTd>
                    {row.categoryType === 'movie' ? 'Movie' : 'Series'}
                  </TableTd>
                  <TableTd>
                    {metadataValue(row.metadata, 'audio_languages')}
                  </TableTd>
                  <TableTd>
                    {metadataValue(row.metadata, 'subtitle_languages')}
                  </TableTd>
                  <TableTd>{metadataValue(row.metadata, 'resolution')}</TableTd>
                </TableTr>
              ))}
            </TableTbody>
          </Table>
        </ScrollArea>

        <Group justify="space-between">
          <Pagination value={page} onChange={setPage} total={pageCount} />
          <Group>
            <Button variant="default" onClick={onClose}>
              Cancel
            </Button>
            <Button
              disabled={rows.length > 0 && !allowedIds.size}
              onClick={apply}
            >
              Apply category access
            </Button>
          </Group>
        </Group>
      </Stack>
    </Modal>
  );
};

export default VODUserCategorySelector;
