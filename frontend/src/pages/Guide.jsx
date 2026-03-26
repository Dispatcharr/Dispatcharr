// frontend/src/pages/Guide.js
import React, {
  useMemo,
  useState,
  useEffect,
  useRef,
  useCallback,
  Suspense,
} from 'react';
import useChannelsStore from '../store/channels';
import useLogosStore from '../store/logos';
import useVideoStore from '../store/useVideoStore';
import useSettingsStore from '../store/settings';
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Flex,
  Group,
  LoadingOverlay,
  Paper,
  Select,
  Text,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core';
import { Clock, Search, X } from 'lucide-react';
import './guide.css';
import useEPGsStore from '../store/epgs';
import { useElementSize } from '@mantine/hooks';
import { VariableSizeList } from 'react-window';
import {
  buildChannelIdMap,
  calculateDesiredScrollPosition,
  calculateEarliestProgramStart,
  calculateEnd,
  calculateHourTimeline,
  calculateLatestProgramEnd,
  calculateLeftScrollPosition,
  calculateNowPosition,
  calculateScrollPosition,
  calculateScrollPositionByTimeClick,
  calculateStart,
  CHANNEL_WIDTH,
  computeRowHeights,
  createRecording,
  createSeriesRule,
  evaluateSeriesRule,
  fetchPrograms,
  fetchRules,
  filterGuideChannels,
  formatSeasonEpisode,
  formatTime,
  getProfileOptions,
  getRuleByProgram,
  HOUR_WIDTH,
  mapProgramsByChannel,
  mapRecordingsByProgramId,
  matchChannelByTvgId,
  MINUTE_BLOCK_WIDTH,
  MINUTE_INCREMENT,
  PROGRAM_GAP_PX,
  PROGRAM_HEIGHT,
  PX_PER_MS,
  calcProgressPct,
  sortChannels,
} from '../utils/guideUtils';
import API from '../api';
import { getShowVideoUrl } from '../utils/cards/RecordingCardUtils.js';
import {
  add,
  convertToMs,
  format,
  getNow,
  initializeTime,
  startOfDay,
  useDateTimeFormat,
} from '../utils/dateTimeUtils.js';
import GuideRow from '../components/GuideRow.jsx';
import HourTimeline from '../components/HourTimeline';
const ProgramRecordingModal = React.lazy(
  () => import('../components/forms/ProgramRecordingModal')
);
const SeriesRecordingModal = React.lazy(
  () => import('../components/forms/SeriesRecordingModal')
);
const ProgramDetailModal = React.lazy(
  () => import('../components/ProgramDetailModal')
);
import { showNotification } from '../utils/notificationUtils.js';
import ErrorBoundary from '../components/ErrorBoundary.jsx';

export default function TVChannelGuide({ startDate, endDate }) {
  const [isChannelsLoading, setIsChannelsLoading] = useState(false);
  const [allowAllGroups, setAllowAllGroups] = useState(true);
  const MAX_ALL_CHANNELS = 99999;

  const recordings = useChannelsStore((s) => s.recordings);
  const channelGroups = useChannelsStore((s) => s.channelGroups);
  const profiles = useChannelsStore((s) => s.profiles);
  const [isProgramsLoading, setIsProgramsLoading] = useState(true);
  const logos = useLogosStore((s) => s.logos);

  const tvgsById = useEPGsStore((s) => s.tvgsById);
  const epgs = useEPGsStore((s) => s.epgs);

  const [programs, setPrograms] = useState([]);
  const [guideChannels, setGuideChannels] = useState([]);
  const [now, setNow] = useState(getNow());
  const [selectedProgram, setSelectedProgram] = useState(null);
  const [selectedChannel, setSelectedChannel] = useState(null);
  const [recordingForProgram, setRecordingForProgram] = useState(null);
  const [recordChoiceOpen, setRecordChoiceOpen] = useState(false);
  const [recordChoiceProgram, setRecordChoiceProgram] = useState(null);
  const [recordChoiceChannel, setRecordChoiceChannel] = useState(null);
  const [existingRuleMode, setExistingRuleMode] = useState(null);
  const [rulesOpen, setRulesOpen] = useState(false);
  const [rules, setRules] = useState([]);
  const [initialScrollComplete, setInitialScrollComplete] = useState(false);

  // New filter states
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedGroupId, setSelectedGroupId] = useState('all');
  const [selectedProfileId, setSelectedProfileId] = useState('all');

  const env_mode = useSettingsStore((s) => s.environment.env_mode);

  const guideRef = useRef(null);
  const timelineRef = useRef(null); // New ref for timeline scrolling
  const listRef = useRef(null);
  const tvGuideRef = useRef(null); // Ref for the main tv-guide wrapper
  const isSyncingScroll = useRef(false);
  const guideScrollLeftRef = useRef(0);
  const nowLineRef = useRef(null);
  const [settledScrollLeft, setSettledScrollLeft] = useState(0);
  const scrollDebounceRef = useRef(null);
  const {
    ref: guideContainerRef,
    width: guideWidth,
    height: guideHeight,
  } = useElementSize();

  // Decide if 'All Channel Groups' should be enabled (based on total channel count)
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const params = new URLSearchParams();
        const ids = await API.getAllChannelIds(params);
        if (cancelled) {
          return;
        }

        const total = Array.isArray(ids)
          ? ids.length
          : (ids?.length ?? ids?.count ?? 0);
        setAllowAllGroups(total <= MAX_ALL_CHANNELS);
      } catch (e) {
        // If we cannot determine, keep current default (true)
        console.error('Failed to get total channel IDs', e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // If 'All' is not allowed, default to the first available group
  useEffect(() => {
    if (!allowAllGroups && selectedGroupId === 'all') {
      const firstGroup = Object.values(channelGroups).find(
        (g) => g?.hasChannels
      );
      if (firstGroup) {
        setSelectedGroupId(String(firstGroup.id));
      }
    }
  }, [allowAllGroups, channelGroups, selectedGroupId]);

  // Fetch channels on demand based on filters
  useEffect(() => {
    let cancelled = false;
    const loadGuideData = async () => {
      try {
        setIsChannelsLoading(true);
        const params = new URLSearchParams();
        // Group filter by name, if not 'all'
        if (selectedGroupId !== 'all') {
          const group = channelGroups[Number(selectedGroupId)];
          if (group?.name) params.set('channel_group', group.name);
        } else if (!allowAllGroups) {
          // If 'all' is not allowed, fall back to first available group
          const firstGroup = Object.values(channelGroups).find(
            (g) => g?.hasChannels
          );
          if (firstGroup?.name) params.set('channel_group', firstGroup.name);
        }

        // Profile filter
        if (selectedProfileId && selectedProfileId !== 'all') {
          params.set('channel_profile_id', String(selectedProfileId));
        }

        // Search filter
        if (searchQuery && searchQuery.trim() !== '') {
          params.set('search', searchQuery.trim());
        }

        // Fetch channels and programs in parallel — programs don't depend
        // on channels so there's no reason to wait for one before the other.
        const [channels, programData] = await Promise.all([
          API.getChannelsSummary(params),
          fetchPrograms(),
        ]);

        if (cancelled) return;

        setGuideChannels(sortChannels(channels || []));
        setPrograms(programData);
      } catch (e) {
        if (cancelled) return;
        console.error('Failed to load guide data:', e);
      } finally {
        if (!cancelled) {
          setIsChannelsLoading(false);
          setIsProgramsLoading(false);
        }
      }
    };

    loadGuideData();
    return () => {
      cancelled = true;
    };
  }, [
    allowAllGroups,
    channelGroups,
    searchQuery,
    selectedGroupId,
    selectedProfileId,
  ]);

  // Apply filters when search, group, or profile changes
  const filteredChannels = useMemo(() => {
    if (!guideChannels.length) return [];

    return filterGuideChannels(
      guideChannels,
      searchQuery,
      selectedGroupId,
      selectedProfileId,
      profiles
    );
  }, [
    searchQuery,
    selectedGroupId,
    selectedProfileId,
    guideChannels,
    profiles,
  ]);

  // Use start/end from props or default to "today at midnight" +24h
  const defaultStart = initializeTime(startDate || startOfDay(getNow()));
  const defaultEnd = endDate
    ? initializeTime(endDate)
    : add(defaultStart, 24, 'hour');

  // Expand timeline if needed based on actual earliest/ latest program
  const earliestProgramStart = useMemo(
    () => calculateEarliestProgramStart(programs, defaultStart),
    [programs, defaultStart]
  );

  const latestProgramEnd = useMemo(
    () => calculateLatestProgramEnd(programs, defaultEnd),
    [programs, defaultEnd]
  );

  const start = calculateStart(earliestProgramStart, defaultStart);
  const end = calculateEnd(latestProgramEnd, defaultEnd);

  // Pre-compute timeline origin in ms for horizontal culling in GuideRow
  const timelineStartMs = useMemo(() => convertToMs(start), [start]);

  const channelIdByTvgId = useMemo(
    () => buildChannelIdMap(guideChannels, tvgsById, epgs),
    [guideChannels, tvgsById, epgs]
  );

  // Local map of channel id -> channel object for quick lookup
  const channelById = useMemo(() => {
    const map = new Map();
    for (const ch of guideChannels) {
      if (ch && ch.id !== undefined && ch.id !== null) {
        map.set(ch.id, ch);
      }
    }
    return map;
  }, [guideChannels]);

  const programsByChannelId = useMemo(
    () => mapProgramsByChannel(programs, channelIdByTvgId),
    [programs, channelIdByTvgId, now]
  );

  const recordingsByProgramId = useMemo(
    () => mapRecordingsByProgramId(recordings),
    [recordings]
  );

  const rowHeights = useMemo(
    () => computeRowHeights(filteredChannels),
    [filteredChannels]
  );

  const getItemSize = useCallback(
    (index) => rowHeights[index] ?? PROGRAM_HEIGHT,
    [rowHeights]
  );

  const { timeFormat, dateFormat } = useDateTimeFormat();

  // Format day label using relative terms when possible (Today, Tomorrow, etc)
  const formatDayLabel = useCallback(
    (time) => formatTime(time, dateFormat),
    [dateFormat]
  );

  // Hourly marks with day labels
  const hourTimeline = useMemo(
    () => calculateHourTimeline(start, end, formatDayLabel),
    [start, end, formatDayLabel]
  );

  useEffect(() => {
    const node = guideRef.current;
    if (!node) return undefined;

    const handleScroll = () => {
      if (isSyncingScroll.current) {
        return;
      }

      const { scrollLeft } = node;

      // Always sync if timeline is out of sync, even if ref matches
      if (
        timelineRef.current &&
        timelineRef.current.scrollLeft !== scrollLeft
      ) {
        isSyncingScroll.current = true;
        timelineRef.current.scrollLeft = scrollLeft;
        guideScrollLeftRef.current = scrollLeft;
        updateNowLine();
        requestAnimationFrame(() => {
          isSyncingScroll.current = false;
        });
      } else if (scrollLeft !== guideScrollLeftRef.current) {
        // Update ref even if timeline was already synced
        guideScrollLeftRef.current = scrollLeft;
        updateNowLine();
      }
    };

    node.addEventListener('scroll', handleScroll, { passive: true });

    return () => {
      node.removeEventListener('scroll', handleScroll);
    };
  }, []);

  // Update "now" every 60 seconds (on a 24h guide, per-second is imperceptible)
  useEffect(() => {
    const interval = setInterval(() => {
      setNow(getNow());
    }, 60000);
    return () => clearInterval(interval);
  }, []);

  // Recover from browser tab throttling — when the user returns to the tab,
  // force-refresh "now" so programs are remapped with current time values.
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (!document.hidden) {
        setNow(getNow());
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () =>
      document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, []);

  // Pixel offset for the "now" vertical line
  const nowPosition = useMemo(
    () => calculateNowPosition(now, start, end),
    [now, start, end]
  );

  // Keep timelineStartMs in a ref for real-time now-line calculation
  const timelineStartMsRef = useRef(timelineStartMs);
  timelineStartMsRef.current = timelineStartMs;

  // Update the now-line DOM element directly (no React re-render)
  // Uses Date.now() for sub-minute precision to stay aligned with progress bars
  const updateNowLine = useCallback(() => {
    if (nowLineRef.current) {
      const nowPx = (Date.now() - timelineStartMsRef.current) * PX_PER_MS;
      nowLineRef.current.style.left = `${Math.round(nowPx + CHANNEL_WIDTH - guideScrollLeftRef.current)}px`;
    }
    // Debounce horizontal culling update — fires 150ms after scrolling stops
    if (scrollDebounceRef.current) {
      clearTimeout(scrollDebounceRef.current);
    }
    scrollDebounceRef.current = setTimeout(() => {
      setSettledScrollLeft(guideScrollLeftRef.current);
    }, 150);
  }, []);

  // Advance now-line and all progress bars every second via direct DOM updates
  // (no React re-renders). Using a single Date.now() per tick keeps everything in sync.
  // Pixel positions are rounded to avoid sub-pixel rendering artifacts (line pulsing).
  // Progress bar scaleX is adjusted to account for the card's gap offset so the
  // fill edge aligns exactly with the now line on the timeline grid.
  useEffect(() => {
    const interval = setInterval(() => {
      const nowMs = Date.now();
      if (nowLineRef.current) {
        const nowPx = (nowMs - timelineStartMsRef.current) * PX_PER_MS;
        nowLineRef.current.style.left = `${Math.round(nowPx + CHANNEL_WIDTH - guideScrollLeftRef.current)}px`;
      }
      document.querySelectorAll('.guide-progress-fill').forEach((el) => {
        const startMs = Number(el.dataset.startMs);
        const endMs = Number(el.dataset.endMs);
        const durationMs = endMs - startMs;
        if (durationMs <= 0) return;
        el.style.transform = `scaleX(${calcProgressPct(nowMs, startMs, durationMs)})`;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  // Clear debounce timeout on unmount
  useEffect(() => {
    return () => {
      if (scrollDebounceRef.current) {
        clearTimeout(scrollDebounceRef.current);
      }
    };
  }, []);

  // Sync now-line whenever nowPosition changes (every 60s)
  useEffect(() => {
    updateNowLine();
  }, [nowPosition, updateNowLine]);

  useEffect(() => {
    const tvGuide = tvGuideRef.current;

    if (!tvGuide) return undefined;

    const handleContainerWheel = (event) => {
      const guide = guideRef.current;
      const timeline = timelineRef.current;

      if (!guide) {
        return;
      }

      if (event.deltaX !== 0 || (event.shiftKey && event.deltaY !== 0)) {
        event.preventDefault();
        event.stopPropagation();

        const delta = event.deltaX !== 0 ? event.deltaX : event.deltaY;
        const newScrollLeft = guide.scrollLeft + delta;

        // Set both guide and timeline scroll positions
        if (typeof guide.scrollTo === 'function') {
          guide.scrollTo({ left: newScrollLeft, behavior: 'auto' });
        } else {
          guide.scrollLeft = newScrollLeft;
        }

        // Also sync timeline immediately
        if (timeline) {
          if (typeof timeline.scrollTo === 'function') {
            timeline.scrollTo({ left: newScrollLeft, behavior: 'auto' });
          } else {
            timeline.scrollLeft = newScrollLeft;
          }
        }

        // Update the ref to keep state in sync
        guideScrollLeftRef.current = newScrollLeft;
        updateNowLine();
      }
    };

    tvGuide.addEventListener('wheel', handleContainerWheel, {
      passive: false,
      capture: true,
    });

    return () => {
      tvGuide.removeEventListener('wheel', handleContainerWheel, {
        capture: true,
      });
    };
  }, []);

  // Fallback: continuously monitor for any scroll changes
  useEffect(() => {
    let rafId = null;
    let lastCheck = 0;

    const checkSync = (timestamp) => {
      // Throttle to check every 100ms instead of every frame
      if (timestamp - lastCheck > 100) {
        const guide = guideRef.current;
        const timeline = timelineRef.current;

        if (guide && timeline && guide.scrollLeft !== timeline.scrollLeft) {
          timeline.scrollLeft = guide.scrollLeft;
          guideScrollLeftRef.current = guide.scrollLeft;
          updateNowLine();
        }
        lastCheck = timestamp;
      }

      rafId = requestAnimationFrame(checkSync);
    };

    rafId = requestAnimationFrame(checkSync);

    return () => {
      if (rafId) cancelAnimationFrame(rafId);
    };
  }, []);

  useEffect(() => {
    const tvGuide = tvGuideRef.current;
    if (!tvGuide) return;

    let lastTouchX = null;
    let isTouching = false;
    let rafId = null;
    let lastScrollLeft = 0;
    let stableFrames = 0;

    const syncScrollPositions = () => {
      const guide = guideRef.current;
      const timeline = timelineRef.current;

      if (!guide || !timeline) return false;

      const currentScroll = guide.scrollLeft;

      // Check if scroll position has changed
      if (currentScroll !== lastScrollLeft) {
        timeline.scrollLeft = currentScroll;
        guideScrollLeftRef.current = currentScroll;
        updateNowLine();
        lastScrollLeft = currentScroll;
        stableFrames = 0;
        return true; // Still scrolling
      } else {
        stableFrames++;
        return stableFrames < 10; // Continue for 10 stable frames to catch late updates
      }
    };

    const startPolling = () => {
      if (rafId) return; // Already polling

      const poll = () => {
        const shouldContinue = isTouching || syncScrollPositions();

        if (shouldContinue) {
          rafId = requestAnimationFrame(poll);
        } else {
          rafId = null;
        }
      };

      rafId = requestAnimationFrame(poll);
    };

    const handleTouchStart = (e) => {
      if (e.touches.length === 1) {
        const guide = guideRef.current;
        if (guide) {
          lastTouchX = e.touches[0].clientX;
          lastScrollLeft = guide.scrollLeft;
          isTouching = true;
          stableFrames = 0;
          startPolling();
        }
      }
    };

    const handleTouchMove = (e) => {
      if (!isTouching || e.touches.length !== 1) return;
      const guide = guideRef.current;
      if (!guide) return;

      const touchX = e.touches[0].clientX;
      const deltaX = lastTouchX - touchX;
      lastTouchX = touchX;

      if (Math.abs(deltaX) > 0) {
        guide.scrollLeft += deltaX;
      }
    };

    const handleTouchEnd = () => {
      isTouching = false;
      lastTouchX = null;
      // Polling continues until scroll stabilizes
    };

    tvGuide.addEventListener('touchstart', handleTouchStart, { passive: true });
    tvGuide.addEventListener('touchmove', handleTouchMove, { passive: false });
    tvGuide.addEventListener('touchend', handleTouchEnd, { passive: true });
    tvGuide.addEventListener('touchcancel', handleTouchEnd, { passive: true });

    return () => {
      if (rafId) cancelAnimationFrame(rafId);
      tvGuide.removeEventListener('touchstart', handleTouchStart);
      tvGuide.removeEventListener('touchmove', handleTouchMove);
      tvGuide.removeEventListener('touchend', handleTouchEnd);
      tvGuide.removeEventListener('touchcancel', handleTouchEnd);
    };
  }, []);

  const syncScrollLeft = useCallback((nextLeft, behavior = 'auto') => {
    const guideNode = guideRef.current;
    const timelineNode = timelineRef.current;

    isSyncingScroll.current = true;

    if (guideNode) {
      if (typeof guideNode.scrollTo === 'function') {
        guideNode.scrollTo({ left: nextLeft, behavior });
      } else {
        guideNode.scrollLeft = nextLeft;
      }
    }

    if (timelineNode) {
      if (typeof timelineNode.scrollTo === 'function') {
        timelineNode.scrollTo({ left: nextLeft, behavior });
      } else {
        timelineNode.scrollLeft = nextLeft;
      }
    }

    guideScrollLeftRef.current = nextLeft;
    updateNowLine();

    requestAnimationFrame(() => {
      isSyncingScroll.current = false;
    });
  }, []);

  // Holds the scroll position to restore after a filter-induced remount.
  // null means "use the default scroll-to-now on first load".
  const savedScrollLeftRef = useRef(null);

  // When channels become empty (filter transition unmounts the list), save the
  // current scroll position so we can restore it once new channels arrive.
  // Only save if the initial scroll has already happened — otherwise the saved
  // position would be 0 (the DOM default) and we'd skip the scroll-to-now.
  useEffect(() => {
    if (filteredChannels.length === 0) {
      if (initialScrollComplete) {
        savedScrollLeftRef.current = guideScrollLeftRef.current;
      }
      setInitialScrollComplete(false);
    }
  }, [filteredChannels.length, initialScrollComplete]);

  // Scroll on initial load, or restore saved position after a filter transition.
  // Guard with guideRef.current — the VariableSizeList outer div is null while
  // unmounted, so we must wait until it remounts before calling syncScrollLeft.
  useEffect(() => {
    if (programs.length > 0 && !initialScrollComplete && guideRef.current) {
      if (savedScrollLeftRef.current !== null) {
        // Restore where the user was before the filter change
        syncScrollLeft(savedScrollLeftRef.current);
        savedScrollLeftRef.current = null;
      } else {
        // Genuine first load — scroll to current time
        syncScrollLeft(calculateScrollPosition(now, start));
      }
      setInitialScrollComplete(true);
    }
  }, [
    programs,
    start,
    now,
    initialScrollComplete,
    syncScrollLeft,
    filteredChannels.length,
  ]);

  const findChannelByTvgId = useCallback(
    (tvgId) => matchChannelByTvgId(channelIdByTvgId, channelById, tvgId),
    [channelById, channelIdByTvgId]
  );

  const openRecordChoice = useCallback(
    async (program, channel) => {
      setRecordChoiceProgram(program);
      setRecordChoiceChannel(channel);
      setRecordChoiceOpen(true);
      try {
        const rules = await fetchRules();
        const rule = getRuleByProgram(rules, program);
        setExistingRuleMode(rule ? rule.mode : null);
      } catch (error) {
        console.warn('Failed to fetch series rules metadata', error);
      }

      setRecordingForProgram(recordingsByProgramId.get(program.id) || null);
    },
    [recordingsByProgramId]
  );

  const recordOne = useCallback(
    async (program, channel) => {
      if (!channel) {
        showNotification({
          title: 'Unable to schedule recording',
          message: 'No channel found for this program.',
          color: 'red.6',
        });
        return;
      }

      await createRecording(channel, program);
      showNotification({ title: 'Recording scheduled' });
    },
    []
  );

  const saveSeriesRule = useCallback(async (program, mode) => {
    await createSeriesRule(program, mode);
    await evaluateSeriesRule(program);
    // recordings_refreshed WS event triggers the debounced fetchRecordings()
    showNotification({
      title: mode === 'new' ? 'Record new episodes' : 'Record all episodes',
    });
  }, []);

  const openRules = useCallback(async () => {
    setRulesOpen(true);
    try {
      const r = await fetchRules();
      setRules(r);
    } catch (error) {
      console.warn('Failed to load series rules', error);
    }
  }, []);

  const showVideo = useVideoStore((s) => s.showVideo);

  const handleLogoClick = useCallback(
    (channel, event) => {
      event.stopPropagation();

      showVideo(getShowVideoUrl(channel, env_mode), 'live', {
        name: channel.name,
      });
    },
    [env_mode, showVideo]
  );

  const handleProgramClick = useCallback(
    (program, channel, event) => {
      event.stopPropagation();
      setSelectedProgram(program);
      setSelectedChannel(channel || findChannelByTvgId(program.tvg_id));
      setRecordingForProgram(recordingsByProgramId.get(program.id) || null);
    },
    [findChannelByTvgId, recordingsByProgramId]
  );

  const handleCloseModal = useCallback(() => {
    setSelectedProgram(null);
    setSelectedChannel(null);
    setRecordingForProgram(null);
  }, []);

  const scrollToNow = useCallback(() => {
    if (nowPosition < 0) {
      return;
    }

    syncScrollLeft(calculateScrollPosition(now, start), 'smooth');
  }, [now, nowPosition, start, syncScrollLeft]);

  const handleTimelineScroll = useCallback(() => {
    if (!timelineRef.current || isSyncingScroll.current) {
      return;
    }

    const nextLeft = timelineRef.current.scrollLeft;
    if (nextLeft === guideScrollLeftRef.current) {
      return;
    }

    guideScrollLeftRef.current = nextLeft;
    updateNowLine();

    isSyncingScroll.current = true;
    if (guideRef.current) {
      if (typeof guideRef.current.scrollTo === 'function') {
        guideRef.current.scrollTo({ left: nextLeft });
      } else {
        guideRef.current.scrollLeft = nextLeft;
      }
    }

    requestAnimationFrame(() => {
      isSyncingScroll.current = false;
    });
  }, []);

  const handleTimelineWheel = useCallback((event) => {
    if (!timelineRef.current) {
      return;
    }

    event.preventDefault();
    const scrollAmount = event.shiftKey ? 250 : 125;
    const delta = event.deltaY > 0 ? scrollAmount : -scrollAmount;
    timelineRef.current.scrollBy({ left: delta, behavior: 'smooth' });
  }, []);

  const handleTimeClick = useCallback(
    (clickedTime, event) => {
      syncScrollLeft(
        calculateScrollPositionByTimeClick(event, clickedTime, start),
        'smooth'
      );
    },
    [start, syncScrollLeft]
  );
  const renderProgram = useCallback(
    (program, channelStart = start, channel = null) => {
      const {
        programStart,
        programEnd,
        startMs: programStartMs,
        endMs: programEndMs,
        isLive,
        isPast,
      } = program;

      const startOffsetMinutes =
        (programStartMs - convertToMs(channelStart)) / 60000;
      const durationMinutes = (programEndMs - programStartMs) / 60000;
      const leftPx =
        (startOffsetMinutes / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH;

      const widthPx =
        (durationMinutes / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH -
        PROGRAM_GAP_PX * 2;

      const recording = recordingsByProgramId.get(program.id);

      const programStartInView = leftPx + PROGRAM_GAP_PX;
      const programEndInView = leftPx + PROGRAM_GAP_PX + widthPx;
      const viewportLeft = guideScrollLeftRef.current;
      const startsBeforeView = programStartInView < viewportLeft;
      const extendsIntoView = programEndInView > viewportLeft;

      let textOffsetLeft = 0;
      if (startsBeforeView && extendsIntoView) {
        const visibleStart = Math.max(viewportLeft - programStartInView, 0);
        const maxOffset = widthPx - 200;
        textOffsetLeft = Math.min(visibleStart, maxOffset);
      }

      const seasonEpisodeLabel = formatSeasonEpisode(
        program.season,
        program.episode
      );
      return (
        <Box
          className="guide-program-container"
          key={`${channel?.id || 'unknown'}-${program.id || `${program.tvg_id}-${program.start_time}`}`}
          style={{ cursor: 'pointer', zIndex: 5 }}
          pos="absolute"
          left={leftPx + PROGRAM_GAP_PX}
          top={0}
          w={widthPx}
          h={PROGRAM_HEIGHT - 4}
          onClick={(event) => handleProgramClick(program, channel, event)}
        >
          <Paper
            elevation={2}
            className={`guide-program ${isLive ? 'live' : isPast ? 'past' : 'not-live'}`}
            style={{
              overflow: 'hidden',
              flexDirection: 'column',
              justifyContent: 'flex-start',
              backgroundColor: isLive
                ? '#18181B'
                : isPast
                  ? '#27272A'
                  : '#2c5282',
            }}
            w={'100%'}
            h={'100%'}
            pos="relative"
            display={'flex'}
            p={8}
            c={isPast ? '#a0aec0' : '#fff'}
          >
            <Box
              style={{
                transform: `translateX(${textOffsetLeft}px)`,
                transition: 'transform 0.1s ease-out',
                display: 'flex',
                flexDirection: 'column',
                justifyContent:
                  program.sub_title || program.description
                    ? 'space-between'
                    : 'flex-start',
                flex: '1 1 0',
                minHeight: 0,
                overflow: 'hidden',
              }}
            >
              {/* Row 1: Title with recording indicator */}
              <Text
                component="div"
                size="md"
                style={{
                  whiteSpace: 'nowrap',
                  textOverflow: 'ellipsis',
                  overflow: 'hidden',
                }}
                fw={'bold'}
              >
                <Group gap="xs" wrap="nowrap">
                  {recording && (
                    <div
                      style={{
                        borderRadius: '50%',
                        width: '10px',
                        height: '10px',
                        display: 'flex',
                        flexShrink: 0,
                        backgroundColor: 'red',
                      }}
                    ></div>
                  )}
                  {program.title}
                </Group>
              </Text>

              {/* Row 2: S/E badge + Subtitle or description fallback */}
              {(seasonEpisodeLabel ||
                program.sub_title ||
                program.description) && (
                <Group
                  gap={4}
                  wrap="nowrap"
                  style={{ overflow: 'hidden', minWidth: 0 }}
                >
                  {seasonEpisodeLabel && (
                    <Badge
                      size="xs"
                      variant="light"
                      color="cyan"
                      styles={{
                        root: {
                          backgroundColor: 'rgba(20,90,110,0.55)',
                          flexShrink: 0,
                        },
                      }}
                    >
                      {seasonEpisodeLabel}
                    </Badge>
                  )}
                  {(program.sub_title || program.description) && (
                    <Text
                      size="xs"
                      fs={program.sub_title ? 'italic' : 'normal'}
                      style={{
                        whiteSpace: 'nowrap',
                        textOverflow: 'ellipsis',
                        overflow: 'hidden',
                        minWidth: 0,
                      }}
                      c={isPast ? '#718096' : '#e2e8f0'}
                    >
                      {program.sub_title || program.description}
                    </Text>
                  )}
                </Group>
              )}

              {/* Row 3: Time + LIVE/NEW badges */}
              <Group gap={4} wrap="nowrap" style={{ overflow: 'hidden' }}>
                <Text
                  size="sm"
                  style={{
                    whiteSpace: 'nowrap',
                    flexShrink: 0,
                  }}
                >
                  {format(programStart, timeFormat)} -{' '}
                  {format(programEnd, timeFormat)}
                </Text>
                {program.is_live && (
                  <Badge
                    size="xs"
                    variant="light"
                    color="red"
                    styles={{
                      root: {
                        backgroundColor: 'rgba(120,20,20,0.55)',
                        flexShrink: 0,
                      },
                    }}
                  >
                    LIVE
                  </Badge>
                )}
                {program.is_new && (
                  <Badge
                    size="xs"
                    variant="light"
                    color="green"
                    styles={{
                      root: {
                        backgroundColor: 'rgba(20,100,20,0.55)',
                        flexShrink: 0,
                      },
                    }}
                  >
                    NEW
                  </Badge>
                )}
              </Group>
            </Box>

            {/* Progress bar for currently-airing programs — updated every second via DOM */}
            {isLive &&
              (() => {
                const durationMs = programEndMs - programStartMs;
                if (durationMs <= 0) return null;
                const initialPct = calcProgressPct(
                  Date.now(),
                  programStartMs,
                  durationMs
                );
                return (
                  <Box
                    pos="absolute"
                    bottom={0}
                    left={0}
                    right={0}
                    h={4}
                    style={{
                      backgroundColor: 'rgba(255, 255, 255, 0.1)',
                      borderRadius: '0 0 8px 8px',
                      overflow: 'hidden',
                    }}
                  >
                    <Box
                      className="guide-progress-fill"
                      data-start-ms={programStartMs}
                      data-end-ms={programEndMs}
                      h="100%"
                      style={{
                        width: '100%',
                        backgroundColor: 'rgba(255, 255, 255, 0.5)',
                        borderRadius: '0 0 0 8px',
                        transformOrigin: 'left',
                        transform: `scaleX(${initialPct})`,
                      }}
                    />
                  </Box>
                );
              })()}
          </Paper>
        </Box>
      );
    },
    [handleProgramClick, recordingsByProgramId, start, timeFormat]
  );

  const contentWidth = useMemo(
    () => hourTimeline.length * HOUR_WIDTH + CHANNEL_WIDTH,
    [hourTimeline]
  );

  const virtualizedHeight = useMemo(() => guideHeight || 600, [guideHeight]);

  const virtualizedWidth = useMemo(() => {
    if (guideWidth) {
      return guideWidth;
    }
    if (typeof window !== 'undefined') {
      return Math.min(window.innerWidth, contentWidth);
    }
    return contentWidth;
  }, [guideWidth, contentWidth]);

  const itemKey = useCallback(
    (index) => filteredChannels[index]?.id ?? index,
    [filteredChannels]
  );

  const listData = useMemo(
    () => ({
      filteredChannels,
      programsByChannelId,
      rowHeights,
      logos,
      renderProgram,
      handleLogoClick,
      contentWidth,
      guideScrollLeftRef,
      viewportWidth:
        guideWidth ||
        (typeof window !== 'undefined' ? window.innerWidth : 1200),
      timelineStartMs,
      settledScrollLeft, // triggers row re-renders after scrolling stops
    }),
    [
      filteredChannels,
      programsByChannelId,
      rowHeights,
      logos,
      renderProgram,
      handleLogoClick,
      contentWidth,
      guideWidth,
      timelineStartMs,
      settledScrollLeft,
    ]
  );

  useEffect(() => {
    if (listRef.current) {
      listRef.current.resetAfterIndex(0, true);
    }
  }, [rowHeights]);

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollToItem(0);
    }
  }, [searchQuery, selectedGroupId, selectedProfileId]);

  // Group options: show all groups; gate 'All' if too many channels
  const groupOptions = useMemo(() => {
    const opts = [];
    if (allowAllGroups) {
      opts.push({ value: 'all', label: 'All Channel Groups' });
    }
    const groupsArr = Object.values(channelGroups)
      .filter((g) => g?.hasChannels)
      .sort((a, b) => (a?.name || '').localeCompare(b?.name || ''));
    groupsArr.forEach((g) => {
      opts.push({ value: String(g.id), label: g.name });
    });
    return opts;
  }, [channelGroups, allowAllGroups]);

  // Create profile options for dropdown
  const profileOptions = useMemo(() => getProfileOptions(profiles), [profiles]);

  // Clear all filters
  const clearFilters = () => {
    setSearchQuery('');
    setSelectedGroupId('all');
    setSelectedProfileId('all');
  };

  // Handle group selection changes, ensuring null becomes 'all'
  const handleGroupChange = (value) => {
    setSelectedGroupId(value || 'all');
  };

  // Handle profile selection changes, ensuring null becomes 'all'
  const handleProfileChange = (value) => {
    setSelectedProfileId(value || 'all');
  };

  const handleClearSearchQuery = () => {
    setSearchQuery('');
  };
  const handleChangeSearchQuery = (e) => {
    setSearchQuery(e.target.value);
  };

  return (
    <Box
      ref={tvGuideRef}
      className="tv-guide"
      style={{
        overflow: 'hidden',
      }}
      w={'100%'}
      h={'100%'}
      c="#ffffff"
      ff={'Roboto, sans-serif'}
    >
      {/* Sticky top bar */}
      <Flex
        direction="column"
        style={{
          zIndex: 1000,
          position: 'sticky',
        }}
        c="#ffffff"
        p={'12px 20px'}
        top={0}
      >
        {/* Title and current time */}
        <Flex justify="space-between" align="center" mb={12}>
          <Title order={3} fw={'bold'}>
            TV Guide
          </Title>
          <Flex align="center" gap="md">
            <Text>
              {format(now, `dddd, ${dateFormat}, YYYY • ${timeFormat}`)}
            </Text>
            <Tooltip label="Jump to current time">
              <ActionIcon
                onClick={scrollToNow}
                variant="filled"
                size="md"
                radius="xl"
                color="teal"
              >
                <Clock size={16} />
              </ActionIcon>
            </Tooltip>
          </Flex>
        </Flex>

        {/* Filter controls */}
        <Flex gap="md" align="center">
          <TextInput
            placeholder="Search channels..."
            value={searchQuery}
            onChange={handleChangeSearchQuery}
            w={'250px'} // Reduced width from flex: 1
            leftSection={<Search size={16} />}
            rightSection={
              searchQuery ? (
                <ActionIcon
                  onClick={handleClearSearchQuery}
                  variant="subtle"
                  color="gray"
                  size="sm"
                >
                  <X size={14} />
                </ActionIcon>
              ) : null
            }
          />

          <Select
            placeholder="Filter by group"
            data={groupOptions}
            value={selectedGroupId}
            onChange={handleGroupChange} // Use the new handler
            w={'220px'}
            clearable={allowAllGroups} // Allow clearing the selection
          />

          <Select
            placeholder="Filter by profile"
            data={profileOptions}
            value={selectedProfileId}
            onChange={handleProfileChange} // Use the new handler
            w={'180px'}
            clearable={true} // Allow clearing the selection
          />

          {(searchQuery !== '' ||
            selectedGroupId !== 'all' ||
            selectedProfileId !== 'all') && (
            <Button variant="subtle" onClick={clearFilters} size="sm">
              Clear Filters
            </Button>
          )}

          <Button
            variant="filled"
            size="sm"
            onClick={openRules}
            style={{
              backgroundColor: '#245043',
            }}
            bd={'1px solid #3BA882'}
            color="#FFFFFF"
          >
            Series Rules
          </Button>

          <Text size="sm" c="dimmed">
            {filteredChannels.length}{' '}
            {filteredChannels.length === 1 ? 'channel' : 'channels'}
          </Text>
        </Flex>
      </Flex>

      {/* Guide container with headers and scrollable content */}
      <Box
        style={{
          flexDirection: 'column',
        }}
        display={'flex'}
        h={'calc(100vh - 120px)'}
      >
        {/* Logo header - Sticky, non-scrollable */}
        <Box
          style={{
            zIndex: 100,
            position: 'sticky',
          }}
          display={'flex'}
          top={0}
        >
          {/* Logo header cell - sticky in both directions */}
          <Box
            style={{
              flexShrink: 0,
              backgroundColor: '#18181B',
              borderBottom: '1px solid #27272A',
              borderRight: '1px solid #27272A', // Increased border width
              zIndex: 200,
            }}
            w={CHANNEL_WIDTH}
            miw={CHANNEL_WIDTH}
            h={'40px'}
            pos="sticky"
            left={0}
          />

          {/* Timeline header with its own scrollbar */}
          <Box
            style={{
              flex: 1,
              overflow: 'hidden',
            }}
            pos="relative"
          >
            <Box
              ref={timelineRef}
              style={{
                overflowX: 'auto',
                overflowY: 'hidden',
              }}
              pos="relative"
              onScroll={handleTimelineScroll}
              onWheel={handleTimelineWheel} // Add wheel event handler
            >
              <Box
                style={{
                  backgroundColor: '#1E2A27',
                  borderBottom: '1px solid #27272A',
                }}
                display={'flex'}
                w={hourTimeline.length * HOUR_WIDTH}
                pos="relative"
              >
                <HourTimeline
                  hourTimeline={hourTimeline}
                  timeFormat={timeFormat}
                  formatDayLabel={formatDayLabel}
                  handleTimeClick={handleTimeClick}
                />
              </Box>
            </Box>
          </Box>
        </Box>

        {/* Main scrollable container for program content */}
        <Box
          ref={guideContainerRef}
          style={{
            flex: 1,
            overflow: 'hidden',
          }}
          pos="relative"
        >
          <LoadingOverlay visible={isProgramsLoading || isChannelsLoading} />
          {nowPosition >= 0 && (
            <Box
              ref={nowLineRef}
              style={{
                backgroundColor: '#38b2ac',
                zIndex: 15,
                pointerEvents: 'none',
                left: `${((Date.now() - timelineStartMs) / 60000 / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH + CHANNEL_WIDTH - guideScrollLeftRef.current}px`,
              }}
              pos="absolute"
              top={0}
              bottom={0}
              w={'2px'}
            >
              {/* Now-marker triangle at top of line */}
              <Box
                pos="absolute"
                top={-1}
                style={{
                  transform: 'translateX(-6px)',
                  width: 0,
                  height: 0,
                  borderLeft: '7px solid transparent',
                  borderRight: '7px solid transparent',
                  borderTop: '9px solid #38b2ac',
                  filter: 'drop-shadow(0 1px 3px rgba(56, 178, 172, 0.5))',
                }}
              />
            </Box>
          )}

          {filteredChannels.length > 0 ? (
            <VariableSizeList
              className="guide-list-outer"
              height={virtualizedHeight}
              width={virtualizedWidth}
              itemCount={filteredChannels.length}
              itemSize={getItemSize}
              estimatedItemSize={PROGRAM_HEIGHT}
              itemKey={itemKey}
              itemData={listData}
              ref={listRef}
              outerRef={guideRef}
              overscanCount={3}
            >
              {GuideRow}
            </VariableSizeList>
          ) : (
            <Box p={'30px'} ta="center" color="#a0aec0">
              <Text size="lg">No channels match your filters</Text>
              <Button variant="subtle" onClick={clearFilters} mt={10}>
                Clear Filters
              </Button>
            </Box>
          )}
        </Box>
      </Box>

      {/* Record choice modal */}
      {recordChoiceOpen && recordChoiceProgram && (
        <ErrorBoundary>
          <Suspense fallback={<LoadingOverlay />}>
            <ProgramRecordingModal
              opened={recordChoiceOpen}
              onClose={() => setRecordChoiceOpen(false)}
              program={recordChoiceProgram}
              recording={recordingForProgram}
              existingRuleMode={existingRuleMode}
              onRecordOne={() => recordOne(recordChoiceProgram, recordChoiceChannel)}
              onRecordSeriesAll={() =>
                saveSeriesRule(recordChoiceProgram, 'all')
              }
              onRecordSeriesNew={() =>
                saveSeriesRule(recordChoiceProgram, 'new')
              }
              onExistingRuleModeChange={setExistingRuleMode}
            />
          </Suspense>
        </ErrorBoundary>
      )}

      {/* Series rules modal */}
      {rulesOpen && (
        <ErrorBoundary>
          <Suspense fallback={<LoadingOverlay />}>
            <SeriesRecordingModal
              opened={rulesOpen}
              onClose={() => setRulesOpen(false)}
              rules={rules}
              onRulesUpdate={setRules}
            />
          </Suspense>
        </ErrorBoundary>
      )}

      {/* Program detail modal */}
      {selectedProgram && (
        <ErrorBoundary>
          <Suspense fallback={<LoadingOverlay />}>
            <ProgramDetailModal
              program={selectedProgram}
              channel={selectedChannel}
              recording={recordingForProgram}
              opened={!!selectedProgram}
              onClose={handleCloseModal}
              onRecord={(program) => openRecordChoice(program, selectedChannel)}
            />
          </Suspense>
        </ErrorBoundary>
      )}
    </Box>
  );
}
