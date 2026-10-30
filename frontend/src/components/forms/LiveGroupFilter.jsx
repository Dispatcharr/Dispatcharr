import React, {
  Suspense,
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { createPortal } from 'react-dom';
import {
  ActionIcon,
  Anchor,
  Box,
  Button,
  Checkbox,
  Flex,
  Loader,
  Group,
  Paper,
  ScrollArea,
  Select,
  Table,
  TableThead,
  TableTbody,
  TableTr,
  TableTh,
  TableTd,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { AlertTriangle, Eye, Info, Settings as Cog } from 'lucide-react';
import ListPagination from '../ListPagination.jsx';
import M3UGroupContentPreview from './M3UGroupContentPreview.jsx';
import CategoryVisibilityFilter from './CategoryVisibilityFilter.jsx';
import CategoryStatusBadge from './CategoryStatusBadge.jsx';
import {
  DEFAULT_CATEGORY_VISIBILITY,
  matchesCategoryVisibility,
  categoryStatusPatch,
} from '../../utils/categoryVisibility.js';
import StreamFilterControl from './StreamFilterControl.jsx';
import editorClasses from './AccountEditor.module.css';
import GroupConfigureModal from './GroupConfigureModal';
import StackedModal from '../StackedModal.jsx';
import useChannelsStore from '../../store/channels';
import useStreamProfilesStore from '../../store/streamProfiles';
import { useChannelLogoSelection } from '../../hooks/useSmartLogos';
import useLiveCategoryContent from '../../hooks/useLiveCategoryContent.js';
import AutoSyncBasic from './AutoSyncBasic.jsx';
import ErrorBoundary from '../ErrorBoundary.jsx';
import { computeRangeOverlapsFor } from '../../utils/forms/AutoSyncBasicUtils.js';
const AutoSyncAdvanced = React.lazy(() => import('./AutoSyncAdvanced.jsx'));
const LogoForm = React.lazy(() => import('./Logo.jsx'));
import {
  abortTimers,
  computeAutoSyncStart,
  getChannelsInRange,
  getEPGs,
  getRegexOptions,
  getStreamsRegexPreview,
  isExpectedOccupantForGroup,
  effectiveSyncGroupId,
  isGroupVisible,
  rangeFor,
} from '../../utils/forms/LiveGroupFilterUtils.js';
import { getM3UStreamLabel } from '../../utils/forms/M3uSetupUtils.js';

const EMPTY_OVERLAPS = Object.freeze([]);
const EMPTY_BULK_SETTINGS = Object.freeze({
  enabled: 'keep',
  autoSync: 'keep',
  orphanCleanup: 'keep',
});

const NUMBERING_MODE_OPTIONS = [
  { value: 'fixed', label: 'Fixed' },
  { value: 'provider', label: 'Provider' },
  { value: 'next_available', label: 'Next Avail' },
];

const LiveGroupCard = memo(function LiveGroupCard({
  group,
  refreshLabel,
  hasChannelConflict,
  overlaps,
  onToggleAutoSync,
  onToggleEnabled,
  onConfigure,
  onPreview,
  selected,
  onSelect,
  previewAvailable,
  previewUnavailableHint,
}) {
  const numberingMode =
    group.custom_properties?.channel_numbering_mode || 'fixed';
  const showAutoSyncControls = group.auto_channel_sync && group.enabled;
  const rangeStart =
    numberingMode === 'provider'
      ? (group.custom_properties?.channel_numbering_fallback ?? 1)
      : (group.auto_sync_channel_start ?? 1);
  const rangeWarning = [
    ...(hasChannelConflict
      ? [
          'Range conflicts with configured channels. View the Channels page to inspect.',
        ]
      : []),
    ...overlaps.map(
      (overlap) =>
        `Overlaps with ${overlap.name} (${overlap.start}-${overlap.end})`
    ),
  ].join('\n');
  return (
    <TableTr
      data-testid="group-card"
      data-selected={selected || undefined}
      bg={selected ? 'var(--mantine-primary-color-light)' : undefined}
    >
      <TableTd>
        <Checkbox
          aria-label={`Select ${group.name}`}
          checked={selected}
          onChange={(event) =>
            onSelect(group.channel_group, event.currentTarget.checked)
          }
        />
      </TableTd>
      <TableTd>
        <Tooltip
          label={`Not seen in the last ${refreshLabel} refresh; removed after the retention period.`}
          disabled={!group.is_stale}
          multiline
          w={220}
        >
          <Text size="sm" c={group.is_stale ? 'orange' : undefined} truncate>
            {group.name}
          </Text>
        </Tooltip>
      </TableTd>
      <TableTd ta="center">
        <CategoryStatusBadge
          category={group}
          onToggle={() => onToggleEnabled(group.channel_group)}
        />
      </TableTd>
      <TableTd>
        <Flex justify="center">
          <Checkbox
            aria-label={`Auto Channel Sync for ${group.name}`}
            checked={!!(group.auto_channel_sync && group.enabled)}
            disabled={!group.enabled}
            onChange={() => onToggleAutoSync(group.channel_group)}
            size="xs"
          />
        </Flex>
      </TableTd>
      <TableTd>
        <Text size="xs" c={showAutoSyncControls ? undefined : 'dimmed'}>
          {NUMBERING_MODE_OPTIONS.find(
            (option) => option.value === numberingMode
          )?.label || 'Fixed'}
        </Text>
      </TableTd>
      <TableTd>
        <Group gap={4} wrap="nowrap">
          <Text size="xs" c={showAutoSyncControls ? undefined : 'dimmed'}>
            {!showAutoSyncControls
              ? 'Auto sync disabled'
              : numberingMode === 'next_available'
                ? 'Next available'
                : `${rangeStart}–${group.auto_sync_channel_end ?? '∞'}`}
          </Text>
          {showAutoSyncControls && rangeWarning && (
            <Tooltip
              label={rangeWarning}
              multiline
              w={280}
              styles={{ tooltip: { whiteSpace: 'pre-line' } }}
            >
              <AlertTriangle
                size={14}
                color="var(--mantine-color-yellow-6)"
                aria-label="Range conflict warning"
              />
            </Tooltip>
          )}
        </Group>
      </TableTd>
      <TableTd>
        <Flex gap={4} align="center" justify="center">
          <Tooltip label="Configure category">
            <ActionIcon
              aria-label="Configure category"
              variant="subtle"
              disabled={!group.enabled}
              onClick={() => onConfigure(group)}
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
                aria-label="Preview category"
                variant="subtle"
                onClick={() => onPreview(group)}
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

const LiveGroupFilter = ({
  playlist,
  isInitialSetup = false,
  groupStates,
  setGroupStates,
  onOpenRules,
  onOverlayChange,
  paginationContainer = null,
  paginationVisible = true,
  previewAvailableIds,
  previewUnavailableHint,
  ruleCount = 0,
  selectionChanged = false,
  onSaveSelection,
}) => {
  const streamLabel = getM3UStreamLabel(playlist.account_type);
  const refreshLabel = playlist.account_type === 'STD' ? 'stream' : 'Live';
  const channelGroups = useChannelsStore((s) => s.channelGroups);
  const streamProfiles = useStreamProfilesStore((s) => s.profiles);
  const fetchStreamProfiles = useStreamProfilesStore((s) => s.fetchProfiles);
  const [groupFilter, setGroupFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState(DEFAULT_CATEGORY_VISIBILITY);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [previewGroup, setPreviewGroup] = useState(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [selectedGroupIds, setSelectedGroupIds] = useState(new Set());
  const [bulkEditorOpen, setBulkEditorOpen] = useState(false);
  const [bulkSettings, setBulkSettings] = useState(EMPTY_BULK_SETTINGS);
  useEffect(() => {
    const ids = new Set(groupStates.map((group) => group.channel_group));
    setSelectedGroupIds((current) => {
      const next = new Set([...current].filter((id) => ids.has(id)));
      return next.size === current.size ? current : next;
    });
  }, [groupStates]);
  useEffect(() => {
    setSelectedGroupIds(new Set());
    setBulkEditorOpen(false);
  }, [playlist.id]);
  useEffect(() => {
    setPage(1);
  }, [groupFilter, statusFilter]);
  const [epgSources, setEpgSources] = useState([]);

  const {
    logos: channelLogos,
    ensureLogosLoaded,
    isLoading: logosLoading,
  } = useChannelLogoSelection();
  const [logoModalOpen, setLogoModalOpen] = useState(false);
  const [currentEditingGroupId, setCurrentEditingGroupId] = useState(null);
  const [configuringGroupId, setConfiguringGroupId] = useState(null);
  useEffect(() => {
    onOverlayChange?.(
      filtersOpen ||
        bulkEditorOpen ||
        !!configuringGroupId ||
        logoModalOpen ||
        !!previewGroup
    );
    return () => onOverlayChange?.(false);
  }, [
    filtersOpen,
    bulkEditorOpen,
    configuringGroupId,
    logoModalOpen,
    previewGroup,
    onOverlayChange,
  ]);
  // Snapshot of the configuring group's state taken when the Configure
  // modal opens. Discard restores it; Apply keeps the current draft.
  const configureSnapshotRef = useRef(null);
  // Merged per-group conflict state: { id: { hasChannelConflict: bool } }
  // sourced from the debounced /numbers-in-range/ scan plus an in-memory
  // overlap check against other groups' ranges in modal state.
  const [groupConflicts, setGroupConflicts] = useState({});
  const conflictTimersRef = useRef({});
  // Aborts the previous /numbers-in-range/ call so a slow response cannot
  // overwrite newer state.
  const conflictAbortRef = useRef({});
  // Conflict state split by source ('occupant' DB scan vs 'form' overlap).
  // The render-time `hasChannelConflict` is `occupant || form`; tracking
  // both lets the sweep refresh form-overlap synchronously while only
  // firing the DB scan when a group's own range changes.
  const conflictSourcesRef = useRef({});
  // Signature of each group's conflict-relevant fields from the last sweep.
  // The sweep skips the (debounced) DB scan when the signature is
  // unchanged, so unrelated state changes do not fan out HTTP requests.
  const lastConflictSigRef = useRef({});
  // Per-group regex preview state mirroring the /streams/regex-preview/
  // payload (find/filter results, counts, scan_limit_hit). Cached by
  // pattern args; cache lifetime = modal lifetime.
  const [regexPreviewState, setRegexPreviewState] = useState({});
  const regexPreviewTimersRef = useRef({});
  const regexPreviewCacheRef = useRef({});
  // Aborts the previous regex preview request so out-of-order responses
  // cannot stomp newer state.
  const regexPreviewAbortRef = useRef({});
  const {
    summaries: categoryContents,
    keyFor: contentKeyFor,
    ensure: ensureCategoryContent,
    remember: rememberCategoryContent,
  } = useLiveCategoryContent(playlist);
  const configuringGroup = configuringGroupId
    ? groupStates.find((g) => g.channel_group === configuringGroupId)
    : null;
  const applyGroupChange = useCallback(
    (nextGroupState) => {
      setGroupStates((prev) =>
        prev.map((state) =>
          state.channel_group === nextGroupState.channel_group
            ? nextGroupState
            : state
        )
      );
    },
    [setGroupStates]
  );

  // Update one source ('occupant' or 'form') of a group's conflict
  // tracking and re-merge into the public `groupConflicts` state.
  const setConflictSource = (groupId, source, value) => {
    const prev = conflictSourcesRef.current[groupId] || {
      occupant: false,
      form: false,
    };
    if (prev[source] === value) return;
    const next = { ...prev, [source]: value };
    conflictSourcesRef.current[groupId] = next;
    setGroupConflicts((prevState) => ({
      ...prevState,
      [groupId]: { hasChannelConflict: next.occupant || next.form },
    }));
  };

  // Debounced /numbers-in-range/ scan; sets `occupant` conflict source
  // when any returned channel is not this group's own auto-sync output.
  //
  // Design: three refs (timer, abort, signature) cooperate to keep the
  // request volume tied to user intent rather than render frequency.
  // The timer debounces fast keystrokes; the abort controller cancels
  // any in-flight request so a slow response cannot stomp newer state;
  // and the parent sweep effect skips this scheduler entirely when a
  // group's start/end signature has not changed since the last sweep.
  // The conflict result is split into 'occupant' (DB scan) and 'form'
  // (in-memory range overlap with sibling groups) sources so the sweep
  // can refresh form-overlap synchronously without firing HTTP for
  // groups that did not change.
  const scheduleConflictScan = (
    groupId,
    rawStart,
    rawEnd,
    expectedGroupId = groupId
  ) => {
    if (conflictTimersRef.current[groupId]) {
      clearTimeout(conflictTimersRef.current[groupId]);
    }
    if (conflictAbortRef.current[groupId]) {
      conflictAbortRef.current[groupId].abort();
    }
    const start = Number(rawStart);
    const end =
      rawEnd === null || rawEnd === undefined || rawEnd === ''
        ? start
        : Number(rawEnd);
    if (!Number.isFinite(start) || start <= 0) {
      setConflictSource(groupId, 'occupant', false);
      return;
    }
    conflictTimersRef.current[groupId] = setTimeout(async () => {
      const controller = new AbortController();
      conflictAbortRef.current[groupId] = controller;
      try {
        const result = await getChannelsInRange(start, end, controller);
        const occupants = Array.isArray(result?.occupants)
          ? result.occupants
          : [];
        const unexpected = occupants.filter(
          (o) => !isExpectedOccupantForGroup(o, expectedGroupId, playlist)
        );
        setConflictSource(groupId, 'occupant', unexpected.length > 0);
      } catch (e) {
        // Aborted by a newer keystroke; the newer call will replace state.
        if (e?.name === 'AbortError') return;
        throw e;
      }
    }, 300);
  };

  useEffect(() => {
    // Clear pending timers and abort in-flight conflict-scan requests on
    // unmount so a late response cannot setState on an unmounted component.
    return () => {
      abortTimers(conflictTimersRef, conflictAbortRef);
    };
  }, []);

  // Sweep effect: recomputes form-overlap in-memory for every group
  // (cheap). The HTTP-bound DB scan only runs for groups whose own
  // range fields changed since the last sweep.
  useEffect(() => {
    const ranges = new Map();
    for (const g of groupStates) {
      const r = rangeFor(g);
      if (r) ranges.set(g.channel_group, r);
    }

    for (const g of groupStates) {
      const range = ranges.get(g.channel_group);
      if (!range) {
        // Group out of scope (disabled, mode flipped, or start blanked).
        // Abort any in-flight scan so its late response cannot stamp a
        // stale 'occupant' value onto the cleared state.
        if (conflictTimersRef.current[g.channel_group]) {
          clearTimeout(conflictTimersRef.current[g.channel_group]);
          delete conflictTimersRef.current[g.channel_group];
        }
        if (conflictAbortRef.current[g.channel_group]) {
          conflictAbortRef.current[g.channel_group].abort();
          delete conflictAbortRef.current[g.channel_group];
        }
        setConflictSource(g.channel_group, 'form', false);
        setConflictSource(g.channel_group, 'occupant', false);
        delete lastConflictSigRef.current[g.channel_group];
        continue;
      }

      let hasFormConflict = false;
      for (const [otherId, otherRange] of ranges) {
        if (otherId === g.channel_group) continue;
        if (range.start <= otherRange.end && otherRange.start <= range.end) {
          hasFormConflict = true;
          break;
        }
      }
      setConflictSource(g.channel_group, 'form', hasFormConflict);

      const sig = `${range.start}|${range.end}`;
      if (lastConflictSigRef.current[g.channel_group] !== sig) {
        lastConflictSigRef.current[g.channel_group] = sig;
        scheduleConflictScan(
          g.channel_group,
          range.startRaw,
          g.auto_sync_channel_end,
          effectiveSyncGroupId(g)
        );
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groupStates]);

  // Debounced regex preview fetcher. Each call computes a cache key from
  // the group + pattern args; identical arg sets reuse the cached result
  // instantly. Distinct keys schedule a backend round-trip 500ms after
  // the last change so the user can finish typing before the request
  // fires. Backend caps in-memory iteration at 5000 streams per call so
  // groups with tens of thousands of streams stay performant. Three
  // independent patterns are supported per call: find/replace, include
  // filter, exclude filter.
  const scheduleRegexPreview = (group, opts) => {
    const groupId = group.channel_group;
    const find = opts.find || '';
    const replace = opts.replace ?? '';
    const match = opts.match || '';
    const exclude = opts.exclude || '';
    const emptyState = {
      findResult: null,
      filterResult: null,
      excludeResult: null,
      loading: false,
    };
    // Clear any pending request whenever the inputs settle on a state that
    // does not require a backend round-trip (all-empty or cache hit).
    // Otherwise a 500ms-old timer would still fire and stomp the new state.
    const cancelPending = () => {
      if (regexPreviewTimersRef.current[groupId]) {
        clearTimeout(regexPreviewTimersRef.current[groupId]);
        regexPreviewTimersRef.current[groupId] = null;
      }
      if (regexPreviewAbortRef.current[groupId]) {
        regexPreviewAbortRef.current[groupId].abort();
        regexPreviewAbortRef.current[groupId] = null;
      }
    };
    if (!find && !match && !exclude) {
      cancelPending();
      setRegexPreviewState((prev) => ({ ...prev, [groupId]: emptyState }));
      return;
    }
    // Account ID in the cache key so previews stay correct when the
    // user switches between accounts that share a group name.
    const accountId = playlist?.id ?? '';
    const cacheKey = `${accountId}|${groupId}|${find}|${replace}|${match}|${exclude}`;
    const cached = regexPreviewCacheRef.current[cacheKey];
    if (cached) {
      cancelPending();
      setRegexPreviewState((prev) => ({
        ...prev,
        [groupId]: { ...cached, loading: false },
      }));
      return;
    }
    if (regexPreviewTimersRef.current[groupId]) {
      clearTimeout(regexPreviewTimersRef.current[groupId]);
    }
    if (regexPreviewAbortRef.current[groupId]) {
      regexPreviewAbortRef.current[groupId].abort();
    }
    setRegexPreviewState((prev) => ({
      ...prev,
      [groupId]: {
        ...(prev[groupId] || {
          findResult: null,
          filterResult: null,
          excludeResult: null,
        }),
        loading: true,
      },
    }));
    regexPreviewTimersRef.current[groupId] = setTimeout(async () => {
      const controller = new AbortController();
      regexPreviewAbortRef.current[groupId] = controller;
      let response;
      try {
        response = await getStreamsRegexPreview(
          group,
          find,
          replace,
          match,
          exclude,
          controller,
          playlist
        );
        if (response?.can_load_provider && !controller.signal.aborted) {
          setRegexPreviewState((prev) => ({
            ...prev,
            [groupId]: { ...prev[groupId], loadingContent: true },
          }));
          await ensureCategoryContent(groupId, true);
          if (controller.signal.aborted) return;
          response = await getStreamsRegexPreview(
            group,
            find,
            replace,
            match,
            exclude,
            controller,
            playlist
          );
        }
        if (!response) throw new Error('Preview unavailable');
      } catch (e) {
        if (e?.name === 'AbortError') return;
        if (!controller.signal.aborted)
          setRegexPreviewState((prev) => ({
            ...prev,
            [groupId]: {
              ...emptyState,
              loadError: `Could not load category content. Retry or run a ${refreshLabel} refresh.`,
            },
          }));
        return;
      }
      if (controller.signal.aborted) return;
      const buildResult = (key, errorKey) => ({
        matches: response[`${key}_matches`] || [],
        match_count: response[`${key}_match_count`] || 0,
        total_in_group: response.total_in_group || 0,
        total_scanned: response.total_scanned || 0,
        scan_limit_hit: !!response.scan_limit_hit,
        error: response[errorKey] || null,
        content_source: response.content_source,
      });
      const next = {
        findResult: find ? buildResult('find', 'find_error') : null,
        filterResult: match ? buildResult('filter', 'match_error') : null,
        excludeResult: exclude ? buildResult('exclude', 'exclude_error') : null,
        loading: false,
      };
      regexPreviewCacheRef.current[cacheKey] = next;
      setRegexPreviewState((prev) => ({
        ...prev,
        [groupId]: next,
      }));
    }, 500);
  };

  useEffect(() => {
    return () => {
      abortTimers(regexPreviewTimersRef, regexPreviewAbortRef);
    };
  }, []);

  // When the gear modal opens (or its open group changes), trigger a
  // preview fetch using whatever patterns are already saved on that
  // group. Subsequent edits to the patterns trigger their own scheduled
  // fetches via the field handlers.
  useEffect(() => {
    if (!configuringGroup) return;
    // This only reads local content for Standard accounts. XC can load the
    // missing category into the same private cache used by Preview/import.
    ensureCategoryContent(configuringGroup.channel_group).catch(() => {});
    const cp = configuringGroup.custom_properties || {};
    scheduleRegexPreview(
      configuringGroup,
      getRegexOptions(
        cp.name_regex_pattern || '',
        cp.name_replace_pattern ?? '',
        cp.name_match_regex || '',
        cp.name_match_exclude_regex || ''
      )
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [configuringGroup?.channel_group, ensureCategoryContent]);

  // Ensure logos are loaded when component mounts
  useEffect(() => {
    ensureLogosLoaded();
  }, [ensureLogosLoaded]);

  // Fetch stream profiles when component mounts
  useEffect(() => {
    if (streamProfiles.length === 0) {
      fetchStreamProfiles();
    }
  }, [streamProfiles.length, fetchStreamProfiles]);

  // Fetch EPG sources when component mounts
  useEffect(() => {
    const fetchEPGSources = async () => {
      try {
        const sources = await getEPGs();
        setEpgSources(sources || []);
      } catch (error) {
        console.error('Failed to fetch EPG sources:', error);
      }
    };
    fetchEPGSources();
  }, []);

  // Build group state once per playlist, not on every prop reference change.
  // The parent re-renders this component on WebSocket sync-progress updates,
  // which would otherwise blow away in-progress edits while the modal is open.
  const lastInitKey = useRef(null);
  useEffect(() => {
    if (Object.keys(channelGroups).length === 0) {
      return;
    }
    const groupIds = (playlist.channel_groups || [])
      .map((g) => g.channel_group)
      .sort()
      .join(',');
    const initKey = `${playlist.id}:${groupIds}`;
    if (lastInitKey.current === initKey) {
      return;
    }
    const sameAccount = lastInitKey.current?.startsWith(`${playlist.id}:`);
    lastInitKey.current = initKey;

    setGroupStates((previous) =>
      (playlist.channel_groups || [])
        .filter((group) => channelGroups[group.channel_group])
        .map((group) => {
          const existing = sameAccount
            ? previous.find((row) => row.channel_group === group.channel_group)
            : null;
          if (existing)
            return {
              ...existing,
              name: channelGroups[group.channel_group].name,
            };
          let customProps = {};
          if (group.custom_properties) {
            try {
              customProps =
                typeof group.custom_properties === 'string'
                  ? JSON.parse(group.custom_properties)
                  : group.custom_properties;
            } catch {
              customProps = {};
            }
          }
          return {
            ...group,
            name: channelGroups[group.channel_group].name,
            auto_channel_sync: group.auto_channel_sync || false,
            auto_sync_channel_start: group.auto_sync_channel_start || 1.0,
            auto_sync_channel_end: group.auto_sync_channel_end ?? null,
            custom_properties: customProps,
            original_enabled: group.enabled,
          };
        })
    );
  }, [playlist, channelGroups, setGroupStates]);

  const toggleEnabled = useCallback(
    (id) => {
      setGroupStates((current) =>
        current.map((group) =>
          group.channel_group === id && !group.ignored
            ? { ...group, enabled: !group.enabled }
            : group
        )
      );
    },
    [setGroupStates]
  );

  const toggleAutoSync = useCallback(
    (id) => {
      setGroupStates((prev) =>
        prev.map((state) => {
          if (state.channel_group != id) return state;
          const turningOn = !state.auto_channel_sync;
          const next = { ...state, auto_channel_sync: turningOn };
          if (!turningOn) return next;

          // Pick a sensible start when enabling auto-sync: max of other
          // groups' end (or start) plus 1, so multiple groups don't all
          // default to 1. Skipped if a non-default start is already set.
          const currentStart = state.auto_sync_channel_start;
          if (currentStart && currentStart > 1) return next;

          next.auto_sync_channel_start = computeAutoSyncStart(prev, id);
          return next;
        })
      );
    },
    [setGroupStates]
  );

  const updateNumberingMode = useCallback(
    (id, value) => {
      setGroupStates((prev) =>
        prev.map((state) => {
          if (state.channel_group !== id) return state;
          return {
            ...state,
            custom_properties: {
              ...state.custom_properties,
              channel_numbering_mode: value || 'fixed',
            },
          };
        })
      );
    },
    [setGroupStates]
  );

  const openConfigure = useCallback((group) => {
    // Snapshot at open time so Discard can restore pre-edit state.
    // custom_properties needs a one-level clone since the rest of group
    // state is flat.
    configureSnapshotRef.current = {
      ...group,
      custom_properties: {
        ...(group.custom_properties || {}),
      },
    };
    setConfiguringGroupId(group.channel_group);
  }, []);

  const retryCategoryContent = () => {
    if (!configuringGroup) return;
    ensureCategoryContent(configuringGroup.channel_group, true)
      .then(() => {
        const cp = configuringGroup.custom_properties || {};
        scheduleRegexPreview(
          configuringGroup,
          getRegexOptions(
            cp.name_regex_pattern || '',
            cp.name_replace_pattern || '',
            cp.name_match_regex || '',
            cp.name_match_exclude_regex || ''
          )
        );
      })
      .catch(() => {});
  };

  // Handle logo selection from LogoForm
  const handleLogoSuccess = ({ logo }) => {
    if (logo && logo.id && currentEditingGroupId !== null) {
      setGroupStates((prev) =>
        prev.map((state) => {
          if (state.channel_group === currentEditingGroupId) {
            return {
              ...state,
              custom_properties: {
                ...state.custom_properties,
                custom_logo_id: logo.id,
              },
            };
          }
          return state;
        })
      );
      ensureLogosLoaded();
    }
    setLogoModalOpen(false);
    setCurrentEditingGroupId(null);
  };

  const toggleSelectedGroup = useCallback((id, checked) => {
    setSelectedGroupIds((current) => {
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

  const applyBulkSettings = () => {
    setGroupStates((current) => {
      const nextGroups = [...current];
      current.forEach((group, index) => {
        if (!selectedGroupIds.has(group.channel_group)) return;
        const next = {
          ...group,
          custom_properties: { ...group.custom_properties },
        };
        if (bulkSettings.enabled !== 'keep')
          Object.assign(next, categoryStatusPatch(bulkSettings.enabled));
        if (bulkSettings.autoSync !== 'keep') {
          next.auto_channel_sync = bulkSettings.autoSync === 'enabled';
          if (
            next.auto_channel_sync &&
            !group.auto_channel_sync &&
            (!group.auto_sync_channel_start ||
              group.auto_sync_channel_start <= 1)
          ) {
            next.auto_sync_channel_start = computeAutoSyncStart(
              nextGroups,
              group.channel_group
            );
          }
        }
        if (bulkSettings.orphanCleanup !== 'keep')
          next.custom_properties.orphan_channel_cleanup =
            bulkSettings.orphanCleanup;
        nextGroups[index] = next;
      });
      return nextGroups;
    });
    closeBulkEditor();
  };

  const overlapsByGroup = useMemo(() => {
    const map = new Map();
    for (const group of groupStates) {
      if (!group.enabled || !group.auto_channel_sync) continue;
      const overlaps = computeRangeOverlapsFor(group, groupStates);
      if (overlaps.length > 0) {
        map.set(group.channel_group, overlaps);
      }
    }
    return map;
  }, [groupStates]);

  const visibleGroups = groupStates
    .filter(
      (group) =>
        isGroupVisible(group, groupFilter, 'all') &&
        matchesCategoryVisibility(group, statusFilter)
    )
    .sort((a, b) => a.name.localeCompare(b.name));
  useEffect(() => {
    setPage((current) =>
      Math.min(current, Math.max(1, Math.ceil(visibleGroups.length / pageSize)))
    );
  }, [visibleGroups.length, pageSize]);
  const selectedVisibleCount = visibleGroups.filter((group) =>
    selectedGroupIds.has(group.channel_group)
  ).length;
  const hasEnabledLiveCategories = groupStates.some((group) => group.enabled);
  const setupIncomplete = isInitialSetup || !!playlist?.setup_step;
  const filtersAvailable = hasEnabledLiveCategories;
  const filtersUnavailableHint = `Select at least one ${streamLabel} category before configuring stream filters.`;
  const toggleVisibleSelection = (checked) => {
    setSelectedGroupIds((current) => {
      const next = new Set(current);
      visibleGroups.forEach((group) =>
        checked
          ? next.add(group.channel_group)
          : next.delete(group.channel_group)
      );
      return next;
    });
  };

  const pagination = (
    <ListPagination
      page={page}
      pageSize={pageSize}
      total={visibleGroups.length}
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
          size="xs"
          variant={ruleCount ? 'light' : 'default'}
          onClick={onOpenRules}
        >
          Import rules{ruleCount ? ` (${ruleCount})` : ''}
        </Button>
        <StreamFilterControl
          playlist={playlist}
          available={filtersAvailable}
          unavailableHint={filtersUnavailableHint}
          selectionChanged={selectionChanged}
          onSaveSelection={onSaveSelection}
          onOverlayChange={setFiltersOpen}
          previewOnly={setupIncomplete}
          selectedGroupIds={groupStates
            .filter((group) => group.enabled)
            .map((group) => group.channel_group)}
        />
        <Text size="xs" c="dimmed">
          New unmatched categories are imported disabled.
        </Text>
      </Flex>

      <Flex gap="sm" align="center" wrap="wrap">
        <TextInput
          placeholder="Filter categories..."
          value={groupFilter}
          onChange={(event) => setGroupFilter(event.currentTarget.value)}
          className={editorClasses.categorySearch}
          size="xs"
        />
        <CategoryVisibilityFilter
          value={statusFilter}
          onChange={setStatusFilter}
          categories={groupStates}
        />
        <Group gap="xs" ml="auto">
          {selectedGroupIds.size > 0 && (
            <Anchor
              component="button"
              type="button"
              size="xs"
              onClick={() => setSelectedGroupIds(new Set())}
            >
              Clear
            </Anchor>
          )}
          <Button
            variant="default"
            size="xs"
            disabled={!selectedGroupIds.size}
            onClick={() => {
              setBulkSettings(EMPTY_BULK_SETTINGS);
              setBulkEditorOpen(true);
            }}
          >
            Edit settings ({selectedGroupIds.size})
          </Button>
        </Group>
      </Flex>

      <ScrollArea className={editorClasses.categoryTableFrame}>
        <Table striped stickyHeader className={editorClasses.categoryTable}>
          <TableThead>
            <TableTr>
              <TableTh w={44}>
                <Checkbox
                  aria-label="Select visible categories"
                  checked={
                    visibleGroups.length > 0 &&
                    selectedVisibleCount === visibleGroups.length
                  }
                  indeterminate={
                    selectedVisibleCount > 0 &&
                    selectedVisibleCount < visibleGroups.length
                  }
                  disabled={!visibleGroups.length}
                  onChange={(event) =>
                    toggleVisibleSelection(event.currentTarget.checked)
                  }
                />
              </TableTh>
              <TableTh>Category</TableTh>
              <TableTh w={100} ta="center">
                Status
              </TableTh>
              <TableTh w="12%">
                <Group gap={4} wrap="nowrap" justify="center">
                  Auto sync
                  <Tooltip
                    label="Auto sync creates and maintains channels for imported streams in each enabled category. Number ranges and advanced options can be configured per category."
                    multiline
                    maw={360}
                    withArrow
                    events={{ hover: true, focus: true, touch: true }}
                  >
                    <span
                      aria-label="Auto channel sync help"
                      tabIndex={0}
                      style={{ display: 'inline-flex', cursor: 'help' }}
                    >
                      <Info size={14} aria-hidden="true" />
                    </span>
                  </Tooltip>
                </Group>
              </TableTh>
              <TableTh w="12%">Numbering</TableTh>
              <TableTh w="18%">Channel range</TableTh>
              <TableTh w={76} ta="center">
                Actions
              </TableTh>
            </TableTr>
          </TableThead>
          <TableTbody>
            {!visibleGroups.length && (
              <TableTr>
                <TableTd colSpan={8} ta="center" py="xl">
                  <Text size="sm" c="dimmed">
                    No categories match the current filters.
                  </Text>
                  <Button
                    variant="subtle"
                    size="xs"
                    onClick={() => {
                      setGroupFilter('');
                      setStatusFilter(DEFAULT_CATEGORY_VISIBILITY);
                    }}
                  >
                    Reset filters
                  </Button>
                </TableTd>
              </TableTr>
            )}
            {visibleGroups
              .slice((page - 1) * pageSize, page * pageSize)
              .map((group) => (
                <LiveGroupCard
                  key={group.channel_group}
                  group={group}
                  refreshLabel={refreshLabel}
                  hasChannelConflict={
                    !!groupConflicts[group.channel_group]?.hasChannelConflict
                  }
                  overlaps={
                    overlapsByGroup.get(group.channel_group) || EMPTY_OVERLAPS
                  }
                  onToggleAutoSync={toggleAutoSync}
                  onToggleEnabled={toggleEnabled}
                  onConfigure={openConfigure}
                  onPreview={setPreviewGroup}
                  selected={selectedGroupIds.has(group.channel_group)}
                  onSelect={toggleSelectedGroup}
                  previewAvailable={
                    previewAvailableIds === undefined ||
                    !!previewAvailableIds?.has(group.channel_group)
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
        scope="live"
        group={previewGroup}
        onClose={() => setPreviewGroup(null)}
        onContentLoaded={rememberCategoryContent}
      />

      <StackedModal
        stackId="m3u-live-category-bulk-settings"
        opened={bulkEditorOpen}
        onClose={closeBulkEditor}
        title={`Edit settings for ${selectedGroupIds.size} ${selectedGroupIds.size === 1 ? 'category' : 'categories'}`}
      >
        <Stack gap="sm">
          <Paper withBorder p="sm">
            <Stack gap="xs" role="group" aria-label="Category status settings">
              <Text fw={600}>General</Text>
              <Select
                label="Status"
                value={bulkSettings.enabled}
                onChange={(value) =>
                  setBulkSettings((current) => ({
                    ...current,
                    enabled: value || 'keep',
                  }))
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
          <Paper withBorder p="sm">
            <Stack gap="xs" role="group" aria-label="Channel sync settings">
              <Text fw={600}>Channel sync</Text>
              <Select
                label="Auto sync"
                value={bulkSettings.autoSync}
                onChange={(value) =>
                  setBulkSettings((current) => ({
                    ...current,
                    autoSync: value || 'keep',
                  }))
                }
                data={[
                  { value: 'keep', label: 'Keep unchanged' },
                  { value: 'enabled', label: 'Enabled' },
                  { value: 'disabled', label: 'Disabled' },
                ]}
              />
              <Select
                label="Auto-sync orphan cleanup"
                value={bulkSettings.orphanCleanup}
                onChange={(value) =>
                  setBulkSettings((current) => ({
                    ...current,
                    orphanCleanup: value || 'keep',
                  }))
                }
                data={[
                  { value: 'keep', label: 'Keep unchanged' },
                  { value: 'always', label: 'Always remove' },
                  {
                    value: 'preserve_customized',
                    label: 'Preserve customized',
                  },
                  { value: 'never', label: 'Never remove' },
                ]}
              />
            </Stack>
          </Paper>
          <Group justify="flex-end">
            <Button variant="default" onClick={closeBulkEditor}>
              Cancel
            </Button>
            <Button
              onClick={applyBulkSettings}
              disabled={!selectedGroupIds.size}
            >
              Apply to selected
            </Button>
          </Group>
        </Stack>
      </StackedModal>

      {/* Settings stay in the per-group dialog; rows show compact summaries. */}
      <GroupConfigureModal
        opened={!!configuringGroup}
        onDone={() => {
          configureSnapshotRef.current = null;
          setConfiguringGroupId(null);
        }}
        onCancel={() => {
          // Revert this group's in-memory edits to the open-time
          // snapshot. Other groups' unsaved edits in groupStates are
          // untouched.
          if (configureSnapshotRef.current) {
            applyGroupChange(configureSnapshotRef.current);
          }
          configureSnapshotRef.current = null;
          setConfiguringGroupId(null);
        }}
        group={configuringGroup}
        dirty={
          !!configuringGroup &&
          JSON.stringify({
            ...configuringGroup,
            custom_properties: configuringGroup.custom_properties || {},
          }) !== JSON.stringify(configureSnapshotRef.current)
        }
        content={
          configuringGroup
            ? categoryContents[contentKeyFor(configuringGroup.channel_group)]
            : null
        }
        onRetryContent={retryCategoryContent}
      >
        {configuringGroup && (
          <Stack>
            <Paper withBorder p="sm">
              <Stack gap="sm" role="group" aria-label="Channel sync settings">
                <Text fw={600}>Channel sync</Text>
                <Checkbox
                  label="Auto sync"
                  checked={!!configuringGroup.auto_channel_sync}
                  onChange={() =>
                    toggleAutoSync(configuringGroup.channel_group)
                  }
                />
                <Select
                  label="Numbering mode"
                  value={
                    configuringGroup.custom_properties
                      ?.channel_numbering_mode || 'fixed'
                  }
                  data={NUMBERING_MODE_OPTIONS}
                  disabled={!configuringGroup.auto_channel_sync}
                  allowDeselect={false}
                  onChange={(value) =>
                    updateNumberingMode(configuringGroup.channel_group, value)
                  }
                />
                {configuringGroup.auto_channel_sync && (
                  <AutoSyncBasic
                    group={configuringGroup}
                    overlaps={
                      overlapsByGroup.get(configuringGroup.channel_group) ||
                      EMPTY_OVERLAPS
                    }
                    groupConflicts={groupConflicts}
                    onApplyGroupChange={applyGroupChange}
                  />
                )}
                <Select
                  label="Auto-sync orphan cleanup"
                  description="What to do with this group's auto-created channels when their source stream disappears. Manual and hidden channels are preserved."
                  value={
                    configuringGroup.custom_properties
                      ?.orphan_channel_cleanup || 'always'
                  }
                  disabled={!configuringGroup.auto_channel_sync}
                  allowDeselect={false}
                  data={[
                    { value: 'always', label: 'Always remove' },
                    {
                      value: 'preserve_customized',
                      label: 'Preserve customized',
                    },
                    { value: 'never', label: 'Never remove' },
                  ]}
                  onChange={(value) =>
                    applyGroupChange({
                      ...configuringGroup,
                      custom_properties: {
                        ...configuringGroup.custom_properties,
                        orphan_channel_cleanup: value || 'always',
                      },
                    })
                  }
                />
              </Stack>
            </Paper>
            {configuringGroup.auto_channel_sync && (
              <ErrorBoundary inline>
                <Suspense fallback={<Loader />}>
                  <AutoSyncAdvanced
                    group={configuringGroup}
                    epgSources={epgSources}
                    channelGroups={channelGroups}
                    streamProfiles={streamProfiles}
                    regexPreviewState={regexPreviewState}
                    contentState={
                      categoryContents[
                        contentKeyFor(configuringGroup.channel_group)
                      ]
                    }
                    onApplyGroupChange={applyGroupChange}
                    onScheduleRegexPreview={scheduleRegexPreview}
                    onRetryRegexPreview={retryCategoryContent}
                    onOpenLogoUpload={(groupId) => {
                      setCurrentEditingGroupId(groupId);
                      setLogoModalOpen(true);
                    }}
                    channelLogos={channelLogos}
                    playlist={playlist}
                    logosLoading={logosLoading}
                    ensureLogosLoaded={ensureLogosLoaded}
                  />
                </Suspense>
              </ErrorBoundary>
            )}
          </Stack>
        )}
      </GroupConfigureModal>

      {/* Logo Upload Modal */}
      {logoModalOpen && (
        <ErrorBoundary inline>
          <Suspense fallback={<Loader />}>
            <LogoForm
              isOpen={logoModalOpen}
              onClose={() => {
                setLogoModalOpen(false);
                setCurrentEditingGroupId(null);
              }}
              onSuccess={handleLogoSuccess}
            />
          </Suspense>
        </ErrorBoundary>
      )}
    </Stack>
  );
};

export default LiveGroupFilter;
