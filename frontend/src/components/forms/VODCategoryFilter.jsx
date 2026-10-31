import React, { memo, useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  TextInput,
  Button,
  Flex,
  Group,
  Modal,
  Paper,
  Stack,
  ActionIcon,
  Anchor,
  Tooltip,
  ScrollArea,
  Table,
  TableThead,
  TableTbody,
  TableTr,
  TableTh,
  TableTd,
  Text,
  Checkbox,
  Select,
} from '@mantine/core';
import { Eye, Settings as Cog } from 'lucide-react';
import useVODStore from '../../store/useVODStore';
import ListPagination from '../ListPagination.jsx';
import M3UGroupContentPreview from './M3UGroupContentPreview.jsx';
import editorClasses from './AccountEditor.module.css';
import MEDIA_LANGUAGE_OPTIONS from '../../../../apps/vod/media_languages.json';
import VODCategoryMetadataEditor from './VODCategoryMetadataEditor.jsx';
import VODMetadataCell from './VODMetadataCell.jsx';
import CategoryVisibilityFilter from './CategoryVisibilityFilter.jsx';
import CategoryStatusBadge from './CategoryStatusBadge.jsx';
import CategoryCleanupFields from '../CategoryCleanupFields.jsx';
import StackedModal from '../StackedModal.jsx';
import ConfirmationDialog from '../ConfirmationDialog.jsx';
import {
  DEFAULT_CATEGORY_VISIBILITY,
  matchesCategoryVisibility,
  categoryStatusPatch,
} from '../../utils/categoryVisibility.js';
import {
  categoryMetadata,
  categoryMetadataPatch,
  metadataSummary,
  VOD_RESOLUTIONS,
  VOD_METADATA_FIELDS,
  VOD_METADATA_LABELS,
} from '../../utils/vodSourceMetadata.js';

const EMPTY_BULK_SETTINGS = Object.freeze({ enabled: 'keep' });

const parseCustomProperties = (raw) => {
  if (!raw) return {};
  try {
    return typeof raw === 'string' ? JSON.parse(raw) : { ...raw };
  } catch {
    return {};
  }
};

const CategoryCard = memo(function CategoryCard({
  category,
  onConfigure,
  onPreview,
  selected,
  onSelect,
  onToggleEnabled,
  previewAvailable,
  previewUnavailableHint,
}) {
  const summary = metadataSummary(categoryMetadata(category));
  const cleanupConfigured =
    !!category.custom_properties?.title_cleanup?.pattern;
  return (
    <TableTr
      data-selected={selected || undefined}
      bg={selected ? 'var(--mantine-primary-color-light)' : undefined}
    >
      <TableTd>
        <Checkbox
          aria-label={`Select ${category.name}`}
          checked={selected}
          onChange={(event) =>
            onSelect(category.id, event.currentTarget.checked)
          }
        />
      </TableTd>
      <TableTd>
        <Text size="sm" truncate>
          {category.name}
        </Text>
      </TableTd>
      <TableTd ta="center">
        <CategoryStatusBadge
          category={category}
          onToggle={() => onToggleEnabled(category.id)}
        />
      </TableTd>
      {VOD_METADATA_FIELDS.map((field) => {
        return (
          <TableTd key={field}>
            <VODMetadataCell
              values={categoryMetadata(category)}
              field={field}
            />
          </TableTd>
        );
      })}
      <TableTd>
        <Flex gap={4} align="center" justify="center">
          <Tooltip
            label={
              category.enabled
                ? summary || 'Configure category defaults'
                : 'Enable this category before editing defaults'
            }
          >
            <ActionIcon
              aria-label={`Edit defaults for ${category.name}`}
              variant={summary || cleanupConfigured ? 'light' : 'subtle'}
              color={summary || cleanupConfigured ? 'blue' : undefined}
              disabled={!category.enabled}
              onClick={() => category.enabled && onConfigure(category)}
            >
              <Cog size={16} />
            </ActionIcon>
          </Tooltip>
          <Tooltip
            label={
              previewAvailable ? 'Preview category' : previewUnavailableHint
            }
            multiline
            maw={300}
            withArrow
            events={{ hover: true, focus: true, touch: true }}
          >
            <span
              style={{ display: 'inline-flex' }}
              tabIndex={previewAvailable ? undefined : 0}
              aria-label={previewAvailable ? undefined : previewUnavailableHint}
            >
              <ActionIcon
                variant="subtle"
                aria-label="Preview category"
                onClick={() => onPreview(category)}
                disabled={!previewAvailable}
              >
                <Eye size={16} />
              </ActionIcon>
            </span>
          </Tooltip>
        </Flex>
      </TableTd>
    </TableTr>
  );
});

const VODCategoryFilter = ({
  ruleCount = 0,
  playlist = null,
  categoryStates,
  setCategoryStates,
  type,
  onOpenRules,
  onOverlayChange,
  paginationContainer = null,
  paginationVisible = true,
  previewAvailableIds,
  previewUnavailableHint,
}) => {
  const categories = useVODStore((s) => s.categories);
  const [filter, setFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState(DEFAULT_CATEGORY_VISIBILITY);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [previewCategory, setPreviewCategory] = useState(null);
  const [selectedCategoryIds, setSelectedCategoryIds] = useState(new Set());
  const [bulkEditorOpen, setBulkEditorOpen] = useState(false);
  const [bulkSettings, setBulkSettings] = useState(EMPTY_BULK_SETTINGS);
  const [configuringCategoryId, setConfiguringCategoryId] = useState(null);
  const [cleanupDraft, setCleanupDraft] = useState({});
  const [cleanupValid, setCleanupValid] = useState(true);
  const [metadataDirty, setMetadataDirty] = useState(false);
  const [discardConfig, setDiscardConfig] = useState(false);
  const configuringCategory = categoryStates.find(
    (category) => category.id === configuringCategoryId
  );
  useEffect(() => {
    const ids = new Set(categoryStates.map((category) => category.id));
    setSelectedCategoryIds((current) => {
      const next = new Set([...current].filter((id) => ids.has(id)));
      return next.size === current.size ? current : next;
    });
  }, [categoryStates]);
  useEffect(() => {
    onOverlayChange?.(
      bulkEditorOpen || !!previewCategory || !!configuringCategory
    );
    return () => onOverlayChange?.(false);
  }, [bulkEditorOpen, previewCategory, configuringCategory, onOverlayChange]);
  const initializedScope = useRef(null);
  useEffect(() => {
    setPage(1);
  }, [filter, statusFilter, type]);
  useEffect(() => {
    setSelectedCategoryIds(new Set());
    setBulkEditorOpen(false);
    setConfiguringCategoryId(null);
  }, [playlist.id, type]);

  useEffect(() => {
    if (Object.keys(categories).length === 0) {
      return;
    }

    const key = `${playlist.id}:${type}`;
    const sameScope = initializedScope.current === key;
    initializedScope.current = key;
    setCategoryStates((previous) =>
      Object.values(categories)
        .filter(
          (cat) =>
            cat.m3u_accounts.find((acc) => acc.m3u_account == playlist.id) &&
            cat.category_type == type
        )
        .map((cat) => {
          const existing = sameScope
            ? previous.find((row) => row.id === cat.id)
            : null;
          if (existing) return { ...cat, ...existing, name: cat.name };
          const match = cat.m3u_accounts.find(
            (acc) => acc.m3u_account == playlist.id
          );
          if (!match) return null;
          const custom_properties = parseCustomProperties(
            match.custom_properties
          );
          return {
            ...cat,
            enabled: match.enabled || false,
            original_enabled: match.enabled,
            ignored: !!match.ignored,
            original_ignored: !!match.ignored,
            custom_properties,
            original_custom_properties: { ...custom_properties },
          };
        })
        .filter(Boolean)
    );
  }, [categories, playlist.id, setCategoryStates, type]);

  const toggleEnabled = useCallback(
    (id) => {
      setCategoryStates((current) =>
        current.map((category) =>
          category.id === id && !category.ignored
            ? { ...category, enabled: !category.enabled }
            : category
        )
      );
    },
    [setCategoryStates]
  );

  const openConfigure = useCallback((category) => {
    if (category.enabled) {
      setCleanupDraft(category.custom_properties?.title_cleanup || {});
      setCleanupValid(true);
      setMetadataDirty(false);
      setConfiguringCategoryId(category.id);
    }
  }, []);
  const closeConfigure = () => {
    const cleanupDirty =
      JSON.stringify(cleanupDraft) !==
      JSON.stringify(
        configuringCategory?.custom_properties?.title_cleanup || {}
      );
    if (metadataDirty || cleanupDirty) setDiscardConfig(true);
    else setConfiguringCategoryId(null);
  };
  const applyMetadata = (draft) => {
    const patch = categoryMetadataPatch(draft);
    setCategoryStates((current) =>
      current.map((category) =>
        category.id === configuringCategoryId
          ? {
              ...category,
              custom_properties: {
                ...category.custom_properties,
                ...patch,
                ...(JSON.stringify(cleanupDraft) !==
                JSON.stringify(category.custom_properties?.title_cleanup || {})
                  ? { title_cleanup: cleanupDraft }
                  : {}),
              },
            }
          : category
      )
    );
    setConfiguringCategoryId(null);
  };

  const isVisible = useCallback(
    (category) => {
      const matchesText = category.name
        .toLowerCase()
        .includes(filter.toLowerCase());
      const matchesStatus = matchesCategoryVisibility(category, statusFilter);
      return matchesText && matchesStatus;
    },
    [filter, statusFilter]
  );

  const toggleSelectedCategory = useCallback((id, checked) => {
    setSelectedCategoryIds((current) => {
      const next = new Set(current);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);
  const closeBulkEditor = () => {
    setBulkEditorOpen(false);
    setBulkSettings(EMPTY_BULK_SETTINGS);
  };
  const applyBulkSettings = (patch) => {
    setCategoryStates((current) =>
      current.map((category) => {
        if (!selectedCategoryIds.has(category.id)) return category;
        const next = {
          ...category,
          custom_properties: { ...category.custom_properties },
        };
        if (bulkSettings.enabled !== 'keep')
          Object.assign(next, categoryStatusPatch(bulkSettings.enabled));
        if (next.enabled) Object.assign(next.custom_properties, patch);
        return next;
      })
    );
    closeBulkEditor();
  };

  const visibleCategories = categoryStates
    .filter((category) => isVisible(category))
    .sort((a, b) => a.name.localeCompare(b.name));
  useEffect(() => {
    setPage((current) =>
      Math.min(
        current,
        Math.max(1, Math.ceil(visibleCategories.length / pageSize))
      )
    );
  }, [visibleCategories.length, pageSize]);
  const selectedVisibleCount = visibleCategories.filter((category) =>
    selectedCategoryIds.has(category.id)
  ).length;
  const toggleVisibleSelection = (checked) => {
    setSelectedCategoryIds((current) => {
      const next = new Set(current);
      visibleCategories.forEach((category) =>
        checked ? next.add(category.id) : next.delete(category.id)
      );
      return next;
    });
  };

  const pagination = (
    <ListPagination
      page={page}
      pageSize={pageSize}
      total={visibleCategories.length}
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
        <Button
          variant={ruleCount ? 'light' : 'default'}
          size="xs"
          onClick={onOpenRules}
        >
          Import rules{ruleCount ? ` (${ruleCount})` : ''}
        </Button>
        <Text size="xs" c="dimmed">
          New unmatched categories are imported disabled.
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
          categories={categoryStates}
        />
        <Group gap="xs" ml="auto">
          {selectedCategoryIds.size > 0 && (
            <Anchor
              component="button"
              type="button"
              size="xs"
              onClick={() => setSelectedCategoryIds(new Set())}
            >
              Clear
            </Anchor>
          )}
          <Button
            variant="default"
            size="xs"
            disabled={!selectedCategoryIds.size}
            onClick={() => {
              setBulkSettings(EMPTY_BULK_SETTINGS);
              setBulkEditorOpen(true);
            }}
          >
            Edit settings ({selectedCategoryIds.size})
          </Button>
        </Group>
      </Flex>

      <ScrollArea className={editorClasses.categoryTableFrame}>
        <Table
          striped
          stickyHeader
          miw={900}
          className={editorClasses.categoryTable}
        >
          <TableThead>
            <TableTr>
              <TableTh w={44}>
                <Checkbox
                  aria-label="Select visible categories"
                  checked={
                    visibleCategories.length > 0 &&
                    selectedVisibleCount === visibleCategories.length
                  }
                  indeterminate={
                    selectedVisibleCount > 0 &&
                    selectedVisibleCount < visibleCategories.length
                  }
                  disabled={!visibleCategories.length}
                  onChange={(event) =>
                    toggleVisibleSelection(event.currentTarget.checked)
                  }
                />
              </TableTh>
              <TableTh>Category</TableTh>
              <TableTh w={100} ta="center">
                Status
              </TableTh>
              {VOD_METADATA_FIELDS.map((field) => (
                <TableTh
                  key={field}
                  w={field === 'video_features' ? '16%' : '12%'}
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
            {!visibleCategories.length && (
              <TableTr>
                <TableTd colSpan={8} ta="center" py="xl">
                  <Text size="sm" c="dimmed">
                    No categories match the current filters.
                  </Text>
                  <Button
                    variant="subtle"
                    size="xs"
                    onClick={() => {
                      setFilter('');
                      setStatusFilter(DEFAULT_CATEGORY_VISIBILITY);
                    }}
                  >
                    Reset filters
                  </Button>
                </TableTd>
              </TableTr>
            )}
            {visibleCategories
              .slice((page - 1) * pageSize, page * pageSize)
              .map((category) => (
                <CategoryCard
                  key={category.id}
                  category={category}
                  onConfigure={openConfigure}
                  onPreview={setPreviewCategory}
                  selected={selectedCategoryIds.has(category.id)}
                  onSelect={toggleSelectedCategory}
                  onToggleEnabled={toggleEnabled}
                  previewAvailable={
                    previewAvailableIds === undefined ||
                    !!previewAvailableIds?.has(category.id)
                  }
                  previewUnavailableHint={previewUnavailableHint}
                />
              ))}
          </TableTbody>
        </Table>
      </ScrollArea>
      {paginationVisible &&
        (paginationContainer
          ? createPortal(pagination, paginationContainer)
          : pagination)}
      <M3UGroupContentPreview
        accountId={playlist.id}
        scope={type}
        group={previewCategory}
        onClose={() => setPreviewCategory(null)}
      />
      <StackedModal
        stackId={`vod-category-defaults-${type}`}
        keepVisibleInStack
        opened={!!configuringCategory}
        onClose={closeConfigure}
        size="lg"
        title={`Category defaults · ${configuringCategory?.name || ''}`}
        closeButtonProps={{ 'aria-label': 'Close category defaults' }}
      >
        {configuringCategory && (
          <ScrollArea.Autosize mah="70dvh" offsetScrollbars>
            <VODCategoryMetadataEditor
              key={configuringCategory.id}
              value={categoryMetadata(configuringCategory)}
              languages={MEDIA_LANGUAGE_OPTIONS}
              resolutions={VOD_RESOLUTIONS}
              pickerStackId={`vod-category-metadata-${type}`}
              onApply={applyMetadata}
              disabled={!cleanupValid}
              onDirtyChange={setMetadataDirty}
            >
              <CategoryCleanupFields
                accountId={playlist.id}
                categoryId={configuringCategory.id}
                value={cleanupDraft}
                onChange={setCleanupDraft}
                onValidityChange={setCleanupValid}
              />
            </VODCategoryMetadataEditor>
          </ScrollArea.Autosize>
        )}
      </StackedModal>
      <ConfirmationDialog
        opened={discardConfig}
        onClose={() => setDiscardConfig(false)}
        onConfirm={() => {
          setDiscardConfig(false);
          setConfiguringCategoryId(null);
        }}
        title="Discard unsaved changes?"
        message="Your category changes have not been applied."
        confirmLabel="Discard"
        cancelLabel="Continue editing"
      />
      <Modal
        stackId={`vod-category-bulk-${type}`}
        opened={bulkEditorOpen}
        onClose={closeBulkEditor}
        title={`Edit settings for ${selectedCategoryIds.size} ${selectedCategoryIds.size === 1 ? 'category' : 'categories'}`}
        closeButtonProps={{ 'aria-label': 'Close bulk category settings' }}
      >
        <Stack gap="sm">
          <Paper
            withBorder
            p="sm"
            role="group"
            aria-label="Category status settings"
          >
            <Stack gap="xs">
              <Text fw={600}>General</Text>
              <Select
                label="Status"
                value={bulkSettings.enabled}
                onChange={(value) =>
                  setBulkSettings({ enabled: value || 'keep' })
                }
                data={[
                  { value: 'keep', label: 'Keep unchanged' },
                  { value: 'enabled', label: 'Enabled' },
                  { value: 'disabled', label: 'Disabled' },
                  { value: 'ignored', label: 'Ignored' },
                ]}
              />
            </Stack>
          </Paper>
          {bulkEditorOpen && (
            <VODCategoryMetadataEditor
              bulk
              value={{
                audio_languages: [],
                subtitle_languages: [],
                resolution: '',
                video_features: [],
              }}
              languages={MEDIA_LANGUAGE_OPTIONS}
              resolutions={VOD_RESOLUTIONS}
              pickerStackId={`vod-category-bulk-metadata-${type}`}
              onApply={applyBulkSettings}
            />
          )}
        </Stack>
      </Modal>
    </Stack>
  );
};

export default VODCategoryFilter;
