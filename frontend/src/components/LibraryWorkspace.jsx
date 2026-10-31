import { useEffect, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Checkbox,
  Group,
  Image,
  Loader,
  Modal,
  Stack,
  Table,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { Ban, Eye, LockKeyhole, Search, Wrench } from 'lucide-react';
import useAuthStore from '../store/auth';
import useLibraryStore from '../store/useLibraryStore';
import { notifyLibraryError } from '../utils/libraryFeedback.js';
import { isVodMoviesEnabled, isVodSeriesEnabled } from '../utils/vodAccess';
import { VOD_METADATA_LABELS } from '../utils/vodSourceMetadata';
import MetadataOriginBadges from './MetadataOriginBadges.jsx';
import ListPagination from './ListPagination.jsx';
import { LibrarySourceEditor } from './LibraryDialogs.jsx';
import {
  libraryMetadataStatus,
  libraryRowTitle,
} from '../utils/libraryMetadataStatus.js';
import LibraryFilters from './LibraryFilters.jsx';
import LibraryMetadataDialog from './LibraryMetadataDialog.jsx';
import VODCard from './cards/VODCard.jsx';
import SeriesCard from './cards/SeriesCard.jsx';
import layout from './VODLayout.module.css';
import classes from './LibraryWorkspace.module.css';

const NO_CHANGE = () => {};
const PAGE_SIZES = [12, 24, 48, 96];
const TABLE_METADATA_FIELDS = [
  'audio_languages',
  'subtitle_languages',
  'resolution',
  'container_extensions',
  'video_features',
];

function LibraryArtwork({ src, name }) {
  const [failedSrc, setFailedSrc] = useState(null);
  return src && failedSrc !== src ? (
    <Image
      src={src}
      alt={`Artwork for ${name}`}
      loading="lazy"
      h={54}
      w={40}
      fit="contain"
      radius="sm"
      onError={() => setFailedSrc(src)}
    />
  ) : (
    <div className={classes.artworkPlaceholder} aria-hidden="true" />
  );
}

// Values without a reported origin, such as the file format, come from the provider.
const rowOrigins = (row) =>
  Object.fromEntries(
    TABLE_METADATA_FIELDS.map((field) => [
      field,
      row.metadata_origins?.[field] ||
        Object.fromEntries(
          (row.metadata_summary?.[field] || []).map((value) => [
            value,
            field === 'container_extensions' ? 'provider' : undefined,
          ])
        ),
    ])
  );

export default function LibraryWorkspace({
  view,
  displayMode = 'list',
  onPreview,
  onChanged = NO_CHANGE,
  children,
}) {
  const user = useAuthStore((state) => state.user);
  const admin = user?.user_level >= 10;
  const {
    filters,
    page,
    pageSize,
    rows,
    count,
    loading,
    error,
    options,
    optionsError,
    job,
    setFilters,
    setPage,
    setPageSize,
    fetchContent,
    fetchOptions,
    fetchJob,
  } = useLibraryStore();
  const [selected, setSelected] = useState({});
  const [allMatching, setAllMatching] = useState(false);
  const [dialog, setDialog] = useState(null);
  useEffect(() => {
    if (admin) fetchJob();
  }, [admin, fetchJob]);
  useEffect(() => {
    if (error) notifyLibraryError(new Error(error));
  }, [error]);
  useEffect(() => {
    if (optionsError)
      notifyLibraryError(new Error(optionsError), 'Library filters');
  }, [optionsError]);
  const [pageSizeReady, setPageSizeReady] = useState(false);
  const sources = view === 'sources';
  const moviesEnabled = isVodMoviesEnabled(user);
  const seriesEnabled = isVodSeriesEnabled(user);
  const type =
    moviesEnabled && seriesEnabled ? 'all' : moviesEnabled ? 'movie' : 'series';

  useEffect(() => {
    const stored = Number(localStorage.getItem('vodsPageSize'));
    if (PAGE_SIZES.includes(stored) && stored !== pageSize) setPageSize(stored);
    setPageSizeReady(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- hydrate before the first request only
  }, []);
  useEffect(() => {
    setFilters({ view, ...(type !== 'all' ? { type } : {}) });
  }, [view, type, setFilters]);
  useEffect(() => {
    fetchOptions();
  }, [fetchOptions, filters.type, filters.account, filters.category]);
  useEffect(() => {
    if (pageSizeReady && filters.view === view) fetchContent();
  }, [view, filters, page, pageSize, pageSizeReady, fetchContent]);
  useEffect(() => {
    setSelected({});
    setAllMatching(false);
  }, [filters, displayMode]);

  const chosen = allMatching ? [] : Object.values(selected);
  const selectedCount = allMatching
    ? Math.max(0, count - Object.keys(selected).length)
    : chosen.length;
  const selection = allMatching
    ? {
        all_matching: true,
        filters: Object.fromEntries(
          Object.entries(filters).filter(
            ([, value]) => value !== '' && value != null
          )
        ),
        excluded: Object.values(selected).map((row) => ({
          content_type: row.content_type,
          id: sources ? row.source_id : row.content_id,
        })),
      }
    : {
        items: chosen.map((row) => ({
          content_type: row.content_type,
          id: row.content_id,
        })),
      };
  const refresh = () => {
    fetchContent();
    onChanged();
  };
  const icon = (label, Icon, onClick, disabled = false, color = 'blue') => (
    <Tooltip label={label}>
      <ActionIcon
        aria-label={label}
        variant="subtle"
        color={color}
        onClick={onClick}
        disabled={disabled}
      >
        <Icon size={17} />
      </ActionIcon>
    </Tooltip>
  );

  return (
    <Modal.Stack>
      <Stack gap="md">
        <div className={classes.toolbar}>
          <TextInput
            aria-label="Search titles"
            placeholder="Search titles…"
            leftSection={<Search size={16} />}
            value={filters.search}
            onChange={(e) => setFilters({ search: e.currentTarget.value })}
            className={classes.search}
          />
          <Group
            role="group"
            aria-label="Library actions"
            gap="xs"
            wrap="nowrap"
            style={{ flexShrink: 0 }}
          >
            <LibraryFilters
              filters={filters}
              onChange={setFilters}
              options={options}
              moviesEnabled={moviesEnabled}
              seriesEnabled={seriesEnabled}
              admin={admin}
            />
            {error && (
              <Button size="compact-sm" variant="subtle" onClick={fetchContent}>
                Retry library
              </Button>
            )}
          </Group>
          {admin && (sources || displayMode === 'list') && (
            <Group gap="xs" ml="auto">
              {selectedCount > 0 && (
                <Button
                  variant="subtle"
                  size="compact-sm"
                  onClick={() => {
                    setSelected({});
                    setAllMatching(false);
                  }}
                >
                  Clear
                </Button>
              )}
              <Button
                leftSection={<Wrench size={16} />}
                disabled={!selectedCount}
                onClick={() =>
                  setDialog(
                    sources
                      ? {
                          type: 'source',
                          items: chosen,
                          selection: allMatching ? selection : undefined,
                          count: selectedCount,
                        }
                      : {
                          type: 'metadata',
                          selection,
                          items: chosen,
                          count: selectedCount,
                        }
                  )
                }
              >
                Edit ({selectedCount})
              </Button>
            </Group>
          )}
        </div>
        {!sources && displayMode === 'posters' ? (
          <div className={layout.grid} aria-busy={loading}>
            {rows.map((row) => {
              const content = {
                ...row,
                id: row.content_id,
                logo: row.poster_url ? { cache_url: row.poster_url } : null,
              };
              return (
                <div
                  key={row.key}
                  className={classes.poster}
                  data-blocked={row.library_blocked || undefined}
                >
                  {row.content_type === 'series' ? (
                    <SeriesCard
                      series={content}
                      compact
                      onClick={() => onPreview(row)}
                    />
                  ) : (
                    <VODCard
                      compact
                      vod={content}
                      onClick={() => onPreview(row)}
                    />
                  )}
                  {row.library_blocked && (
                    <span
                      className={classes.blockedOverlay}
                      role="img"
                      aria-label="Blocked globally"
                    >
                      <Ban size={36} />
                    </span>
                  )}
                </div>
              );
            })}
            {loading && <Text role="status">Loading library…</Text>}
            {!loading && !error && !rows.length && (
              <Text c="dimmed">No titles match these filters.</Text>
            )}
          </div>
        ) : (
          <div className={classes.tableFrame}>
            <Table
              className={classes.table}
              verticalSpacing="sm"
              horizontalSpacing="md"
              highlightOnHover
              striped
              stickyHeader
            >
              <Table.Thead>
                <Table.Tr>
                  {admin && (
                    <Table.Th w={42}>
                      <Checkbox
                        aria-label={`Select all matching ${sources ? 'sources' : 'titles'}`}
                        checked={count > 0 && selectedCount === count}
                        indeterminate={
                          selectedCount > 0 && selectedCount < count
                        }
                        disabled={loading || !count}
                        onChange={(e) => {
                          const checked = e.currentTarget.checked;
                          setAllMatching(checked);
                          setSelected({});
                        }}
                      />
                    </Table.Th>
                  )}
                  <Table.Th w={62}>Artwork</Table.Th>
                  <Table.Th>Title</Table.Th>
                  <Table.Th className={sources ? classes.source : undefined}>
                    {sources ? 'Source' : 'Sources'}
                  </Table.Th>
                  <Table.Th className={classes.genre}>Genre</Table.Th>
                  <Table.Th w={120}>Metadata</Table.Th>
                  {TABLE_METADATA_FIELDS.map((field) => (
                    <Table.Th key={field}>
                      {field === 'container_extensions'
                        ? 'Format'
                        : VOD_METADATA_LABELS[field]}
                    </Table.Th>
                  ))}
                  <Table.Th ta="center" w={84}>
                    Details
                  </Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {rows.map((row) => {
                  const title = libraryRowTitle(row, sources);
                  const status = libraryMetadataStatus(row);
                  return (
                    <Table.Tr
                      key={row.key}
                      data-blocked={row.library_blocked || undefined}
                    >
                      {admin && (
                        <Table.Td>
                          <Checkbox
                            aria-label={`Select ${title}`}
                            checked={
                              allMatching
                                ? !selected[row.key]
                                : !!selected[row.key]
                            }
                            onChange={(e) => {
                              const checked = e.currentTarget.checked;
                              setSelected((current) => {
                                const next = { ...current };
                                if (checked !== allMatching)
                                  next[row.key] = row;
                                else delete next[row.key];
                                return next;
                              });
                            }}
                          />
                        </Table.Td>
                      )}
                      <Table.Td>
                        <LibraryArtwork src={row.poster_url} name={row.name} />
                      </Table.Td>
                      <Table.Td className={classes.title}>
                        {row.library_blocked && (
                          <span
                            className={classes.blockedListIcon}
                            role="img"
                            aria-label="Blocked globally"
                          >
                            <Ban size={22} />
                          </span>
                        )}
                        <Tooltip label={title} multiline maw={420} withArrow>
                          <Text
                            fw={500}
                            size="sm"
                            lineClamp={2}
                            className={classes.wrappedText}
                          >
                            {title}
                          </Text>
                        </Tooltip>
                        {sources &&
                          row.clean_title &&
                          row.clean_title !== title && (
                            <Text
                              size="xs"
                              c="dimmed"
                              lineClamp={1}
                              title={row.clean_title}
                              className={classes.wrappedText}
                            >
                              Clean: {row.clean_title}
                            </Text>
                          )}
                        <Text size="xs" c="dimmed">
                          {row.content_type === 'movie' ? 'Movie' : 'Series'} ·{' '}
                          {row.year || '—'}
                        </Text>
                      </Table.Td>
                      <Table.Td
                        className={sources ? classes.source : undefined}
                      >
                        {sources ? (
                          <Stack gap={2}>
                            <Text
                              size="sm"
                              lineClamp={2}
                              className={classes.wrappedText}
                            >
                              {row.account?.name}
                            </Text>
                            <Text
                              size="xs"
                              c="dimmed"
                              lineClamp={2}
                              className={classes.wrappedText}
                            >
                              {row.category?.name || '—'}
                            </Text>
                          </Stack>
                        ) : (
                          <Text size="sm">{row.source_count}</Text>
                        )}
                      </Table.Td>
                      <Table.Td className={classes.genre}>
                        <Tooltip
                          label={row.genre || '—'}
                          multiline
                          maw={420}
                          withArrow
                        >
                          <Text
                            size="sm"
                            lineClamp={2}
                            className={classes.wrappedText}
                          >
                            {row.genre || '—'}
                          </Text>
                        </Tooltip>
                      </Table.Td>
                      <Table.Td>
                        <Tooltip
                          label={`${status.label}${row.tmdb_id && !row.enriched_at ? ' · TMDB details not enriched' : ''}`}
                          multiline
                          maw={320}
                          withArrow
                          events={{ hover: true, focus: true, touch: true }}
                        >
                          <Badge
                            color={
                              ['failed', 'ambiguous', 'not_found'].includes(
                                row.metadata_status
                              )
                                ? status.color
                                : row.enriched_at
                                  ? 'blue'
                                  : 'gray'
                            }
                            variant="light"
                            size="sm"
                            tabIndex={0}
                            aria-label={status.label}
                          >
                            {row.enriched_at ? 'TMDB' : 'Provider'}
                          </Badge>
                        </Tooltip>
                      </Table.Td>
                      {TABLE_METADATA_FIELDS.map((field) => (
                        <Table.Td key={field}>
                          <MetadataOriginBadges
                            origins={rowOrigins(row)}
                            field={field}
                          />
                        </Table.Td>
                      ))}
                      <Table.Td>
                        <div className={classes.actions}>
                          <span className={classes.lockStatus}>
                            {row.metadata_locked && (
                              <Tooltip
                                label="Automatic metadata matching is locked"
                                withArrow
                              >
                                <LockKeyhole
                                  size={15}
                                  aria-label="Automatic metadata matching locked"
                                />
                              </Tooltip>
                            )}
                          </span>
                          {icon(`Preview ${title}`, Eye, () => onPreview(row))}
                        </div>
                      </Table.Td>
                    </Table.Tr>
                  );
                })}
              </Table.Tbody>
            </Table>
            {loading && (
              <Group justify="center" p="md">
                <Loader size="sm" />
                <Text size="sm">Loading library…</Text>
              </Group>
            )}
            {!loading && !error && !rows.length && (
              <Text p="xl" ta="center" c="dimmed">
                No titles match these filters.
              </Text>
            )}
          </div>
        )}
        {(!loading || rows.length > 0) && (
          <ListPagination
            page={page}
            pageSize={pageSize}
            total={count}
            onPageChange={setPage}
            onPageSizeChange={(value) => {
              setPageSize(value);
              localStorage.setItem('vodsPageSize', String(value));
            }}
            pageSizeOptions={PAGE_SIZES}
            disabled={loading}
            itemLabel={sources ? 'Sources' : 'Titles'}
          />
        )}
        {dialog?.type === 'source' && (
          <LibrarySourceEditor
            items={dialog.items}
            selection={dialog.selection}
            selectionCount={dialog.count}
            onClose={() => setDialog(null)}
            onSaved={refresh}
          />
        )}
        {dialog?.type === 'metadata' && (
          <LibraryMetadataDialog
            selection={dialog.selection}
            items={dialog.items}
            selectionCount={dialog.count}
            job={job}
            onPreview={onPreview}
            onClose={() => setDialog(null)}
            onChanged={() => {
              setSelected({});
              setAllMatching(false);
              refresh();
            }}
          />
        )}
        {children}
      </Stack>
    </Modal.Stack>
  );
}
