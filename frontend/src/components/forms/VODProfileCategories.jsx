import React, { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  ActionIcon,
  Anchor,
  Button,
  Checkbox,
  Flex,
  Group,
  Modal,
  Paper,
  ScrollArea,
  Select,
  Stack,
  Table,
  TableTbody,
  TableTd,
  TableTh,
  TableThead,
  TableTr,
  Tabs,
  TabsList,
  TabsPanel,
  TabsTab,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { Eye } from 'lucide-react';
import API from '../../api';
import ListPagination from '../ListPagination.jsx';
import CategoryStatusBadge from './CategoryStatusBadge.jsx';
import CategoryVisibilityFilter from './CategoryVisibilityFilter.jsx';
import M3UGroupContentPreview from './M3UGroupContentPreview.jsx';
import M3URulesModal from './M3URulesModal.jsx';
import VODMetadataCell from './VODMetadataCell.jsx';
import editorClasses from './AccountEditor.module.css';
import {
  DEFAULT_CATEGORY_VISIBILITY,
  matchesCategoryVisibility,
} from '../../utils/categoryVisibility.js';
import {
  categoryMetadata,
  VOD_METADATA_FIELDS,
  VOD_METADATA_LABELS,
} from '../../utils/vodSourceMetadata.js';
import { categoryRows, setCategoryChoices } from '../../utils/vodProfiles';

const SCOPES = [
  { value: 'movie', label: 'Movies' },
  { value: 'series', label: 'Series' },
];

function CategoryTable({
  scope,
  values,
  saved,
  options,
  errors,
  set,
  ruleStates,
  ruleCounts,
  onRulesChanged,
  onApplied,
  paginationContainer,
  paginationVisible,
}) {
  const [filter, setFilter] = useState('');
  const [account, setAccount] = useState(null);
  const [statusFilter, setStatusFilter] = useState(DEFAULT_CATEGORY_VISIBILITY);
  const [selected, setSelected] = useState(new Set());
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [rulesOpen, setRulesOpen] = useState(false);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkStatus, setBulkStatus] = useState('keep');
  const [previewCategory, setPreviewCategory] = useState(null);

  const accounts = useMemo(
    () =>
      Object.fromEntries(options.accounts.map((item) => [item.id, item.name])),
    [options.accounts]
  );
  const rows = useMemo(
    () => categoryRows(options.categories, values, scope, ruleStates),
    [options.categories, values, scope, ruleStates]
  );
  // Rules are saved right away, like M3U import rules, so they need a profile.
  const rulesApi = useMemo(
    () => (saved.id ? API.vodProfileRules(saved.id) : null),
    [saved.id]
  );
  const visible = rows
    .filter(
      (row) =>
        row.name.toLowerCase().includes(filter.toLowerCase()) &&
        (!account || String(row.account) === account) &&
        matchesCategoryVisibility(row, statusFilter)
    )
    .sort(
      (a, b) =>
        a.name.localeCompare(b.name) ||
        (accounts[a.account] || '').localeCompare(accounts[b.account] || '')
    );
  const pages = Math.max(1, Math.ceil(visible.length / pageSize));
  useEffect(() => {
    setPage((current) => Math.min(current, pages));
  }, [pages]);
  useEffect(() => setPage(1), [filter, account, statusFilter]);

  const ruleCount = ruleCounts?.[scope] || 0;
  const selectedVisible = visible.filter((row) => selected.has(row.id)).length;

  const choose = (targets, enabled) =>
    set('category_choices', setCategoryChoices(values, targets, enabled));
  const closeBulk = () => {
    setBulkOpen(false);
    setBulkStatus('keep');
  };
  const applyBulk = () => {
    if (bulkStatus !== 'keep')
      choose(
        rows.filter((row) => selected.has(row.id)),
        bulkStatus === 'enabled'
      );
    setSelected(new Set());
    closeBulk();
  };
  const toggleVisible = (checked) =>
    setSelected((current) => {
      const next = new Set(current);
      visible.forEach((row) =>
        checked ? next.add(row.id) : next.delete(row.id)
      );
      return next;
    });
  const toggleRow = (id, checked) =>
    setSelected((current) => {
      const next = new Set(current);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });

  const pagination = (
    <ListPagination
      page={page}
      pageSize={pageSize}
      total={visible.length}
      onPageChange={setPage}
      onPageSizeChange={(size) => {
        setPageSize(size);
        setPage(1);
      }}
    />
  );

  return (
    <Stack gap="xs" style={{ height: '100%', minHeight: 0 }}>
      <Flex gap="xs" align="center" wrap="wrap">
        <Tooltip
          label="Save the profile to add import rules."
          disabled={!!rulesApi}
        >
          <span style={{ display: 'inline-flex' }}>
            <Button
              variant={ruleCount ? 'light' : 'default'}
              size="xs"
              disabled={!rulesApi}
              onClick={() => setRulesOpen(true)}
            >
              Import rules{ruleCount ? ` (${ruleCount})` : ''}
            </Button>
          </span>
        </Tooltip>
        <Text size="xs" c="dimmed">
          Categories without a matching rule are disabled.
        </Text>
      </Flex>

      <Flex gap="sm" align="center" wrap="wrap">
        <TextInput
          placeholder="Filter categories..."
          value={filter}
          onChange={(event) => setFilter(event.currentTarget.value)}
          className={editorClasses.categorySearch}
          size="xs"
        />
        <CategoryVisibilityFilter
          value={statusFilter}
          onChange={setStatusFilter}
          categories={rows}
          statuses={['enabled', 'disabled']}
          filtered={!!account}
          onReset={() => setAccount(null)}
        >
          {options.accounts.length > 1 && (
            <Select
              size="xs"
              label="Account"
              placeholder="All accounts"
              clearable
              value={account}
              onChange={setAccount}
              comboboxProps={{ withinPortal: false }}
              data={options.accounts.map((item) => ({
                value: String(item.id),
                label: item.name,
              }))}
            />
          )}
        </CategoryVisibilityFilter>
        <Group gap="xs" ml="auto">
          {selected.size > 0 && (
            <Anchor
              component="button"
              type="button"
              size="xs"
              onClick={() => setSelected(new Set())}
            >
              Clear
            </Anchor>
          )}
          <Button
            variant="default"
            size="xs"
            disabled={!selected.size}
            onClick={() => setBulkOpen(true)}
          >
            Edit settings ({selected.size})
          </Button>
        </Group>
      </Flex>

      {errors.category_choices && (
        <Text size="sm" c="red">
          {errors.category_choices}
        </Text>
      )}

      <ScrollArea className={editorClasses.categoryTableFrame}>
        <Table
          striped
          stickyHeader
          miw={980}
          className={editorClasses.categoryTable}
        >
          <TableThead>
            <TableTr>
              <TableTh w={44}>
                <Checkbox
                  aria-label="Select visible categories"
                  checked={
                    visible.length > 0 && selectedVisible === visible.length
                  }
                  indeterminate={
                    selectedVisible > 0 && selectedVisible < visible.length
                  }
                  disabled={!visible.length}
                  onChange={(event) =>
                    toggleVisible(event.currentTarget.checked)
                  }
                />
              </TableTh>
              <TableTh>Category</TableTh>
              <TableTh w="14%">Account</TableTh>
              <TableTh w={100} ta="center">
                Status
              </TableTh>
              {VOD_METADATA_FIELDS.map((field) => (
                <TableTh
                  key={field}
                  w={field === 'video_features' ? '14%' : '10%'}
                >
                  {VOD_METADATA_LABELS[field]}
                </TableTh>
              ))}
              <TableTh w={76} ta="center">
                Actions
              </TableTh>
            </TableTr>
          </TableThead>
          <TableTbody>
            {!visible.length && (
              <TableTr>
                <TableTd colSpan={9} ta="center" py="xl">
                  <Text size="sm" c="dimmed">
                    {rows.length
                      ? 'No categories match the current filters.'
                      : 'No enabled provider categories yet.'}
                  </Text>
                  {rows.length > 0 && (
                    <Button
                      variant="subtle"
                      size="xs"
                      onClick={() => {
                        setFilter('');
                        setAccount(null);
                        setStatusFilter(DEFAULT_CATEGORY_VISIBILITY);
                      }}
                    >
                      Reset filters
                    </Button>
                  )}
                </TableTd>
              </TableTr>
            )}
            {visible
              .slice((page - 1) * pageSize, page * pageSize)
              .map((row) => (
                <TableTr
                  key={row.id}
                  bg={
                    selected.has(row.id)
                      ? 'var(--mantine-primary-color-light)'
                      : undefined
                  }
                >
                  <TableTd>
                    <Checkbox
                      aria-label={`Select ${row.name}`}
                      checked={selected.has(row.id)}
                      onChange={(event) =>
                        toggleRow(row.id, event.currentTarget.checked)
                      }
                    />
                  </TableTd>
                  <TableTd>
                    <Text size="sm" truncate>
                      {row.name}
                    </Text>
                  </TableTd>
                  <TableTd>
                    <Text size="sm" truncate>
                      {accounts[row.account] || `Account ${row.account}`}
                    </Text>
                  </TableTd>
                  <TableTd ta="center">
                    <CategoryStatusBadge
                      category={row}
                      onToggle={() => choose([row], !row.enabled)}
                    />
                  </TableTd>
                  {VOD_METADATA_FIELDS.map((field) => (
                    <TableTd key={field}>
                      <VODMetadataCell
                        values={categoryMetadata(row)}
                        field={field}
                      />
                    </TableTd>
                  ))}
                  <TableTd ta="center">
                    <Tooltip label="Preview category">
                      <ActionIcon
                        variant="subtle"
                        aria-label={`Preview ${row.name}`}
                        onClick={() => setPreviewCategory(row)}
                      >
                        <Eye size={16} />
                      </ActionIcon>
                    </Tooltip>
                  </TableTd>
                </TableTr>
              ))}
          </TableTbody>
        </Table>
      </ScrollArea>
      {paginationVisible &&
        (paginationContainer
          ? createPortal(pagination, paginationContainer)
          : pagination)}

      <M3UGroupContentPreview
        accountId={previewCategory?.account}
        scope={scope}
        group={
          previewCategory && {
            id: previewCategory.category,
            name: previewCategory.name,
          }
        }
        onClose={() => setPreviewCategory(null)}
      />
      {rulesApi && (
        <M3URulesModal
          opened={rulesOpen}
          onClose={() => setRulesOpen(false)}
          title={`${scope === 'series' ? 'Series' : 'Movie'} import rules`}
          accountId={`vod-profile-${saved.id}`}
          scope={scope}
          categoryCount={rows.length}
          rulesApi={rulesApi}
          metadataDefaults={false}
          ignoreResult={false}
          onApplied={onApplied}
          onRulesChanged={(rules) => onRulesChanged(scope, rules)}
        />
      )}
      <Modal
        stackId={`vod-profile-category-bulk-${scope}`}
        opened={bulkOpen}
        onClose={closeBulk}
        title={`Edit settings for ${selected.size} ${selected.size === 1 ? 'category' : 'categories'}`}
      >
        <Stack gap="sm">
          <Paper withBorder p="sm" role="group" aria-label="Category status">
            <Stack gap="xs">
              <Text fw={600}>General</Text>
              <Select
                label="Status"
                value={bulkStatus}
                allowDeselect={false}
                onChange={(value) => setBulkStatus(value || 'keep')}
                data={[
                  { value: 'keep', label: 'Keep unchanged' },
                  { value: 'enabled', label: 'Enabled' },
                  { value: 'disabled', label: 'Disabled' },
                ]}
              />
            </Stack>
          </Paper>
          <Group justify="flex-end" gap="xs">
            <Button variant="default" onClick={closeBulk}>
              Cancel
            </Button>
            <Button onClick={applyBulk}>Apply</Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}

export default function VODProfileCategories({
  active,
  paginationContainer,
  ...props
}) {
  const [scope, setScope] = useState('movie');
  return (
    <Tabs
      value={scope}
      onChange={setScope}
      keepMounted={false}
      style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
    >
      <TabsList mb="sm">
        {SCOPES.map((item) => (
          <TabsTab key={item.value} value={item.value}>
            VOD - {item.label}
          </TabsTab>
        ))}
      </TabsList>
      {SCOPES.map((item) => (
        <TabsPanel
          key={item.value}
          value={item.value}
          style={{ flex: 1, minHeight: 0 }}
        >
          <CategoryTable
            scope={item.value}
            paginationContainer={paginationContainer}
            paginationVisible={active && scope === item.value}
            {...props}
          />
        </TabsPanel>
      ))}
    </Tabs>
  );
}
