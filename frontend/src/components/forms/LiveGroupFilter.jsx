import React, { Suspense, useEffect, useRef, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Box,
  Button,
  Checkbox,
  Divider,
  Flex,
  Group,
  Loader,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { CircleCheck, CircleX, Info, Settings as Cog } from 'lucide-react';
import GroupConfigureModal from './GroupConfigureModal';
import useChannelsStore from '../../store/channels';
import useStreamProfilesStore from '../../store/streamProfiles';
import { useChannelLogoSelection } from '../../hooks/useSmartLogos';
import OrphanCleanupControl from './AutoSyncOrphanCleanup.jsx';
import AutoSyncBasic from './AutoSyncBasic.jsx';
import ErrorBoundary from '../ErrorBoundary.jsx';
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
  isGroupVisible,
  rangeFor,
} from '../../utils/forms/LiveGroupFilterUtils.js';

const LiveGroupFilter = ({
  playlist,
  groupStates,
  setGroupStates,
  autoEnableNewGroupsLive,
  setAutoEnableNewGroupsLive,
}) => {
  const channelGroups = useChannelsStore((s) => s.channelGroups);
  const streamProfiles = useStreamProfilesStore((s) => s.profiles);
  const fetchStreamProfiles = useStreamProfilesStore((s) => s.fetchProfiles);
  const [groupFilter, setGroupFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [epgSources, setEpgSources] = useState([]);

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
  const scheduleConflictScan = (groupId, rawStart, rawEnd) => {
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
          (o) => !isExpectedOccupantForGroup(o, groupId, playlist)
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
          g.auto_sync_channel_end
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
  }, [playlist, channelGroups]);

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

  const selectAll = () => {
    setGroupStates((prev) =>
      prev.map((state) => ({
        ...state,
        enabled: isGroupVisible(state, groupFilter, statusFilter)
          ? true
          : state.enabled,
      }))
    );
  };

  const deselectAll = () => {
    setGroupStates((prev) =>
      prev.map((state) => ({
        ...state,
        enabled: isGroupVisible(state, groupFilter, statusFilter)
          ? false
          : state.enabled,
      }))
    );
  };

  return (
    <Stack style={{ paddingTop: 10 }}>
      <Alert icon={<Info size={16} />} color="blue" variant="light">
        <Text size="sm">
          <strong>Auto Channel Sync:</strong> When enabled, channels will be
          automatically created for all streams in the group during M3U updates,
          and removed when streams are no longer present. Set a starting channel
          number for each group to organize your channels.
        </Text>
      </Alert>

      <Checkbox
        label="Automatically enable new groups discovered on future scans"
        checked={autoEnableNewGroupsLive}
        onChange={(event) =>
          setAutoEnableNewGroupsLive(event.currentTarget.checked)
        }
        size="sm"
        description="When disabled, new groups from the M3U source will be created but disabled by default. You can enable them manually later."
      />

      <OrphanCleanupControl playlist={playlist} />

      <Flex gap="sm" align="center">
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
        <Button variant="default" size="xs" onClick={selectAll}>
          Select Visible
        </Button>
        <Button variant="default" size="xs" onClick={deselectAll}>
          Deselect Visible
        </Button>
      </Flex>

      <Divider label="Groups & Auto Sync Settings" labelPosition="center" />

      <Box style={{ maxHeight: 'calc(50vh - 80px)', overflowY: 'auto' }}>
        <SimpleGrid
          cols={{ base: 1, sm: 2, md: 3 }}
          spacing="xs"
          verticalSpacing="xs"
        >
          {groupStates
            .filter((group) => isGroupVisible(group, groupFilter, statusFilter))
            .sort((a, b) => a.name.localeCompare(b.name))
            .map((group) => (
              <Group
                key={group.channel_group}
                spacing="xs"
                style={{
                  padding: '8px',
                  border: '1px solid #444',
                  borderRadius: '8px',
                  backgroundColor: group.enabled ? '#2A2A2E' : '#1E1E22',
                  flexDirection: 'column',
                  alignItems: 'stretch',
                }}
              >
                {/* Group Enable/Disable Button */}
                <Tooltip
                  label={
                    group.enabled && group.is_stale
                      ? 'This group was not seen in the last M3U refresh and will be deleted after the retention period expires'
                      : ''
                  }
                  disabled={!group.enabled || !group.is_stale}
                  multiline
                  w={220}
                >
                  <Button
                    color={
                      group.enabled
                        ? group.is_stale
                          ? 'orange'
                          : 'green'
                        : 'gray'
                    }
                    variant="filled"
                    onClick={() => toggleGroupEnabled(group.channel_group)}
                    radius="md"
                    size="xs"
                    leftSection={
                      group.enabled ? (
                        <CircleCheck size={14} />
                      ) : (
                        <CircleX size={14} />
                      )
                    }
                    fullWidth
                  >
                    <Text size="xs" truncate>
                      {group.name}
                    </Text>
                  </Button>
                </Tooltip>

                {/* Auto Sync Controls */}
                <Stack spacing="xs" style={{ '--stack-gap': '4px' }}>
                  <Flex align="center" gap="xs" justify="space-between">
                    <Checkbox
                      label="Auto Channel Sync"
                      checked={group.auto_channel_sync && group.enabled}
                      disabled={!group.enabled}
                      onChange={() => toggleAutoSync(group.channel_group)}
                      size="xs"
                    />
                    {group.auto_channel_sync && group.enabled && (
                      <Tooltip
                        label="Configure advanced options for this group"
                        withArrow
                      >
                        <ActionIcon
                          variant="subtle"
                          size="sm"
                          onClick={() => {
                            // Snapshot at open time so Cancel can restore
                            // pre-edit state. custom_properties needs a
                            // one-level clone since the rest of group
                            // state is flat.
                            configureSnapshotRef.current = {
                              ...group,
                              custom_properties: {
                                ...(group.custom_properties || {}),
                              },
                            };
                            setConfiguringGroupId(group.channel_group);
                          }}
                          aria-label="Configure group"
                        >
                          <Cog size={14} />
                        </ActionIcon>
                      </Tooltip>
                    )}
                  </Flex>

                  {group.auto_channel_sync && group.enabled && (
                    <>
                      <Tooltip
                        label={
                          <div>
                            <div>
                              <strong>Fixed:</strong> Start at a specific number
                              and increment
                            </div>
                            <div>
                              <strong>Provider:</strong> Use channel numbers
                              from the M3U source
                            </div>
                            <div>
                              <strong>Next Available:</strong> Auto-assign
                              starting from 1, skipping used numbers
                            </div>
                          </div>
                        }
                        withArrow
                        multiline
                        w={280}
                        openDelay={500}
                      >
                        <Box>
                          <Text size="xs" mb={6}>
                            Channel Numbering Mode
                          </Text>
                          <SegmentedControl
                            value={
                              group.custom_properties?.channel_numbering_mode ||
                              'fixed'
                            }
                            onChange={(value) => {
                              setGroupStates((prev) =>
                                prev.map((state) => {
                                  if (
                                    state.channel_group === group.channel_group
                                  ) {
                                    return {
                                      ...state,
                                      custom_properties: {
                                        ...state.custom_properties,
                                        channel_numbering_mode:
                                          value || 'fixed',
                                      },
                                    };
                                  }
                                  return state;
                                })
                              );
                            }}
                            data={[
                              { value: 'fixed', label: 'Fixed' },
                              { value: 'provider', label: 'Provider' },
                              { value: 'next_available', label: 'Next Avail' },
                            ]}
                            size="xs"
                            fullWidth
                          />
                        </Box>
                      </Tooltip>

                      {(() => {
                        const m =
                          group.custom_properties?.channel_numbering_mode ||
                          'fixed';
                        if (m === 'next_available') return null;
                        return (
                          <Text size="xs" c="dimmed" mt={-2}>
                            {m === 'provider'
                              ? 'Provider numbers; falls back to Start - End.'
                              : 'Channels number sequentially from Start - End.'}
                          </Text>
                        );
                      })()}

                      <AutoSyncBasic
                        group={group}
                        groupStates={groupStates}
                        groupConflicts={groupConflicts}
                        onApplyGroupChange={applyGroupChange}
                      />
                    </>
                  )}
                </Stack>
              </Group>
            ))}
        </SimpleGrid>
      </Box>

      {/* Per-group Configure modal. Holds the Advanced Options MultiSelect
          and all its conditional fields so the inline row only renders the
          core Sync toggle, Numbering Mode, and Start/End inputs regardless
          of how many advanced options are active. */}
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
          <ErrorBoundary>
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
        )}
      </GroupConfigureModal>

      {/* Logo Upload Modal */}
      {logoModalOpen && (
        <ErrorBoundary>
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
