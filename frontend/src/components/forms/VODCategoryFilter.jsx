import React, { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Button,
  Checkbox,
  Flex,
  Group,
  Modal,
  ScrollArea,
  SegmentedControl,
  Stack,
  Switch,
  Table,
  TableTbody,
  TableTd,
  TableTh,
  TableThead,
  TableTr,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { Eye, Info, Settings2 } from 'lucide-react';
import useVODStore from '../../store/useVODStore';
import API from '../../api';
import { showNotification } from '../../utils/notificationUtils';
import VODMetadataFields from '../VODMetadataFields.jsx';
import M3UGroupRules from './M3UGroupRules.jsx';
import { normalizeLanguageCodes } from '../../utils/languageCodes.js';
import M3UDeveloperCatalog from './M3UDeveloperCatalog.jsx';
import { showVODProfileRebuildNotice } from '../../utils/vodProfileUpdates.js';
import ListPagination from '../ListPagination.jsx';
import { videoFeatureLabel } from '../../utils/vodMetadataOptions.js';

const VODCategoryFilter = ({
  playlist = null,
  categoryStates,
  setCategoryStates,
  type,
  mode = 'account',
  rules = [],
  onRulesChange,
  accountOptions = [],
}) => {
  const profileMode = mode === 'profile';
  const categories = useVODStore((s) => s.categories);
  const [filter, setFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [selected, setSelected] = useState(new Set());
  const [editorOpen, setEditorOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [rulesOpen, setRulesOpen] = useState(false);
  const [previewCategory, setPreviewCategory] = useState(null);
  const [cleanupCategory, setCleanupCategory] = useState(null);
  const [cleanupPattern, setCleanupPattern] = useState('');
  const [cleanupCaseSensitive, setCleanupCaseSensitive] = useState(false);
  const [savingCleanup, setSavingCleanup] = useState(false);
  const [cleanupPreviewPage, setCleanupPreviewPage] = useState(1);
  const [cleanupPreviewPageSize, setCleanupPreviewPageSize] = useState(25);
  const [cleanupPreview, setCleanupPreview] = useState({
    results: [],
    page_match_count: 0,
    total_in_category: 0,
    loading: false,
    error: '',
  });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [metadataModes, setMetadataModes] = useState({
    audio_languages: 'keep',
    subtitle_languages: 'keep',
    resolution: 'keep',
    video_features: 'keep',
  });
  const [metadata, setMetadata] = useState({
    audio_languages: [],
    subtitle_languages: [],
    resolution: '',
    video_features: [],
  });

  useEffect(() => {
    if (profileMode) return;
    if (Object.keys(categories).length === 0) return;

    setCategoryStates(
      Object.values(categories)
        .filter(
          (category) =>
            category.m3u_accounts.find(
              (account) => account.m3u_account == playlist?.id
            ) && category.category_type == type
        )
        .map((category) => {
          const relation = category.m3u_accounts.find(
            (account) => account.m3u_account == playlist?.id
          );
          return {
            ...category,
            relation_id: relation.id,
            metadata_defaults: relation.metadata_defaults || {},
            title_cleanup: relation.title_cleanup || {},
            enabled: relation.enabled || false,
            original_enabled: relation.enabled,
          };
        })
    );
  }, [categories, playlist?.id, profileMode, setCategoryStates, type]);

  const rowId = (category) => String(category.relation_id ?? category.id);

  const visible = useMemo(
    () =>
      categoryStates
        .filter((category) => {
          const matchesText = category.name
            .concat(' ', category.accountName || '')
            .toLowerCase()
            .includes(filter.toLowerCase());
          const matchesStatus =
            statusFilter === 'all' ||
            (statusFilter === 'enabled' && category.enabled) ||
            (statusFilter === 'disabled' && !category.enabled);
          return matchesText && matchesStatus;
        })
        .sort((a, b) => a.name.localeCompare(b.name)),
    [categoryStates, filter, statusFilter]
  );
  const pageCount = Math.max(1, Math.ceil(visible.length / pageSize));
  const pagedCategories = visible.slice((page - 1) * pageSize, page * pageSize);

  useEffect(() => {
    setPage(1);
  }, [filter, statusFilter, pageSize]);

  useEffect(() => {
    if (page > pageCount) setPage(pageCount);
  }, [page, pageCount]);

  const updateSelected = (changes) => {
    setCategoryStates((current) =>
      current.map((category) =>
        selected.has(rowId(category)) ? { ...category, ...changes } : category
      )
    );
  };

  const toggleSelected = (id, checked) => {
    setSelected((current) => {
      const next = new Set(current);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const toggleVisibleSelection = (checked) => {
    setSelected((current) => {
      const next = new Set(current);
      visible.forEach((category) =>
        checked ? next.add(rowId(category)) : next.delete(rowId(category))
      );
      return next;
    });
  };

  const saveBulkMetadata = async () => {
    const values = {};
    for (const field of Object.keys(metadataModes)) {
      if (metadataModes[field] === 'keep') continue;
      if (metadataModes[field] === 'clear') {
        values[field] = field === 'resolution' ? '' : [];
      } else {
        values[field] =
          field === 'resolution'
            ? metadata[field]
            : field === 'video_features'
              ? metadata[field]
              : normalizeLanguageCodes(metadata[field]);
      }
    }
    const targets = categoryStates.filter((category) =>
      selected.has(rowId(category))
    );
    setSaving(true);
    try {
      const response = await API.bulkUpdateVODCategoryMetadata(
        targets.map((category) => category.relation_id),
        values
      );
      setCategoryStates((current) =>
        current.map((category) =>
          selected.has(rowId(category))
            ? {
                ...category,
                metadata_defaults: {
                  ...(category.metadata_defaults || {}),
                  ...values,
                },
              }
            : category
        )
      );
      showNotification({
        title: 'Category metadata updated',
        message: `${targets.length} categories were updated. These defaults have lower priority than manual source metadata.`,
        color: 'green',
      });
      setEditorOpen(false);
      showVODProfileRebuildNotice(response);
    } finally {
      setSaving(false);
    }
  };

  const openMetadataEditor = () => {
    setMetadata({
      audio_languages: [],
      subtitle_languages: [],
      resolution: '',
      video_features: [],
    });
    setMetadataModes({
      audio_languages: 'keep',
      subtitle_languages: 'keep',
      resolution: 'keep',
      video_features: 'keep',
    });
    setEditorOpen(true);
  };

  const allVisibleSelected =
    visible.length > 0 &&
    visible.every((category) => selected.has(rowId(category)));

  const openCleanupEditor = (category) => {
    const cleanup = category.title_cleanup || {};
    setCleanupCategory(category);
    setCleanupPattern(cleanup.pattern || '');
    setCleanupCaseSensitive(cleanup.case_sensitive === true);
    setCleanupPreviewPage(1);
  };

  useEffect(() => {
    const pattern = cleanupPattern.trim();
    if (!cleanupCategory) {
      setCleanupPreview({
        results: [],
        page_match_count: 0,
        total_in_category: 0,
        loading: false,
        error: '',
      });
      return undefined;
    }

    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setCleanupPreview((current) => ({
        ...current,
        loading: true,
        error: '',
      }));
      try {
        const response = await API.previewVODCategoryTitleCleanup(
          cleanupCategory.relation_id,
          pattern
            ? {
                pattern: cleanupPattern,
                case_sensitive: cleanupCaseSensitive,
              }
            : {},
          {
            page: cleanupPreviewPage,
            pageSize: cleanupPreviewPageSize,
            signal: controller.signal,
          }
        );
        setCleanupPreview({
          results: response.results || [],
          page_match_count: response.page_match_count || 0,
          total_in_category: response.total_in_category || 0,
          loading: false,
          error: response.error || '',
        });
      } catch (error) {
        if (error?.name === 'AbortError') return;
        setCleanupPreview({
          results: [],
          page_match_count: 0,
          total_in_category: 0,
          loading: false,
          error:
            error?.body?.title_cleanup ||
            error?.body?.detail ||
            error?.message ||
            'The preview could not be created.',
        });
      }
    }, 400);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [
    cleanupCaseSensitive,
    cleanupCategory,
    cleanupPattern,
    cleanupPreviewPage,
    cleanupPreviewPageSize,
  ]);

  const saveTitleCleanup = async () => {
    if (!cleanupCategory) return;
    setSavingCleanup(true);
    try {
      const response = await API.updateVODCategoryTitleCleanup(
        cleanupCategory.relation_id,
        cleanupPattern.trim()
          ? {
              pattern: cleanupPattern,
              case_sensitive: cleanupCaseSensitive,
            }
          : {}
      );
      setCategoryStates((current) =>
        current.map((category) =>
          rowId(category) === rowId(cleanupCategory)
            ? { ...category, title_cleanup: response.title_cleanup || {} }
            : category
        )
      );
      showNotification({
        title: 'Category title removal saved',
        message: cleanupPattern.trim()
          ? 'Matching text is removed after global prefix and release-year cleanup for new or unlocked titles. Locked titles stay unchanged until cleanup is applied again.'
          : 'The category-specific removal rule was cleared. Global prefix and release-year cleanup still applies.',
        color: 'green',
      });
      setCleanupCategory(null);
    } catch (error) {
      showNotification({
        title: 'Category title removal was not saved',
        message:
          error?.body?.title_cleanup ||
          error?.body?.detail ||
          error?.message ||
          'Check the removal expression and try again.',
        color: 'red',
      });
    } finally {
      setSavingCleanup(false);
    }
  };

  return (
    <>
      <Stack pt="sm" h="100%" mih={0}>
        <Group justify="flex-start" align="center">
          <Button
            variant="default"
            size="xs"
            onClick={() => setRulesOpen(true)}
          >
            Import rules
          </Button>
          {!profileMode && (
            <Text size="xs" c="dimmed">
              New unmatched categories are imported inactive.
            </Text>
          )}
        </Group>

        <Flex gap="sm" align="end" wrap="wrap">
          <TextInput
            label={
              profileMode ? 'Search account or category' : 'Search categories'
            }
            placeholder="Filter categories..."
            value={filter}
            onChange={(event) => setFilter(event.currentTarget.value)}
            style={{ flex: 1 }}
            size="xs"
          />
          <SegmentedControl
            value={statusFilter}
            onChange={setStatusFilter}
            size="xs"
            data={[
              { label: 'All', value: 'all' },
              {
                label: profileMode ? 'Allowed' : 'Enabled',
                value: 'enabled',
              },
              {
                label: profileMode ? 'Blocked' : 'Disabled',
                value: 'disabled',
              },
            ]}
          />
          <Button
            variant="default"
            size="xs"
            disabled={!selected.size}
            onClick={() => updateSelected({ enabled: true })}
          >
            {profileMode ? 'Allow selected' : 'Enable selected'}
          </Button>
          <Button
            variant="default"
            size="xs"
            disabled={!selected.size}
            onClick={() => updateSelected({ enabled: false })}
          >
            {profileMode ? 'Block selected' : 'Disable selected'}
          </Button>
          {!profileMode ? (
            <Button
              variant="default"
              size="xs"
              disabled={!selected.size}
              onClick={openMetadataEditor}
            >
              Edit metadata ({selected.size})
            </Button>
          ) : null}
        </Flex>

        <ScrollArea style={{ flex: 1, minHeight: 0 }}>
          <Table striped highlightOnHover withTableBorder stickyHeader>
            <TableThead>
              <TableTr>
                <TableTh w={44}>
                  <Checkbox
                    aria-label="Select visible categories"
                    checked={allVisibleSelected}
                    onChange={(event) =>
                      toggleVisibleSelection(event.currentTarget.checked)
                    }
                  />
                </TableTh>
                {profileMode && <TableTh>M3U account</TableTh>}
                <TableTh>Category</TableTh>
                <TableTh w={110}>{profileMode ? 'Allowed' : 'Enabled'}</TableTh>
                <TableTh>
                  <Group gap={4} wrap="nowrap">
                    DUB
                    <Tooltip label="Approximate audio languages used only to seed newly imported sources. Manual and observed metadata has higher priority.">
                      <Info size={13} aria-label="About DUB defaults" />
                    </Tooltip>
                  </Group>
                </TableTh>
                <TableTh>
                  <Group gap={4} wrap="nowrap">
                    SUB
                    <Tooltip label="Approximate subtitle languages used only to seed newly imported sources. Manual and observed metadata has higher priority.">
                      <Info size={13} aria-label="About SUB defaults" />
                    </Tooltip>
                  </Group>
                </TableTh>
                <TableTh w={120}>
                  <Group gap={4} wrap="nowrap">
                    Resolution
                    <Tooltip label="Approximate maximum resolution used only to seed newly imported sources.">
                      <Info size={13} aria-label="About resolution defaults" />
                    </Tooltip>
                  </Group>
                </TableTh>
                <TableTh w={180}>Features</TableTh>
                <TableTh w={88} ta="center">
                  Actions
                </TableTh>
              </TableTr>
            </TableThead>
            <TableTbody>
              {pagedCategories.map((category) => (
                <TableTr key={rowId(category)}>
                  <TableTd>
                    <Checkbox
                      aria-label={`Select ${category.name}`}
                      checked={selected.has(rowId(category))}
                      onChange={(event) =>
                        toggleSelected(
                          rowId(category),
                          event.currentTarget.checked
                        )
                      }
                    />
                  </TableTd>
                  {profileMode && <TableTd>{category.accountName}</TableTd>}
                  <TableTd>{category.name}</TableTd>
                  <TableTd>
                    <Button
                      size="compact-xs"
                      color={category.enabled ? 'green' : 'gray'}
                      variant={category.enabled ? 'filled' : 'light'}
                      aria-label={`${profileMode ? 'Allow' : 'Enable'} ${category.name}`}
                      aria-pressed={category.enabled}
                      onClick={() =>
                        setCategoryStates((current) =>
                          current.map((item) =>
                            rowId(item) === rowId(category)
                              ? {
                                  ...item,
                                  enabled: !item.enabled,
                                }
                              : item
                          )
                        )
                      }
                    >
                      {category.enabled
                        ? profileMode
                          ? 'Allowed'
                          : 'Active'
                        : profileMode
                          ? 'Blocked'
                          : 'Inactive'}
                    </Button>
                  </TableTd>
                  <TableTd>
                    {(category.metadata_defaults?.audio_languages || []).join(
                      ', '
                    ) || '—'}
                  </TableTd>
                  <TableTd>
                    {(
                      category.metadata_defaults?.subtitle_languages || []
                    ).join(', ') || '—'}
                  </TableTd>
                  <TableTd>
                    {category.metadata_defaults?.resolution || '—'}
                  </TableTd>
                  <TableTd>
                    {(category.metadata_defaults?.video_features || [])
                      .map(videoFeatureLabel)
                      .join(', ') || '—'}
                  </TableTd>
                  <TableTd ta="center">
                    <Group gap={2} justify="center" wrap="nowrap">
                      {!profileMode && (
                        <Tooltip
                          label="Remove category-specific title text"
                          withArrow
                        >
                          <ActionIcon
                            variant={
                              category.title_cleanup?.pattern
                                ? 'light'
                                : 'subtle'
                            }
                            color={
                              category.title_cleanup?.pattern ? 'blue' : 'gray'
                            }
                            aria-label={`Edit title removal for ${category.name}`}
                            onClick={() => openCleanupEditor(category)}
                          >
                            <Settings2 size={16} />
                          </ActionIcon>
                        </Tooltip>
                      )}
                      <Tooltip label="Preview imported content" withArrow>
                        <ActionIcon
                          variant="subtle"
                          aria-label={`Preview ${category.name}`}
                          onClick={() => setPreviewCategory(category)}
                        >
                          <Eye size={16} />
                        </ActionIcon>
                      </Tooltip>
                    </Group>
                  </TableTd>
                </TableTr>
              ))}
            </TableTbody>
          </Table>
        </ScrollArea>

        <ListPagination
          page={page}
          pageSize={pageSize}
          total={visible.length}
          onPageChange={setPage}
          onPageSizeChange={setPageSize}
        />
      </Stack>

      <Modal
        opened={editorOpen}
        onClose={() => setEditorOpen(false)}
        title={`Edit defaults for ${selected.size} categories`}
      >
        <Stack>
          <Text size="sm" c="dimmed">
            Choose Keep, Set, or Clear for each field. These are approximate
            import assumptions; manual and observed source metadata remains
            authoritative.
          </Text>
          <VODMetadataFields
            fields={[
              'audio_languages',
              'subtitle_languages',
              'resolution',
              'video_features',
            ]}
            labels={{
              audio_languages: 'DUB',
              subtitle_languages: 'SUB',
            }}
            value={metadata}
            onChange={setMetadata}
            modes={metadataModes}
            onModesChange={setMetadataModes}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setEditorOpen(false)}>
              Cancel
            </Button>
            <Button loading={saving} onClick={saveBulkMetadata}>
              Apply to selected
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={!!cleanupCategory}
        onClose={() => setCleanupCategory(null)}
        title={`Remove text from titles · ${cleanupCategory?.name || ''}`}
        size="lg"
      >
        <Stack>
          <Button
            component="a"
            href="/settings#vod-title-cleanup"
            target="_blank"
            rel="noopener noreferrer"
            variant="subtle"
            size="compact-sm"
            style={{ alignSelf: 'flex-start' }}
          >
            Open global title cleanup settings
          </Button>
          <TextInput
            label="Text to remove (regular expression)"
            description="Use | to remove more than one pattern. Every match is removed."
            placeholder={'-\\d+-\\s*|\\b4K\\b'}
            value={cleanupPattern}
            onChange={(event) => {
              setCleanupPattern(event.currentTarget.value);
              setCleanupPreviewPage(1);
            }}
          />
          <Switch
            label="Case-sensitive matching"
            checked={cleanupCaseSensitive}
            onChange={(event) => {
              setCleanupCaseSensitive(event.currentTarget.checked);
              setCleanupPreviewPage(1);
            }}
          />
          <Stack gap={6}>
            <Text size="sm" fw={600}>
              Final title preview
            </Text>
            {cleanupPreview.loading && (
              <Text size="xs" c="dimmed">
                Preparing title preview...
              </Text>
            )}
            {cleanupPreview.error && (
              <Text size="xs" c="red.5">
                Removal expression error: {cleanupPreview.error}
              </Text>
            )}
            {!cleanupPreview.loading && !cleanupPreview.error && (
              <>
                <Text size="xs" c="dimmed">
                  {cleanupPreview.total_in_category}{' '}
                  {cleanupPreview.total_in_category === 1 ? 'title' : 'titles'}{' '}
                  in this category.
                  {cleanupPattern.trim() && (
                    <>
                      {' '}
                      {cleanupPreview.page_match_count}{' '}
                      {cleanupPreview.page_match_count === 1
                        ? 'title on this page contains'
                        : 'titles on this page contain'}{' '}
                      text that will be removed.
                    </>
                  )}
                </Text>
                {cleanupPreview.results.length === 0 ? (
                  <Text size="xs" c="dimmed">
                    No titles are available on this page.
                  </Text>
                ) : (
                  <ScrollArea h="min(32vh, 300px)" offsetScrollbars>
                    <Table striped withTableBorder>
                      <TableThead>
                        <TableTr>
                          <TableTh>Provider title</TableTh>
                          <TableTh>Clean title</TableTh>
                          <TableTh w={90}>Year</TableTh>
                        </TableTr>
                      </TableThead>
                      <TableTbody>
                        {cleanupPreview.results.map((row) => (
                          <TableTr
                            key={`${row.content_type}:${row.relation_id}`}
                          >
                            <TableTd>{row.before || '—'}</TableTd>
                            <TableTd>
                              <Text c={row.changed ? 'teal.4' : 'dimmed'}>
                                {row.after || '—'}
                              </Text>
                            </TableTd>
                            <TableTd>{row.year || '—'}</TableTd>
                          </TableTr>
                        ))}
                      </TableTbody>
                    </Table>
                  </ScrollArea>
                )}
                <ListPagination
                  page={cleanupPreviewPage}
                  pageSize={cleanupPreviewPageSize}
                  total={cleanupPreview.total_in_category}
                  onPageChange={setCleanupPreviewPage}
                  onPageSizeChange={(value) => {
                    setCleanupPreviewPageSize(value);
                    setCleanupPreviewPage(1);
                  }}
                  pageSizes={[10, 25, 50, 100, 250]}
                />
              </>
            )}
          </Stack>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setCleanupCategory(null)}>
              Cancel
            </Button>
            <Button loading={savingCleanup} onClick={saveTitleCleanup}>
              Save
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={!!previewCategory}
        onClose={() => setPreviewCategory(null)}
        title={`Preview imported ${type === 'movie' ? 'movies' : 'series'}`}
        size="85vw"
      >
        {previewCategory && (
          <M3UDeveloperCatalog
            accountId={profileMode ? previewCategory.accountId : playlist?.id}
            initialScope={type}
            lockedScope
            initialCategory={String(
              previewCategory.category_id ?? previewCategory.id
            )}
            summaryOnly
          />
        )}
      </Modal>

      <Modal
        opened={rulesOpen}
        onClose={() => setRulesOpen(false)}
        title={`${type === 'movie' ? 'Movie' : 'Series'} import rules`}
        size="95vw"
        scrollAreaComponent={Modal.NativeScrollArea}
      >
        <M3UGroupRules
          accountId={playlist?.id}
          scope={type}
          mode={mode}
          value={rules}
          onChange={onRulesChange}
          accountOptions={accountOptions}
          categoryRows={categoryStates}
        />
      </Modal>
    </>
  );
};

export default VODCategoryFilter;
