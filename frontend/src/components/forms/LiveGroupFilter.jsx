import React, { Suspense, useEffect, useRef, useState } from 'react';
import {
  ActionIcon,
  Button,
  Checkbox,
  Divider,
  Flex,
  Group,
  Loader,
  Modal,
  ScrollArea,
  Select,
  SegmentedControl,
  Stack,
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
import { Eye, Info, Settings as Cog } from 'lucide-react';
import GroupConfigureModal from './GroupConfigureModal';
import useChannelsStore from '../../store/channels';
import useStreamProfilesStore from '../../store/streamProfiles';
import { useChannelLogoSelection } from '../../hooks/useSmartLogos';
import AutoSyncBasic from './AutoSyncBasic.jsx';
import ErrorBoundary from '../ErrorBoundary.jsx';
import M3UGroupRules from './M3UGroupRules.jsx';
import M3UDeveloperCatalog from './M3UDeveloperCatalog.jsx';
import ListPagination from '../ListPagination.jsx';
const AutoSyncAdvanced = React.lazy(() => import('./AutoSyncAdvanced.jsx'));
const LogoForm = React.lazy(() => import('./Logo.jsx'));
const M3UFilters = React.lazy(() => import('./M3UFilters.jsx'));
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

const EMPTY_BULK_SETTINGS = {
  enabled: 'keep',
  autoSync: 'keep',
  numberingMode: 'keep',
  orphanCleanup: 'keep',
};

const LiveGroupFilter = ({ playlist, groupStates, setGroupStates }) => {
  const channelGroups = useChannelsStore((s) => s.channelGroups);
  const streamProfiles = useStreamProfilesStore((s) => s.profiles);
  const fetchStreamProfiles = useStreamProfilesStore((s) => s.fetchProfiles);
  const [groupFilter, setGroupFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [selectedGroupIds, setSelectedGroupIds] = useState(new Set());
  const [bulkEditorOpen, setBulkEditorOpen] = useState(false);
  const [bulkSettings, setBulkSettings] = useState(EMPTY_BULK_SETTINGS);
  const [epgSources, setEpgSources] = useState([]);
  const [rulesOpen, setRulesOpen] = useState(false);
  const [streamFiltersOpen, setStreamFiltersOpen] = useState(false);
  const [previewGroupId, setPreviewGroupId] = useState(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  const {
    logos: channelLogos,
    ensureLogosLoaded,
    isLoading: logosLoading,
  } = useChannelLogoSelection();
  const [logoModalOpen, setLogoModalOpen] = useState(false);
  const [currentEditingGroupId, setCurrentEditingGroupId] = useState(null);
  const [configuringGroupId, setConfiguringGroupId] = useState(null);
  // Snapshot of the configuring group's state taken when the Configure
  // modal opens. Cancel restores from this; Done discards it.
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
  const configuringGroup = configuringGroupId
    ? groupStates.find((g) => g.channel_group === configuringGroupId)
    : null;
  const previewGroup = previewGroupId
    ? groupStates.find((group) => group.channel_group === previewGroupId)
    : null;

  const applyGroupChange = (nextGroupState) => {
    setGroupStates((prev) =>
      prev.map((state) =>
        state.channel_group === nextGroupState.channel_group
          ? nextGroupState
          : state
      )
    );
  };

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

  // Conflict checks are only needed while one group's settings are open.
  // Avoiding one request/timer per row keeps large Live catalogs responsive.
  useEffect(() => {
    if (!configuringGroup) return;
    const ranges = new Map();
    for (const g of groupStates) {
      const r = rangeFor(g);
      if (r) ranges.set(g.channel_group, r);
    }
    const groupId = configuringGroup.channel_group;
    const range = ranges.get(groupId);
    if (!range) {
      setConflictSource(groupId, 'form', false);
      setConflictSource(groupId, 'occupant', false);
      delete lastConflictSigRef.current[groupId];
      return;
    }
    let hasFormConflict = false;
    for (const [otherId, otherRange] of ranges) {
      if (otherId === groupId) continue;
      if (range.start <= otherRange.end && otherRange.start <= range.end) {
        hasFormConflict = true;
        break;
      }
    }
    setConflictSource(groupId, 'form', hasFormConflict);
    const sig = `${range.start}|${range.end}`;
    if (lastConflictSigRef.current[groupId] !== sig) {
      lastConflictSigRef.current[groupId] = sig;
      scheduleConflictScan(
        groupId,
        range.startRaw,
        configuringGroup.auto_sync_channel_end,
        effectiveSyncGroupId(configuringGroup)
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groupStates, configuringGroupId]);

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
      } catch (e) {
        if (e?.name === 'AbortError') return;
        throw e;
      }
      if (!response) {
        setRegexPreviewState((prev) => ({ ...prev, [groupId]: emptyState }));
        return;
      }
      const buildResult = (key, errorKey) => ({
        matches: response[`${key}_matches`] || [],
        match_count: response[`${key}_match_count`] || 0,
        total_in_group: response.total_in_group || 0,
        total_scanned: response.total_scanned || 0,
        scan_limit_hit: !!response.scan_limit_hit,
        error: response[errorKey] || null,
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
  }, [configuringGroup?.channel_group]);

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
    lastInitKey.current = initKey;

    setGroupStates(
      playlist.channel_groups
        .filter((group) => channelGroups[group.channel_group])
        .map((group) => {
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

  const toggleGroupEnabled = (id) => {
    setGroupStates((prev) =>
      prev.map((state) => ({
        ...state,
        enabled: state.channel_group == id ? !state.enabled : state.enabled,
      }))
    );
  };

  const toggleAutoSync = (id) => {
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

  const updateSelectedGroups = (changes) => {
    setGroupStates((prev) =>
      prev.map((state) =>
        selectedGroupIds.has(state.channel_group)
          ? { ...state, ...changes }
          : state
      )
    );
  };

  const applyBulkSettings = () => {
    setGroupStates((current) =>
      current.map((group) => {
        if (!selectedGroupIds.has(group.channel_group)) return group;
        const next = { ...group };
        if (bulkSettings.enabled !== 'keep') {
          next.enabled = bulkSettings.enabled === 'enabled';
        }
        if (bulkSettings.autoSync !== 'keep') {
          next.auto_channel_sync = bulkSettings.autoSync === 'enabled';
        }
        const customProperties = { ...(group.custom_properties || {}) };
        if (bulkSettings.numberingMode !== 'keep') {
          customProperties.channel_numbering_mode = bulkSettings.numberingMode;
        }
        if (bulkSettings.orphanCleanup !== 'keep') {
          customProperties.orphan_channel_cleanup = bulkSettings.orphanCleanup;
        }
        next.custom_properties = customProperties;
        return next;
      })
    );
    setBulkEditorOpen(false);
    setBulkSettings(EMPTY_BULK_SETTINGS);
  };

  const closeBulkEditor = () => {
    setBulkEditorOpen(false);
    setBulkSettings(EMPTY_BULK_SETTINGS);
  };

  const toggleSelectedGroup = (id, checked) => {
    setSelectedGroupIds((current) => {
      const next = new Set(current);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const visibleGroups = groupStates
    .filter((group) => isGroupVisible(group, groupFilter, statusFilter))
    .sort((a, b) => a.name.localeCompare(b.name));
  const pageCount = Math.max(1, Math.ceil(visibleGroups.length / pageSize));
  const pagedGroups = visibleGroups.slice(
    (page - 1) * pageSize,
    page * pageSize
  );
  const allVisibleSelected =
    visibleGroups.length > 0 &&
    visibleGroups.every((group) => selectedGroupIds.has(group.channel_group));

  useEffect(() => {
    setPage(1);
  }, [groupFilter, statusFilter, pageSize]);

  useEffect(() => {
    if (page > pageCount) setPage(pageCount);
  }, [page, pageCount]);

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

  return (
    <Stack style={{ paddingTop: 10, height: '100%', minHeight: 0 }}>
      <Group justify="flex-start" align="center">
        <Button variant="default" size="xs" onClick={() => setRulesOpen(true)}>
          Import rules
        </Button>
        <Button
          variant="default"
          size="xs"
          onClick={() => setStreamFiltersOpen(true)}
        >
          Stream filters
        </Button>
        <Text size="xs" c="dimmed">
          New unmatched groups are imported inactive.
        </Text>
      </Group>

      <Flex gap="sm" align="center" wrap="wrap">
        <TextInput
          placeholder="Filter groups..."
          value={groupFilter}
          onChange={(event) => setGroupFilter(event.currentTarget.value)}
          style={{ flex: 1 }}
          size="xs"
        />
        <SegmentedControl
          value={statusFilter}
          onChange={setStatusFilter}
          size="xs"
          data={[
            { label: 'All', value: 'all' },
            { label: 'Enabled', value: 'enabled' },
            { label: 'Disabled', value: 'disabled' },
          ]}
        />
        <Button
          variant="default"
          size="xs"
          disabled={!selectedGroupIds.size}
          onClick={() => updateSelectedGroups({ enabled: true })}
        >
          Enable selected
        </Button>
        <Button
          variant="default"
          size="xs"
          disabled={!selectedGroupIds.size}
          onClick={() => updateSelectedGroups({ enabled: false })}
        >
          Disable selected
        </Button>
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
      </Flex>

      <Divider label="Groups & Auto Sync Settings" labelPosition="center" />

      <ScrollArea style={{ flex: 1, minHeight: 0 }}>
        <Table striped highlightOnHover withTableBorder stickyHeader>
          <TableThead>
            <TableTr>
              <TableTh w={44}>
                <Checkbox
                  aria-label="Select visible groups"
                  checked={allVisibleSelected}
                  onChange={(event) =>
                    toggleVisibleSelection(event.currentTarget.checked)
                  }
                />
              </TableTh>
              <TableTh>Group</TableTh>
              <TableTh w={100}>Enabled</TableTh>
              <TableTh w={125} ta="center">
                <Tooltip
                  label="Automatically creates channels for streams in this group during M3U updates. Cleanup behavior is configured per group."
                  multiline
                  w={300}
                  withArrow
                >
                  <Group
                    gap={5}
                    wrap="nowrap"
                    aria-label="About Auto Sync"
                    style={{ width: 'fit-content', cursor: 'help' }}
                  >
                    <Text inherit>Auto Sync</Text>
                    <Info size={14} aria-hidden="true" />
                  </Group>
                </Tooltip>
              </TableTh>
              <TableTh w={120}>Numbering</TableTh>
              <TableTh w={150}>Channel range</TableTh>
              <TableTh w={95} ta="center">
                Actions
              </TableTh>
            </TableTr>
          </TableThead>
          <TableTbody>
            {pagedGroups.map((group) => (
              <TableTr key={group.channel_group}>
                <TableTd ta="center">
                  <Checkbox
                    aria-label={`Select ${group.name}`}
                    checked={selectedGroupIds.has(group.channel_group)}
                    onChange={(event) =>
                      toggleSelectedGroup(
                        group.channel_group,
                        event.currentTarget.checked
                      )
                    }
                  />
                </TableTd>
                <TableTd>
                  <Tooltip
                    label="This group was not seen in the last M3U refresh and may be removed after its retention period."
                    disabled={!group.is_stale}
                  >
                    <Text c={group.is_stale ? 'orange' : undefined}>
                      {group.name}
                    </Text>
                  </Tooltip>
                </TableTd>
                <TableTd>
                  <Button
                    size="compact-xs"
                    color={group.enabled ? 'green' : 'gray'}
                    variant={group.enabled ? 'filled' : 'light'}
                    aria-label={`Enable ${group.name}`}
                    aria-pressed={group.enabled}
                    onClick={() => toggleGroupEnabled(group.channel_group)}
                  >
                    {group.enabled ? 'Active' : 'Inactive'}
                  </Button>
                </TableTd>
                <TableTd ta="center">
                  <Checkbox
                    aria-label={`Auto sync ${group.name}`}
                    checked={group.auto_channel_sync && group.enabled}
                    disabled={!group.enabled}
                    onChange={() => toggleAutoSync(group.channel_group)}
                  />
                </TableTd>
                <TableTd>
                  <Text size="sm">
                    {{
                      fixed: 'Fixed',
                      provider: 'Provider',
                      next_available: 'Next available',
                    }[
                      group.custom_properties?.channel_numbering_mode || 'fixed'
                    ] || 'Fixed'}
                  </Text>
                </TableTd>
                <TableTd>
                  {group.auto_channel_sync && group.enabled ? (
                    <Text size="sm">
                      {(group.custom_properties?.channel_numbering_mode ||
                        'fixed') === 'next_available'
                        ? 'From 1'
                        : `${
                            (group.custom_properties?.channel_numbering_mode ||
                              'fixed') === 'provider'
                              ? group.custom_properties
                                  ?.channel_numbering_fallback || 1
                              : group.auto_sync_channel_start || 1
                          } – ${group.auto_sync_channel_end || 'unlimited'}`}
                    </Text>
                  ) : (
                    <Text size="xs" c="dimmed">
                      Auto sync disabled
                    </Text>
                  )}
                </TableTd>
                <TableTd>
                  <Group gap={4} justify="center" wrap="nowrap">
                    <Tooltip label="Configure advanced options" withArrow>
                      <ActionIcon
                        variant="subtle"
                        disabled={!group.enabled}
                        onClick={() => {
                          configureSnapshotRef.current = {
                            ...group,
                            custom_properties: {
                              ...(group.custom_properties || {}),
                            },
                          };
                          setConfiguringGroupId(group.channel_group);
                        }}
                        aria-label={`Configure ${group.name}`}
                      >
                        <Cog size={16} />
                      </ActionIcon>
                    </Tooltip>
                    <Tooltip label="Preview imported content" withArrow>
                      <ActionIcon
                        variant="subtle"
                        onClick={() => setPreviewGroupId(group.channel_group)}
                        aria-label={`Preview ${group.name}`}
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
        total={visibleGroups.length}
        onPageChange={setPage}
        onPageSizeChange={setPageSize}
      />

      <Modal
        opened={!!previewGroup}
        onClose={() => setPreviewGroupId(null)}
        title={
          previewGroup
            ? `Preview imported content: ${previewGroup.name}`
            : 'Preview imported content'
        }
        size="85vw"
      >
        {previewGroup && (
          <M3UDeveloperCatalog
            accountId={playlist.id}
            initialScope="live"
            lockedScope
            initialCategory={String(previewGroup.channel_group)}
            summaryOnly
          />
        )}
      </Modal>

      <Modal
        opened={rulesOpen}
        onClose={() => setRulesOpen(false)}
        title="Live import rules"
        size="95vw"
        scrollAreaComponent={Modal.NativeScrollArea}
      >
        <M3UGroupRules accountId={playlist.id} scope="live" />
      </Modal>

      {streamFiltersOpen && (
        <ErrorBoundary>
          <Suspense fallback={<Loader />}>
            <M3UFilters
              playlist={playlist}
              isOpen={streamFiltersOpen}
              onClose={() => setStreamFiltersOpen(false)}
            />
          </Suspense>
        </ErrorBoundary>
      )}

      {/* Per-group settings stay out of the table so large provider catalogs
          render only lightweight summaries in each row. */}
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
      >
        {configuringGroup && (
          <>
            <Checkbox
              label="Auto sync"
              description="Create and maintain channels for streams in this group."
              checked={!!configuringGroup.auto_channel_sync}
              disabled={!configuringGroup.enabled}
              onChange={() => toggleAutoSync(configuringGroup.channel_group)}
            />
            <SegmentedControl
              value={
                configuringGroup.custom_properties?.channel_numbering_mode ||
                'fixed'
              }
              disabled={
                !configuringGroup.enabled || !configuringGroup.auto_channel_sync
              }
              onChange={(value) =>
                applyGroupChange({
                  ...configuringGroup,
                  custom_properties: {
                    ...(configuringGroup.custom_properties || {}),
                    channel_numbering_mode: value || 'fixed',
                  },
                })
              }
              data={[
                { value: 'fixed', label: 'Fixed' },
                { value: 'provider', label: 'Provider' },
                { value: 'next_available', label: 'Next available' },
              ]}
              size="xs"
              fullWidth
            />
            {configuringGroup.enabled && configuringGroup.auto_channel_sync && (
              <AutoSyncBasic
                group={configuringGroup}
                groupStates={groupStates}
                groupConflicts={groupConflicts}
                onApplyGroupChange={applyGroupChange}
              />
            )}
            <Select
              label="Auto-sync orphan cleanup"
              description="What to do with this group's auto-created channels when their source stream disappears."
              value={
                configuringGroup.custom_properties?.orphan_channel_cleanup ||
                'always'
              }
              onChange={(value) =>
                applyGroupChange({
                  ...configuringGroup,
                  custom_properties: {
                    ...(configuringGroup.custom_properties || {}),
                    orphan_channel_cleanup: value || 'always',
                  },
                })
              }
              data={[
                { value: 'always', label: 'Always remove' },
                {
                  value: 'preserve_customized',
                  label: 'Preserve customized',
                },
                { value: 'never', label: 'Never remove' },
              ]}
            />
            <ErrorBoundary inline>
              <Suspense fallback={<Loader />}>
                <AutoSyncAdvanced
                  group={configuringGroup}
                  epgSources={epgSources}
                  channelGroups={channelGroups}
                  streamProfiles={streamProfiles}
                  regexPreviewState={regexPreviewState}
                  onApplyGroupChange={applyGroupChange}
                  onScheduleRegexPreview={scheduleRegexPreview}
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
          </>
        )}
      </GroupConfigureModal>

      <Modal
        opened={bulkEditorOpen}
        onClose={closeBulkEditor}
        title={`Edit settings for ${selectedGroupIds.size} groups`}
      >
        <Stack>
          <Text size="sm" c="dimmed">
            Keep unchanged leaves the current value of each group intact.
          </Text>
          <Select
            label="Enabled"
            value={bulkSettings.enabled}
            onChange={(value) =>
              setBulkSettings({ ...bulkSettings, enabled: value || 'keep' })
            }
            data={[
              { value: 'keep', label: 'Keep unchanged' },
              { value: 'enabled', label: 'Enabled' },
              { value: 'disabled', label: 'Disabled' },
            ]}
          />
          <Select
            label="Auto sync"
            value={bulkSettings.autoSync}
            onChange={(value) =>
              setBulkSettings({ ...bulkSettings, autoSync: value || 'keep' })
            }
            data={[
              { value: 'keep', label: 'Keep unchanged' },
              { value: 'enabled', label: 'Enabled' },
              { value: 'disabled', label: 'Disabled' },
            ]}
          />
          <Select
            label="Numbering mode"
            value={bulkSettings.numberingMode}
            onChange={(value) =>
              setBulkSettings({
                ...bulkSettings,
                numberingMode: value || 'keep',
              })
            }
            data={[
              { value: 'keep', label: 'Keep unchanged' },
              { value: 'fixed', label: 'Fixed' },
              { value: 'provider', label: 'Provider' },
              { value: 'next_available', label: 'Next available' },
            ]}
          />
          <Select
            label="Auto-sync orphan cleanup"
            value={bulkSettings.orphanCleanup}
            onChange={(value) =>
              setBulkSettings({
                ...bulkSettings,
                orphanCleanup: value || 'keep',
              })
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
          <Group justify="flex-end">
            <Button variant="default" onClick={closeBulkEditor}>
              Cancel
            </Button>
            <Button onClick={applyBulkSettings}>Apply</Button>
          </Group>
        </Stack>
      </Modal>

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
