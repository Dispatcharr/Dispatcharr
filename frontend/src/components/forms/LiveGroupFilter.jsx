import React, { useEffect, useRef, useState } from 'react';
import {
  TextInput,
  Button,
  Checkbox,
  Flex,
  Select,
  Stack,
  Group,
  SimpleGrid,
  Text,
  NumberInput,
  Divider,
  Alert,
  Box,
  MultiSelect,
  Tooltip,
  Popover,
  ScrollArea,
  Center,
  SegmentedControl,
  ActionIcon,
  Switch,
} from '@mantine/core';
import {
  Info,
  CircleCheck,
  CircleX,
  Settings as Cog,
  AlertTriangle,
  RefreshCw,
} from 'lucide-react';
import GroupConfigureModal from './GroupConfigureModal';
import { notifications } from '@mantine/notifications';
import useChannelsStore from '../../store/channels';
import useStreamProfilesStore from '../../store/streamProfiles';
import { useChannelLogoSelection } from '../../hooks/useSmartLogos';
import { FixedSizeList as List } from 'react-window';
import LazyLogo from '../LazyLogo';
import LogoForm from './Logo';
import logo from '../../images/logo.png';
import API from '../../api';
import { getGroupReservation } from '../../utils/forms/GroupSyncUtils';

const LiveGroupFilter = ({
  playlist,
  groupStates,
  setGroupStates,
  autoEnableNewGroupsLive,
  setAutoEnableNewGroupsLive,
}) => {
  const channelGroups = useChannelsStore((s) => s.channelGroups);
  const profiles = useChannelsStore((s) => s.profiles);
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

  // "Expected" occupants are this group's own auto-sync output:
  // auto_created, in this group on this account, no channel_number
  // override. Channels from any other provider, group, or with a user
  // pin all surface as a warning so the user is aware their range
  // overlaps with existing assignments. Sync still merges shared
  // ranges across providers, so the warning is informational rather
  // than blocking.
  const isExpectedOccupantForGroup = (occupant, groupChannelGroupId) => {
    if (!occupant) return false;
    if (!occupant.auto_created) return false;
    if (occupant.has_channel_number_override) return false;
    if (
      occupant.channel_group_id !== undefined &&
      occupant.channel_group_id !== groupChannelGroupId
    )
      return false;
    if (
      occupant.auto_created_by_account_id !== undefined &&
      playlist?.id !== undefined &&
      occupant.auto_created_by_account_id !== playlist.id
    )
      return false;
    return true;
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
        const result = await API.getChannelsInRange(start, end, {
          signal: controller.signal,
        });
        const occupants = Array.isArray(result?.occupants)
          ? result.occupants
          : [];
        const unexpected = occupants.filter(
          (o) => !isExpectedOccupantForGroup(o, groupId)
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
      Object.values(conflictTimersRef.current).forEach((t) => clearTimeout(t));
      conflictTimersRef.current = {};
      Object.values(conflictAbortRef.current).forEach((c) => {
        try {
          c.abort();
        } catch {
          // ignore
        }
      });
      conflictAbortRef.current = {};
    };
  }, []);

  // Sweep effect: recomputes form-overlap in-memory for every group
  // (cheap). The HTTP-bound DB scan only runs for groups whose own
  // range fields changed since the last sweep.
  useEffect(() => {
    const rangeFor = (g) => {
      if (!g.enabled || !g.auto_channel_sync) return null;
      const mode = g.custom_properties?.channel_numbering_mode || 'fixed';
      if (mode === 'next_available') return null;
      const startRaw =
        mode === 'provider'
          ? (g.custom_properties?.channel_numbering_fallback ?? 1)
          : (g.auto_sync_channel_start ?? 1);
      const start = Number(startRaw);
      if (!Number.isFinite(start)) return null;
      const endRaw = g.auto_sync_channel_end;
      const end =
        endRaw === null || endRaw === undefined || endRaw === ''
          ? start
          : Number(endRaw);
      return { start, end, startRaw };
    };

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
    const cacheKey = `${groupId}|${find}|${replace}|${match}|${exclude}`;
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
        response = await API.getStreamsRegexPreview(group.name, {
          find: find || undefined,
          replace: find ? replace : undefined,
          match: match || undefined,
          exclude: exclude || undefined,
          limit: 10,
          signal: controller.signal,
        });
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
      Object.values(regexPreviewTimersRef.current).forEach((t) =>
        clearTimeout(t)
      );
      regexPreviewTimersRef.current = {};
      Object.values(regexPreviewAbortRef.current).forEach((c) => {
        try {
          c.abort();
        } catch {
          // ignore
        }
      });
      regexPreviewAbortRef.current = {};
    };
  }, []);

  // When the gear modal opens (or its open group changes), trigger a
  // preview fetch using whatever patterns are already saved on that
  // group. Subsequent edits to the patterns trigger their own scheduled
  // fetches via the field handlers.
  useEffect(() => {
    if (!configuringGroup) return;
    const cp = configuringGroup.custom_properties || {};
    scheduleRegexPreview(configuringGroup, {
      find: cp.name_regex_pattern || '',
      replace: cp.name_replace_pattern ?? '',
      match: cp.name_match_regex || '',
      exclude: cp.name_match_exclude_regex || '',
    });
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
        const sources = await API.getEPGs();
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

        let proposedStart = 1;
        for (const other of prev) {
          if (other.channel_group == id) continue;
          if (!other.enabled || !other.auto_channel_sync) continue;
          const otherMode =
            other.custom_properties?.channel_numbering_mode || 'fixed';
          if (otherMode === 'next_available') continue;
          const otherStart = Number(
            otherMode === 'provider'
              ? (other.custom_properties?.channel_numbering_fallback ?? 1)
              : (other.auto_sync_channel_start ?? 1)
          );
          if (!Number.isFinite(otherStart)) continue;
          const otherEnd =
            other.auto_sync_channel_end === null ||
            other.auto_sync_channel_end === undefined ||
            other.auto_sync_channel_end === ''
              ? otherStart
              : Number(other.auto_sync_channel_end);
          const upper = Math.max(otherStart, otherEnd);
          if (upper + 1 > proposedStart) proposedStart = upper + 1;
        }
        next.auto_sync_channel_start = proposedStart;
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

  const isVisible = (group) => {
    const matchesText = group.name
      .toLowerCase()
      .includes(groupFilter.toLowerCase());
    const matchesStatus =
      statusFilter === 'all' ||
      (statusFilter === 'enabled' && group.enabled) ||
      (statusFilter === 'disabled' && !group.enabled);
    return matchesText && matchesStatus;
  };

  const selectAll = () => {
    setGroupStates((prev) =>
      prev.map((state) => ({
        ...state,
        enabled: isVisible(state) ? true : state.enabled,
      }))
    );
  };

  const deselectAll = () => {
    setGroupStates((prev) =>
      prev.map((state) => ({
        ...state,
        enabled: isVisible(state) ? false : state.enabled,
      }))
    );
  };

  // Returns {name, start, end}[] for groups whose declared ranges
  // intersect this group's range, or [] when there is no overlap.
  const computeRangeOverlapsFor = (group) => {
    const myReservation = getGroupReservation(group);
    if (!myReservation) return [];
    const [myStart, myEnd] = myReservation;
    const overlaps = [];
    for (const other of groupStates) {
      if (other.channel_group === group.channel_group) continue;
      const otherReservation = getGroupReservation(other);
      if (!otherReservation) continue;
      const [oStart, oEnd] = otherReservation;
      if (myStart <= oEnd && oStart <= myEnd) {
        overlaps.push({ name: other.name, start: oStart, end: oEnd });
      }
    }
    return overlaps;
  };

  // Inline Start/End range inputs for Fixed and Provider modes. Start
  // writes to auto_sync_channel_start (Fixed) or
  // custom_properties.channel_numbering_fallback (Provider); End always
  // writes to auto_sync_channel_end. Next Available shows a one-line
  // explanation because a range contradicts pack-anywhere semantics.
  const renderNumberingRange = (group) => {
    const mode = group.custom_properties?.channel_numbering_mode || 'fixed';
    if (mode === 'next_available') {
      return (
        <Text size="xs" c="dimmed">
          Channels receive the lowest available numbers starting at 1.
        </Text>
      );
    }
    const startValue =
      mode === 'provider'
        ? (group.custom_properties?.channel_numbering_fallback ?? 1)
        : (group.auto_sync_channel_start ?? 1);
    const endValue = group.auto_sync_channel_end;
    // Caps pathological pasted values like "1e308" at the input layer.
    const MAX_CHANNEL_NUMBER = 999999;
    const clampChannelNumber = (n) =>
      Math.max(1, Math.min(MAX_CHANNEL_NUMBER, Math.floor(Number(n) || 1)));
    const updateStart = (value) => {
      const normalized =
        value === '' || value === null || value === undefined
          ? 1
          : clampChannelNumber(value);
      if (mode === 'provider') {
        applyGroupChange({
          ...group,
          custom_properties: {
            ...(group.custom_properties || {}),
            channel_numbering_fallback: normalized,
          },
        });
      } else {
        // If End is set and the new Start exceeds it, drop End so the user
        // is not left holding an invalid range silently.
        const next = { ...group, auto_sync_channel_start: normalized };
        if (
          endValue !== null &&
          endValue !== undefined &&
          normalized > endValue
        ) {
          next.auto_sync_channel_end = null;
        }
        applyGroupChange(next);
      }
      // Sweep effect picks up the state change and dispatches the scan.
    };
    const updateEnd = (value) => {
      const normalized =
        value === '' || value === null || value === undefined
          ? null
          : clampChannelNumber(value);
      applyGroupChange({
        ...group,
        auto_sync_channel_end: normalized,
      });
    };

    const streamCount =
      typeof group.stream_count === 'number' ? group.stream_count : null;
    const metaParts = [];
    if (endValue) {
      metaParts.push(`Range: ${Math.max(endValue - startValue + 1, 0)}`);
    }
    if (streamCount !== null) {
      metaParts.push(`Streams: ${streamCount}`);
    }
    const metaText = metaParts.join(' · ');

    const conflict = groupConflicts[group.channel_group];
    const hasChannelConflict = !!conflict?.hasChannelConflict;
    const overlaps = computeRangeOverlapsFor(group);

    // Channel-level conflicts get a generic Channels-page pointer (count
    // can be large); range-level overlaps stay specific to the modal.
    const tooltipSections = [];
    if (hasChannelConflict) {
      tooltipSections.push(
        'Range conflicts with configured channels.\nView the Channels page to inspect.'
      );
    }
    if (overlaps.length > 0) {
      const overlapLines = overlaps
        .map((o) => `${o.name} (${o.start}-${o.end})`)
        .join('\n  ');
      tooltipSections.push(
        overlaps.length === 1
          ? `Range overlaps with: ${overlaps[0].name} (${overlaps[0].start}-${overlaps[0].end})`
          : `Range overlaps with:\n  ${overlapLines}`
      );
    }
    const showWarning = tooltipSections.length > 0;
    const tooltipBody = tooltipSections.join('\n\n');

    return (
      <Stack gap={4}>
        <Flex gap="xs" align="flex-start">
          <Tooltip
            label={
              mode === 'provider'
                ? 'Fallback channel number used when a stream has no provider-supplied number.'
                : 'First channel number assigned to this group.'
            }
            withArrow
            multiline
            w={260}
          >
            <NumberInput
              label="Start #"
              value={startValue}
              onChange={updateStart}
              min={1}
              step={1}
              size="xs"
              precision={0}
              style={{ flex: 1 }}
            />
          </Tooltip>
          <Tooltip
            label="Optional upper bound. Streams exceeding the range are skipped and reported after sync."
            withArrow
            multiline
            w={260}
          >
            <NumberInput
              label="End # (optional)"
              placeholder="Unlimited"
              value={endValue ?? ''}
              onChange={updateEnd}
              min={startValue || 1}
              step={1}
              size="xs"
              precision={0}
              style={{ flex: 1 }}
            />
          </Tooltip>
        </Flex>
        <Flex
          gap="xs"
          align="center"
          justify="space-between"
          style={{ minHeight: 18 }}
        >
          <Text size="xs" c="dimmed">
            {metaText}
          </Text>
          {showWarning && (
            <Tooltip
              label={tooltipBody}
              withArrow
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
        </Flex>
      </Stack>
    );
  };

  // Header line for the preview box. Adds a scan-cap suffix when the
  // backend only scanned the first SCAN_CAP streams of the group.
  const formatPreviewSummary = (label, result) => {
    if (!result) return null;
    const { match_count, total_in_group, total_scanned, scan_limit_hit } =
      result;
    const matchWord = `match${match_count === 1 ? '' : 'es'}`;
    if (scan_limit_hit) {
      return `${match_count} ${matchWord} in first ${total_scanned.toLocaleString()} streams scanned (of ${total_in_group.toLocaleString()} total)`;
    }
    return `${match_count} ${label} ${matchWord} in ${total_scanned.toLocaleString()} stream${total_scanned === 1 ? '' : 's'}`;
  };

  // Find/replace regex preview backed by /streams/regex-preview/, so
  // counts reflect the whole group (or up to SCAN_CAP) rather than a
  // small client-side sample.
  const renderRegexPreview = (group) => {
    const find = group.custom_properties?.name_regex_pattern || '';
    if (!find) return null;
    const state = regexPreviewState[group.channel_group] || {};
    const result = state.findResult;
    const loading = state.loading;
    return (
      <Box
        style={{
          border: '1px solid #3F3F46',
          borderRadius: 6,
          padding: 8,
          backgroundColor: '#1E1E22',
        }}
      >
        <Text size="xs" fw={600} mb={4}>
          {result ? formatPreviewSummary('rename', result) : 'Preview'}
        </Text>
        {result?.error && (
          <Text size="xs" c="red.5">
            Invalid regex: {result.error}
          </Text>
        )}
        {loading && !result && (
          <Text size="xs" c="dimmed">
            Scanning streams...
          </Text>
        )}
        {result && !result.error && result.matches.length === 0 && (
          <Text size="xs" c="dimmed">
            {result.total_in_group === 0
              ? 'No streams in this group yet.'
              : 'No streams matched this pattern.'}
          </Text>
        )}
        {result?.matches?.map((row, idx) => (
          <Flex
            key={`${row.before}-${idx}`}
            gap="xs"
            align="center"
            style={{ fontFamily: 'monospace' }}
          >
            <Text size="xs" c="dimmed" style={{ flex: 1 }} truncate>
              {row.before}
            </Text>
            <Text size="xs" c="gray.5">
              {' -> '}
            </Text>
            <Text size="xs" c="teal.4" style={{ flex: 1 }} truncate>
              {row.after}
            </Text>
          </Flex>
        ))}
      </Box>
    );
  };

  // Shared preview box for include and exclude filters. The marker and
  // color reflect whether matched names are kept (teal check) or dropped
  // (red x); empty/loading/error states mirror the find preview.
  const renderFilterPreview = (group, kind) => {
    const pattern =
      kind === 'exclude'
        ? group.custom_properties?.name_match_exclude_regex || ''
        : group.custom_properties?.name_match_regex || '';
    if (!pattern) return null;
    const state = regexPreviewState[group.channel_group] || {};
    const result =
      kind === 'exclude' ? state.excludeResult : state.filterResult;
    const loading = state.loading;
    const summaryLabel = kind === 'exclude' ? 'exclude' : 'filter';
    const placeholderLabel =
      kind === 'exclude' ? 'Exclude preview' : 'Filter preview';
    const markerChar = kind === 'exclude' ? '✗' : '✓';
    const markerColor = kind === 'exclude' ? 'red.4' : 'teal.4';
    const emptyText =
      kind === 'exclude'
        ? 'No streams matched this pattern (nothing would be excluded).'
        : 'No streams matched this pattern.';
    return (
      <Box
        style={{
          border: '1px solid #3F3F46',
          borderRadius: 6,
          padding: 8,
          backgroundColor: '#1E1E22',
        }}
      >
        <Text size="xs" fw={600} mb={4}>
          {result
            ? formatPreviewSummary(summaryLabel, result)
            : placeholderLabel}
        </Text>
        {result?.error && (
          <Text size="xs" c="red.5">
            Invalid regex: {result.error}
          </Text>
        )}
        {loading && !result && (
          <Text size="xs" c="dimmed">
            Scanning streams...
          </Text>
        )}
        {result && !result.error && result.matches.length === 0 && (
          <Text size="xs" c="dimmed">
            {result.total_in_group === 0
              ? 'No streams in this group yet.'
              : emptyText}
          </Text>
        )}
        {result?.matches?.map((row, idx) => (
          <Flex
            key={`${row.name}-${idx}`}
            gap="xs"
            align="center"
            style={{ fontFamily: 'monospace' }}
          >
            <Text size="xs" c={markerColor} style={{ width: 18 }}>
              {markerChar}
            </Text>
            <Text size="xs" c="gray.2" style={{ flex: 1 }} truncate>
              {row.name}
            </Text>
          </Flex>
        ))}
      </Box>
    );
  };

  const renderMatchPreview = (group) => renderFilterPreview(group, 'include');
  const renderExcludePreview = (group) => renderFilterPreview(group, 'exclude');

  // Advanced Options form rendered inside the gear modal. A field's
  // presence in custom_properties activates it; blanking returns the
  // group to default behavior.
  const renderAdvancedOptions = (group) => {
    const cp = group.custom_properties || {};
    const setCp = (patch, clears = []) => {
      const next = { ...cp, ...patch };
      clears.forEach((k) => delete next[k]);
      applyGroupChange({ ...group, custom_properties: next });
    };

    // --- Name Transforms ---

    const findValue = cp.name_regex_pattern ?? '';
    const replaceValue = cp.name_replace_pattern ?? '';
    const filterValue = cp.name_match_regex ?? '';
    const excludeValue = cp.name_match_exclude_regex ?? '';
    const updateFind = (val) => {
      if (!val && !replaceValue) {
        setCp({}, ['name_regex_pattern', 'name_replace_pattern']);
      } else {
        setCp({
          name_regex_pattern: val,
          name_replace_pattern: replaceValue,
        });
      }
      scheduleRegexPreview(group, {
        find: val,
        replace: replaceValue,
        match: filterValue,
        exclude: excludeValue,
      });
    };
    const updateReplace = (val) => {
      if (!val && !findValue) {
        setCp({}, ['name_regex_pattern', 'name_replace_pattern']);
      } else {
        setCp({
          name_regex_pattern: findValue,
          name_replace_pattern: val,
        });
      }
      scheduleRegexPreview(group, {
        find: findValue,
        replace: val,
        match: filterValue,
        exclude: excludeValue,
      });
    };
    const updateFilter = (val) => {
      if (!val) setCp({}, ['name_match_regex']);
      else setCp({ name_match_regex: val });
      scheduleRegexPreview(group, {
        find: findValue,
        replace: replaceValue,
        match: val,
        exclude: excludeValue,
      });
    };
    const updateExclude = (val) => {
      if (!val) setCp({}, ['name_match_exclude_regex']);
      else setCp({ name_match_exclude_regex: val });
      scheduleRegexPreview(group, {
        find: findValue,
        replace: replaceValue,
        match: filterValue,
        exclude: val,
      });
    };

    // --- EPG ---

    const epgValue = (() => {
      if (cp.custom_epg_id !== undefined && cp.custom_epg_id !== null) {
        return cp.custom_epg_id.toString();
      }
      if (cp.force_dummy_epg) return '0';
      return '';
    })();
    const updateEpg = (value) => {
      const next = { ...cp };
      delete next.custom_epg_id;
      delete next.force_dummy_epg;
      delete next.force_epg_selected;
      if (value === '0') {
        next.force_dummy_epg = true;
      } else if (value) {
        next.custom_epg_id = parseInt(value);
      }
      applyGroupChange({ ...group, custom_properties: next });
    };

    // --- Channel Assignment ---

    const groupOverrideValue = cp.group_override
      ? cp.group_override.toString()
      : '';
    const updateGroupOverride = (value) => {
      if (!value) setCp({}, ['group_override']);
      else setCp({ group_override: parseInt(value) });
    };

    const profileValue = cp.channel_profile_ids ?? [];
    const updateProfiles = (value) => {
      if (!value || value.length === 0) {
        setCp({}, ['channel_profile_ids']);
      } else {
        setCp({ channel_profile_ids: value });
      }
    };

    const streamProfileValue = cp.stream_profile_id
      ? cp.stream_profile_id.toString()
      : '';
    const updateStreamProfile = (value) => {
      if (!value) setCp({}, ['stream_profile_id']);
      else setCp({ stream_profile_id: parseInt(value) });
    };

    const sortOrderValue = cp.channel_sort_order ?? '__default__';
    const sortReverseEnabled = cp.channel_sort_order !== undefined;
    const updateSortOrder = (value) => {
      if (!value || value === '__default__') {
        setCp({}, ['channel_sort_order', 'channel_sort_reverse']);
      } else {
        setCp({
          channel_sort_order: value,
          channel_sort_reverse: cp.channel_sort_reverse ?? false,
        });
      }
    };
    const updateSortReverse = (checked) => {
      setCp({ channel_sort_reverse: checked });
    };

    // --- Custom Logo ---

    const logoValue = cp.custom_logo_id;

    return (
      <Stack gap="lg">
        <Stack gap="sm">
          <Divider
            label={
              <Text size="sm" fw={600} c="gray.3">
                Name Transforms
              </Text>
            }
            labelPosition="left"
            size="sm"
            color="gray.6"
          />
          <Tooltip
            label="Apply a regex find/replace to channel names during sync. Leave both empty to skip."
            withArrow
            multiline
            w={280}
            openDelay={500}
          >
            <Box>
              <Flex gap="xs">
                <TextInput
                  label="Find (Regex)"
                  placeholder="e.g. ^.*? - PPV\\d+ - (.+)$"
                  value={findValue}
                  onChange={(e) => updateFind(e.currentTarget.value)}
                  size="xs"
                  style={{ flex: 1 }}
                />
                <TextInput
                  label="Replace"
                  placeholder="e.g. $1"
                  value={replaceValue}
                  onChange={(e) => updateReplace(e.currentTarget.value)}
                  size="xs"
                  style={{ flex: 1 }}
                />
              </Flex>
              {findValue && renderRegexPreview(group)}
            </Box>
          </Tooltip>
          <Flex gap="xs" align="flex-start">
            <Tooltip
              label="Only include channels whose names match the pattern. Leave empty to include all."
              withArrow
              multiline
              w={280}
              openDelay={500}
            >
              <Box style={{ flex: 1 }}>
                <TextInput
                  label="Include if name matches (Regex)"
                  placeholder="e.g. ^Sports.*"
                  value={filterValue}
                  onChange={(e) => updateFilter(e.currentTarget.value)}
                  size="xs"
                />
                {filterValue && renderMatchPreview(group)}
              </Box>
            </Tooltip>
            <Tooltip
              label="Drop channels whose names match the pattern. Applied after the include filter; useful for removing specific bad streams without rewriting the include pattern."
              withArrow
              multiline
              w={280}
              openDelay={500}
            >
              <Box style={{ flex: 1 }}>
                <TextInput
                  label="Exclude if name matches (Regex)"
                  placeholder="e.g. TEST|BACKUP"
                  value={excludeValue}
                  onChange={(e) => updateExclude(e.currentTarget.value)}
                  size="xs"
                />
                {excludeValue && renderExcludePreview(group)}
              </Box>
            </Tooltip>
          </Flex>
        </Stack>

        <Stack gap="sm">
          <Divider
            label={
              <Text size="sm" fw={600} c="gray.3">
                EPG & Logo
              </Text>
            }
            labelPosition="left"
            size="sm"
            color="gray.6"
          />
          <Flex gap="xs" align="flex-start">
            <Tooltip
              label="Force a specific EPG source. Defaults to auto-matching by tvg_id when blank."
              withArrow
              multiline
              w={280}
              openDelay={500}
            >
              <Select
                label="EPG Source"
                placeholder="Auto-match (default)"
                value={epgValue || null}
                onChange={updateEpg}
                data={[
                  { value: '0', label: 'No EPG (Disabled)' },
                  ...[...epgSources]
                    .sort((a, b) => a.name.localeCompare(b.name))
                    .map((source) => ({
                      value: source.id.toString(),
                      label: `${source.name} (${
                        source.source_type === 'dummy'
                          ? 'Dummy'
                          : source.source_type === 'xmltv'
                            ? 'XMLTV'
                            : source.source_type === 'schedules_direct'
                              ? 'Schedules Direct'
                              : source.source_type
                      })`,
                    })),
                ]}
                clearable
                searchable
                size="xs"
                style={{ flex: 1 }}
              />
            </Tooltip>

            <Box style={{ flex: 1 }}>
              <Group justify="space-between">
                <Popover
                  opened={group.logoPopoverOpened || false}
                  onChange={(opened) => {
                    applyGroupChange({ ...group, logoPopoverOpened: opened });
                    if (opened) ensureLogosLoaded();
                  }}
                  withArrow
                >
                  <Popover.Target>
                    <TextInput
                      label="Custom Logo"
                      placeholder="Stream logo (default)"
                      readOnly
                      value={
                        logoValue ? channelLogos[logoValue]?.name || '' : ''
                      }
                      onClick={() =>
                        applyGroupChange({
                          ...group,
                          logoPopoverOpened: true,
                        })
                      }
                      size="xs"
                      style={{ flex: 1 }}
                    />
                  </Popover.Target>
                  <Popover.Dropdown onMouseDown={(e) => e.stopPropagation()}>
                    <Group>
                      <TextInput
                        placeholder="Filter logos..."
                        size="xs"
                        value={group.logoFilter || ''}
                        onChange={(e) =>
                          applyGroupChange({
                            ...group,
                            logoFilter: e.currentTarget.value,
                          })
                        }
                      />
                      {logosLoading && (
                        <Text size="xs" c="dimmed">
                          Loading...
                        </Text>
                      )}
                    </Group>
                    <ScrollArea style={{ height: 200 }}>
                      {(() => {
                        const logoOptions = [
                          { id: '0', name: 'Default' },
                          ...Object.values(channelLogos),
                        ];
                        const filteredLogos = logoOptions.filter((logoItem) =>
                          logoItem.name
                            .toLowerCase()
                            .includes((group.logoFilter || '').toLowerCase())
                        );
                        if (filteredLogos.length === 0) {
                          return (
                            <Center style={{ height: 200 }}>
                              <Text size="sm" c="dimmed">
                                {group.logoFilter
                                  ? 'No logos match your filter'
                                  : 'No logos available'}
                              </Text>
                            </Center>
                          );
                        }
                        return (
                          <List
                            height={200}
                            itemCount={filteredLogos.length}
                            itemSize={55}
                            style={{ width: '100%' }}
                          >
                            {({ index, style }) => {
                              const logoItem = filteredLogos[index];
                              return (
                                <div
                                  style={{
                                    ...style,
                                    cursor: 'pointer',
                                    padding: '5px',
                                    borderRadius: '4px',
                                  }}
                                  onClick={() => {
                                    const next = { ...cp };
                                    if (logoItem.id === '0' || !logoItem.id) {
                                      delete next.custom_logo_id;
                                    } else {
                                      next.custom_logo_id = logoItem.id;
                                    }
                                    applyGroupChange({
                                      ...group,
                                      custom_properties: next,
                                      logoPopoverOpened: false,
                                    });
                                  }}
                                  onMouseEnter={(e) => {
                                    e.currentTarget.style.backgroundColor =
                                      'rgb(68, 68, 68)';
                                  }}
                                  onMouseLeave={(e) => {
                                    e.currentTarget.style.backgroundColor =
                                      'transparent';
                                  }}
                                >
                                  <Center
                                    style={{
                                      flexDirection: 'column',
                                      gap: '2px',
                                    }}
                                  >
                                    <img
                                      src={logoItem.cache_url || logo}
                                      height="30"
                                      style={{
                                        maxWidth: 80,
                                        objectFit: 'contain',
                                      }}
                                      alt={logoItem.name || 'Logo'}
                                      onError={(e) => {
                                        if (e.target.src !== logo) {
                                          e.target.src = logo;
                                        }
                                      }}
                                    />
                                    <Text
                                      size="xs"
                                      c="dimmed"
                                      ta="center"
                                      style={{
                                        maxWidth: 80,
                                        overflow: 'hidden',
                                        textOverflow: 'ellipsis',
                                        whiteSpace: 'nowrap',
                                      }}
                                    >
                                      {logoItem.name || 'Default'}
                                    </Text>
                                  </Center>
                                </div>
                              );
                            }}
                          </List>
                        );
                      })()}
                    </ScrollArea>
                  </Popover.Dropdown>
                </Popover>
                {logoValue && (
                  <Stack gap="xs" align="center">
                    <LazyLogo
                      logoId={logoValue}
                      alt="custom logo"
                      style={{ height: 40 }}
                    />
                  </Stack>
                )}
              </Group>
              <Button
                onClick={() => {
                  setCurrentEditingGroupId(group.channel_group);
                  setLogoModalOpen(true);
                }}
                variant="subtle"
                size="compact-xs"
                mt={4}
              >
                + Upload new logo
              </Button>
            </Box>
          </Flex>
        </Stack>

        <Stack gap="sm">
          <Divider
            label={
              <Text size="sm" fw={600} c="gray.3">
                Channel Assignment
              </Text>
            }
            labelPosition="left"
            size="sm"
            color="gray.6"
          />
          <Flex gap="xs">
            <Tooltip
              label="Send auto-created channels into a different group than their source."
              withArrow
              multiline
              w={280}
              openDelay={500}
            >
              <Select
                label="Override Channel Group"
                placeholder="Source group (default)"
                value={groupOverrideValue || null}
                onChange={updateGroupOverride}
                data={Object.values(channelGroups).map((g) => ({
                  value: g.id.toString(),
                  label: g.name,
                }))}
                clearable
                searchable
                size="xs"
                style={{ flex: 1 }}
              />
            </Tooltip>
            <Tooltip
              label="Limit auto-created channels to specific channel profiles. Defaults to all profiles when blank."
              withArrow
              multiline
              w={280}
              openDelay={500}
            >
              <MultiSelect
                label="Channel Profiles"
                placeholder="All profiles (default)"
                value={profileValue}
                onChange={updateProfiles}
                data={Object.values(profiles).map((profile) => ({
                  value: profile.id.toString(),
                  label: profile.name,
                }))}
                clearable
                searchable
                size="xs"
                style={{ flex: 1 }}
              />
            </Tooltip>
          </Flex>
          <Flex gap="xs" align="flex-start">
            <Tooltip
              label="Apply a specific stream profile to channels created by this group."
              withArrow
              multiline
              w={280}
              openDelay={500}
            >
              <Select
                label="Stream Profile"
                placeholder="Account default"
                value={streamProfileValue || null}
                onChange={updateStreamProfile}
                data={streamProfiles.map((profile) => ({
                  value: profile.id.toString(),
                  label: profile.name,
                }))}
                clearable
                searchable
                size="xs"
                style={{ flex: 1 }}
              />
            </Tooltip>
            <Tooltip
              label="Order channels within the group before assigning numbers."
              withArrow
              multiline
              w={280}
              openDelay={500}
            >
              <Box style={{ flex: 1 }}>
                <Select
                  label="Channel Sort Order"
                  value={sortOrderValue}
                  onChange={updateSortOrder}
                  data={[
                    { value: '__default__', label: 'Provider Order (Default)' },
                    { value: 'name', label: 'Name' },
                    { value: 'tvg_id', label: 'TVG ID' },
                    { value: 'updated_at', label: 'Updated At' },
                  ]}
                  searchable
                  size="xs"
                />
                {sortReverseEnabled && (
                  <Checkbox
                    label="Reverse sort order"
                    checked={cp.channel_sort_reverse || false}
                    onChange={(event) =>
                      updateSortReverse(event.currentTarget.checked)
                    }
                    size="xs"
                    mt="xs"
                  />
                )}
              </Box>
            </Tooltip>
          </Flex>
          <Flex align="center" justify="space-between" gap="md" mt="xs">
            <Tooltip
              label="Visible channels get sequential numbers; hidden channels release theirs. Set a channel number override to preserve channel numbers over time."
              withArrow
              multiline
              w={320}
              openDelay={500}
            >
              <Box style={{ flex: 1, minWidth: 0 }}>
                <Switch
                  label="Compact numbering"
                  description="Numbers shift on hide/unhide. Pin a number with a channel number override."
                  checked={!!cp.compact_numbering}
                  onChange={(event) => {
                    if (event.currentTarget.checked) {
                      setCp({ compact_numbering: true });
                    } else {
                      setCp({}, ['compact_numbering']);
                    }
                  }}
                  size="xs"
                />
              </Box>
            </Tooltip>
            <Tooltip
              label="Re-assign visible channels into the group's current range. Overrides are kept as reservations and not modified."
              withArrow
              multiline
              w={280}
              openDelay={500}
            >
              <Button
                variant="subtle"
                size="compact-xs"
                color="gray"
                leftSection={<RefreshCw size={12} />}
                onClick={async () => {
                  const result = await API.repackGroupChannels(
                    playlist.id,
                    group.channel_group
                  );
                  if (result) {
                    notifications.show({
                      title: 'Channels renumbered',
                      message: `Assigned ${result.assigned}, released ${result.released}${
                        result.failed
                          ? `, ${result.failed} could not fit in the configured range`
                          : ''
                      }.`,
                      color: result.failed ? 'yellow' : 'green',
                      autoClose: 5000,
                    });
                  }
                }}
                style={{ flexShrink: 0 }}
              >
                Renumber now
              </Button>
            </Tooltip>
          </Flex>
        </Stack>
      </Stack>
    );
  };

  // Local state mirrors the persisted mode so the SegmentedControl
  // reflects clicks immediately even when the parent's playlist prop is
  // a stale snapshot from before the PATCH lands.
  const [orphanCleanupMode, setOrphanCleanupMode] = useState(
    (playlist?.custom_properties || {}).orphan_channel_cleanup || 'always'
  );

  useEffect(() => {
    setOrphanCleanupMode(
      (playlist?.custom_properties || {}).orphan_channel_cleanup || 'always'
    );
  }, [playlist?.id, playlist?.custom_properties?.orphan_channel_cleanup]);

  const handleOrphanCleanupChange = async (mode) => {
    if (!playlist?.id) return;
    const previousMode = orphanCleanupMode;
    setOrphanCleanupMode(mode);
    const nextProps = {
      ...(playlist.custom_properties || {}),
      orphan_channel_cleanup: mode,
    };
    try {
      await API.updatePlaylist({
        id: playlist.id,
        custom_properties: nextProps,
      });
    } catch (err) {
      setOrphanCleanupMode(previousMode);
      notifications.show({
        title: 'Failed to update cleanup mode',
        message: err?.body?.detail || err?.message || 'Please try again.',
        color: 'red',
      });
    }
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

      <Box>
        <Group gap="sm" align="center" wrap="nowrap">
          <Tooltip
            label="Controls what sync does with auto-synced channels whose source streams have been removed from this provider. Manual channels and hidden channels are never affected by this setting."
            withArrow
            multiline
            w={320}
            openDelay={400}
          >
            <Text size="sm" fw={500}>
              Auto-sync orphan cleanup
            </Text>
          </Tooltip>
          <SegmentedControl
            size="xs"
            value={orphanCleanupMode}
            onChange={handleOrphanCleanupChange}
            data={[
              { label: 'Always remove', value: 'always' },
              { label: 'Preserve customized', value: 'preserve_customized' },
              { label: 'Never remove', value: 'never' },
            ]}
          />
        </Group>
        <Text size="xs" c="dimmed" mt={4}>
          {orphanCleanupMode === 'always' &&
            'Removes any auto-synced channel whose source stream is gone from this provider.'}
          {orphanCleanupMode === 'preserve_customized' &&
            'Removes orphaned auto-synced channels except those with active overrides.'}
          {orphanCleanupMode === 'never' &&
            'Keeps all orphaned auto-synced channels. You can clean up manually from the channels page.'}
        </Text>
      </Box>

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

      <Box style={{ maxHeight: '50vh', overflowY: 'auto' }}>
        <SimpleGrid
          cols={{ base: 1, sm: 2, md: 3 }}
          spacing="xs"
          verticalSpacing="xs"
        >
          {groupStates
            .filter((group) => isVisible(group))
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
                          onClick={() =>
                            setConfiguringGroupId(group.channel_group)
                          }
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

                      {renderNumberingRange(group)}
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
        onClose={() => setConfiguringGroupId(null)}
        group={configuringGroup}
        onChange={applyGroupChange}
      >
        {configuringGroup && renderAdvancedOptions(configuringGroup)}
      </GroupConfigureModal>

      {/* Logo Upload Modal */}
      <LogoForm
        isOpen={logoModalOpen}
        onClose={() => {
          setLogoModalOpen(false);
          setCurrentEditingGroupId(null);
        }}
        onSuccess={handleLogoSuccess}
      />
    </Stack>
  );
};

export default LiveGroupFilter;
