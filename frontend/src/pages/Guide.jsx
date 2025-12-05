// frontend/src/pages/Guide.js
import React, {
  useMemo,
  useState,
  useEffect,
  useRef,
  useCallback,
} from 'react';
import dayjs from 'dayjs';
import API from '../api';
import useChannelsStore from '../store/channels';
import useLogosStore from '../store/logos';
import logo from '../images/logo.png';
import useVideoStore from '../store/useVideoStore'; // NEW import
import { notifications } from '@mantine/notifications';
import useSettingsStore from '../store/settings';
import {
  Title,
  Box,
  Flex,
  Button,
  Text,
  Paper,
  Group,
  TextInput,
  Select,
  ActionIcon,
  Tooltip,
  Transition,
  Modal,
  Stack,
} from '@mantine/core';
import { Search, X, Clock, Video, Calendar, Play } from 'lucide-react';
import './guide.css';
import useEPGsStore from '../store/epgs';
import useLocalStorage from '../hooks/useLocalStorage';
import { useElementSize } from '@mantine/hooks';
import { VariableSizeList } from 'react-window';
import {
  PROGRAM_HEIGHT,
  EXPANDED_PROGRAM_HEIGHT,
  buildChannelIdMap,
  mapProgramsByChannel,
  computeRowHeights,
} from './guideUtils';

/** Layout constants */
const CHANNEL_WIDTH = 120; // Width of the channel/logo column
const HOUR_WIDTH = 450; // Increased from 300 to 450 to make each program wider
const MINUTE_INCREMENT = 15; // For positioning programs every 15 min
const MINUTE_BLOCK_WIDTH = HOUR_WIDTH / (60 / MINUTE_INCREMENT);

const GuideRow = React.memo(({ index, style, data }) => {
  const {
    filteredChannels,
    programsByChannelId,
    expandedProgramId,
    rowHeights,
    logos,
    hoveredChannelId,
    setHoveredChannelId,
    renderProgram,
    handleLogoClick,
    contentWidth,
  } = data;

  const channel = filteredChannels[index];
  if (!channel) {
    return null;
  }

  const channelPrograms = programsByChannelId.get(channel.id) || [];
  const rowHeight =
    rowHeights[index] ??
    (channelPrograms.some((program) => program.id === expandedProgramId)
      ? EXPANDED_PROGRAM_HEIGHT
      : PROGRAM_HEIGHT);

  return (
    <div
      data-testid="guide-row"
      style={{ ...style, width: contentWidth, height: rowHeight }}
    >
      <Box
        style={{
          display: 'flex',
          height: '100%',
          borderBottom: '0px solid #27272A',
          transition: 'height 0.2s ease',
          position: 'relative',
          overflow: 'visible',
        }}
      >
        <Box
          className="channel-logo"
          style={{
            width: CHANNEL_WIDTH,
            minWidth: CHANNEL_WIDTH,
            flexShrink: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: '#18181B',
            borderRight: '1px solid #27272A',
            borderBottom: '1px solid #27272A',
            boxShadow: '2px 0 5px rgba(0,0,0,0.2)',
            left: 0,
            zIndex: 30,
            height: '100%',
            transition: 'height 0.2s ease',
            cursor: 'pointer',
            position: 'relative',
          }}
          onClick={(event) => handleLogoClick(channel, event)}
          onMouseEnter={() => setHoveredChannelId(channel.id)}
          onMouseLeave={() => setHoveredChannelId(null)}
        >
          {hoveredChannelId === channel.id && (
            <Flex
              align="center"
              justify="center"
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                right: 0,
                bottom: 0,
                width: '100%',
                height: '100%',
                backgroundColor: 'rgba(0, 0, 0, 0.7)',
                zIndex: 10,
                animation: 'fadeIn 0.2s',
              }}
            >
              <Play size={32} color="#fff" fill="#fff" />
            </Flex>
          )}

          <Flex
            direction="column"
            align="center"
            justify="space-between"
            style={{
              width: '100%',
              height: '100%',
              padding: '4px',
              boxSizing: 'border-box',
              zIndex: 5,
              position: 'relative',
            }}
          >
            <Box
              style={{
                width: '100%',
                height: `${rowHeight - 32}px`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                overflow: 'hidden',
                padding: '4px',
                marginBottom: '4px',
              }}
            >
              <img
                src={logos[channel.logo_id]?.cache_url || logo}
                alt={channel.name}
                style={{
                  maxWidth: '100%',
                  maxHeight: '100%',
                  objectFit: 'contain',
                }}
              />
            </Box>

            <Text
              size="sm"
              weight={600}
              style={{
                position: 'absolute',
                bottom: '4px',
                left: '50%',
                transform: 'translateX(-50%)',
                backgroundColor: '#18181B',
                padding: '2px 8px',
                borderRadius: 4,
                fontSize: '0.85em',
                border: '1px solid #27272A',
                height: '24px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                minWidth: '36px',
              }}
            >
              {channel.channel_number || '-'}
            </Text>
          </Flex>
        </Box>

        <Box
          style={{
            flex: 1,
            position: 'relative',
            height: '100%',
            transition: 'height 0.2s ease',
            paddingLeft: 0,
          }}
        >
          {channelPrograms.length > 0 ? (
            channelPrograms.map((program) =>
              renderProgram(program, undefined, channel)
            )
          ) : (
            <>
              {Array.from({ length: Math.ceil(24 / 2) }).map(
                (_, placeholderIndex) => (
                  <Box
                    key={`placeholder-${channel.id}-${placeholderIndex}`}
                    style={{
                      position: 'absolute',
                      left: placeholderIndex * (HOUR_WIDTH * 2),
                      top: 0,
                      width: HOUR_WIDTH * 2,
                      height: rowHeight - 4,
                      border: '1px dashed #2D3748',
                      borderRadius: '4px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: '#4A5568',
                    }}
                  >
                    <Text size="sm">No program data</Text>
                  </Box>
                )
              )}
            </>
          )}
        </Box>
      </Box>
    </div>
  );
});

export default function TVChannelGuide({ startDate, endDate }) {
  const channels = useChannelsStore((s) => s.channels);
  const recordings = useChannelsStore((s) => s.recordings);
  const channelGroups = useChannelsStore((s) => s.channelGroups);
  const profiles = useChannelsStore((s) => s.profiles);
  const logos = useLogosStore((s) => s.logos);

  const tvgsById = useEPGsStore((s) => s.tvgsById);
  const epgs = useEPGsStore((s) => s.epgs);

  const [programs, setPrograms] = useState([]);
  const [guideChannels, setGuideChannels] = useState([]);
  const [filteredChannels, setFilteredChannels] = useState([]);
  const [now, setNow] = useState(dayjs());
  const [expandedProgramId, setExpandedProgramId] = useState(null); // Track expanded program
  const [recordingForProgram, setRecordingForProgram] = useState(null);
  const [recordChoiceOpen, setRecordChoiceOpen] = useState(false);
  const [recordChoiceProgram, setRecordChoiceProgram] = useState(null);
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
  const {
    ref: guideContainerRef,
    width: guideWidth,
    height: guideHeight,
  } = useElementSize();
  const [guideScrollLeft, setGuideScrollLeft] = useState(0);

  // Add new state to track hovered logo
  const [hoveredChannelId, setHoveredChannelId] = useState(null);

  // Load program data once
  useEffect(() => {
    if (!Object.keys(channels).length === 0) {
      console.warn('No channels provided or empty channels array');
      notifications.show({ title: 'No channels available', color: 'red.5' });
      return;
    }

    const fetchPrograms = async () => {
      console.log('Fetching program grid...');
      const fetched = await API.getGrid(); // GETs your EPG grid
      console.log(`Received ${fetched.length} programs`);

      // Include ALL channels, sorted by channel number - don't filter by EPG data
      const sortedChannels = Object.values(channels).sort(
        (a, b) =>
          (a.channel_number || Infinity) - (b.channel_number || Infinity)
      );

      console.log(`Using all ${sortedChannels.length} available channels`);

      const processedPrograms = fetched.map((program) => {
        const start = dayjs(program.start_time);
        const end = dayjs(program.end_time);
        return {
          ...program,
          startMs: start.valueOf(),
          endMs: end.valueOf(),
        };
      });

      setGuideChannels(sortedChannels);
      setFilteredChannels(sortedChannels); // Initialize filtered channels
      setPrograms(processedPrograms);
    };

    fetchPrograms();
  }, [channels]);

  // Apply filters when search, group, or profile changes
  useEffect(() => {
    if (!guideChannels.length) return;

    let result = [...guideChannels];

    // Apply search filter
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      result = result.filter((channel) =>
        channel.name.toLowerCase().includes(query)
      );
    }

    // Apply channel group filter
    if (selectedGroupId !== 'all') {
      result = result.filter(
        (channel) => channel.channel_group_id === parseInt(selectedGroupId)
      );
    }

    // Apply profile filter
    if (selectedProfileId !== 'all') {
      // Get the profile's enabled channels
      const profileChannels = profiles[selectedProfileId]?.channels || [];
      // Check if channels is a Set (from the error message, it likely is)
      const enabledChannelIds = Array.isArray(profileChannels)
        ? profileChannels.filter((pc) => pc.enabled).map((pc) => pc.id)
        : profiles[selectedProfileId]?.channels instanceof Set
          ? Array.from(profiles[selectedProfileId].channels)
          : [];

      result = result.filter((channel) =>
        enabledChannelIds.includes(channel.id)
      );
    }

    setFilteredChannels(result);
  }, [
    searchQuery,
    selectedGroupId,
    selectedProfileId,
    guideChannels,
    profiles,
  ]);

  // Use start/end from props or default to "today at midnight" +24h
  const defaultStart = dayjs(startDate || dayjs().startOf('day'));
  const defaultEnd = endDate ? dayjs(endDate) : defaultStart.add(24, 'hour');

  // Expand timeline if needed based on actual earliest/ latest program
  const earliestProgramStart = useMemo(() => {
    if (!programs.length) return defaultStart;
    return programs.reduce((acc, p) => {
      const s = dayjs(p.start_time);
      return s.isBefore(acc) ? s : acc;
    }, defaultStart);
  }, [programs, defaultStart]);

  const latestProgramEnd = useMemo(() => {
    if (!programs.length) return defaultEnd;
    return programs.reduce((acc, p) => {
      const e = dayjs(p.end_time);
      return e.isAfter(acc) ? e : acc;
    }, defaultEnd);
  }, [programs, defaultEnd]);

  const start = earliestProgramStart.isBefore(defaultStart)
    ? earliestProgramStart
    : defaultStart;
  const end = latestProgramEnd.isAfter(defaultEnd)
    ? latestProgramEnd
    : defaultEnd;

  const channelIdByTvgId = useMemo(
    () => buildChannelIdMap(guideChannels, tvgsById, epgs),
    [guideChannels, tvgsById, epgs]
  );

  const channelById = useMemo(() => {
    const map = new Map();
    guideChannels.forEach((channel) => {
      map.set(channel.id, channel);
    });
    return map;
  }, [guideChannels]);

  const programsByChannelId = useMemo(
    () => mapProgramsByChannel(programs, channelIdByTvgId),
    [programs, channelIdByTvgId]
  );

  const recordingsByProgramId = useMemo(() => {
    const map = new Map();
    (recordings || []).forEach((recording) => {
      const programId = recording?.custom_properties?.program?.id;
      if (programId != null) {
        map.set(programId, recording);
      }
    });
    return map;
  }, [recordings]);

  const rowHeights = useMemo(
    () =>
      computeRowHeights(
        filteredChannels,
        programsByChannelId,
        expandedProgramId
      ),
    [filteredChannels, programsByChannelId, expandedProgramId]
  );

  const getItemSize = useCallback(
    (index) => rowHeights[index] ?? PROGRAM_HEIGHT,
    [rowHeights]
  );

  const [timeFormatSetting] = useLocalStorage('time-format', '12h');
  const [dateFormatSetting] = useLocalStorage('date-format', 'mdy');
  // Use user preference for time format
  const timeFormat = timeFormatSetting === '12h' ? 'h:mm A' : 'HH:mm';
  const dateFormat = dateFormatSetting === 'mdy' ? 'MMMM D' : 'D MMMM';

  // Format day label using relative terms when possible (Today, Tomorrow, etc)
  const formatDayLabel = useCallback(
    (time) => {
      const today = dayjs().startOf('day');
      const tomorrow = today.add(1, 'day');
      const weekLater = today.add(7, 'day');

      const day = time.startOf('day');

      if (day.isSame(today, 'day')) {
        return 'Today';
      } else if (day.isSame(tomorrow, 'day')) {
        return 'Tomorrow';
      } else if (day.isBefore(weekLater)) {
        // Within a week, show day name
        return time.format('dddd');
      } else {
        // Beyond a week, show month and day
        return time.format(dateFormat);
      }
    },
    [dateFormat]
  );

  // Hourly marks with day labels
  const hourTimeline = useMemo(() => {
    const hours = [];
    let current = start;
    let currentDay = null;

    while (current.isBefore(end)) {
      // Check if we're entering a new day
      const day = current.startOf('day');
      const isNewDay = !currentDay || !day.isSame(currentDay, 'day');

      if (isNewDay) {
        currentDay = day;
      }

      // Add day information to our hour object
      hours.push({
        time: current,
        isNewDay,
        dayLabel: formatDayLabel(current),
      });

      current = current.add(1, 'hour');
    }
    return hours;
  }, [start, end, formatDayLabel]);

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
        setGuideScrollLeft(scrollLeft);
        requestAnimationFrame(() => {
          isSyncingScroll.current = false;
        });
      } else if (scrollLeft !== guideScrollLeftRef.current) {
        // Update ref even if timeline was already synced
        guideScrollLeftRef.current = scrollLeft;
        setGuideScrollLeft(scrollLeft);
      }
    };

    node.addEventListener('scroll', handleScroll, { passive: true });

    return () => {
      node.removeEventListener('scroll', handleScroll);
    };
  }, []);

  // Update "now" every second
  useEffect(() => {
    const interval = setInterval(() => {
      setNow(dayjs());
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  // Pixel offset for the "now" vertical line
  const nowPosition = useMemo(() => {
    if (now.isBefore(start) || now.isAfter(end)) return -1;
    const minutesSinceStart = now.diff(start, 'minute');
    return (minutesSinceStart / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH;
  }, [now, start, end]);

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
        setGuideScrollLeft(newScrollLeft);
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
          setGuideScrollLeft(guide.scrollLeft);
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
        setGuideScrollLeft(currentScroll);
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
    setGuideScrollLeft(nextLeft);

    requestAnimationFrame(() => {
      isSyncingScroll.current = false;
    });
  }, []);

  // Scroll to the nearest half-hour mark ONLY on initial load
  useEffect(() => {
    if (programs.length > 0 && !initialScrollComplete) {
      const roundedNow =
        now.minute() < 30
          ? now.startOf('hour')
          : now.startOf('hour').add(30, 'minute');
      const nowOffset = roundedNow.diff(start, 'minute');
      const scrollPosition =
        (nowOffset / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH -
        MINUTE_BLOCK_WIDTH;

      const scrollPos = Math.max(scrollPosition, 0);
      syncScrollLeft(scrollPos);

      setInitialScrollComplete(true);
    }
  }, [programs, start, now, initialScrollComplete, syncScrollLeft]);

  const findChannelByTvgId = useCallback(
    (tvgId) => {
      const channelIds = channelIdByTvgId.get(String(tvgId));
      if (!channelIds || channelIds.length === 0) {
        return null;
      }
      // Return the first channel that matches this TVG ID
      return channelById.get(channelIds[0]) || null;
    },
    [channelById, channelIdByTvgId]
  );

  const openRecordChoice = useCallback(
    async (program) => {
      setRecordChoiceProgram(program);
      setRecordChoiceOpen(true);
      try {
        const rules = await API.listSeriesRules();
        const rule = (rules || []).find(
          (r) =>
            String(r.tvg_id) === String(program.tvg_id) &&
            (!r.title || r.title === program.title)
        );
        setExistingRuleMode(rule ? rule.mode : null);
      } catch (error) {
        console.warn('Failed to fetch series rules metadata', error);
      }

      const existingRecording = recordingsByProgramId.get(program.id) || null;
      setRecordingForProgram(existingRecording);
    },
    [recordingsByProgramId]
  );

  const recordOne = useCallback(
    async (program) => {
      const channel = findChannelByTvgId(program.tvg_id);
      if (!channel) {
        notifications.show({
          title: 'Unable to schedule recording',
          message: 'No channel found for this program.',
          color: 'red.6',
        });
        return;
      }

      await API.createRecording({
        channel: `${channel.id}`,
        start_time: program.start_time,
        end_time: program.end_time,
        custom_properties: { program },
      });
      notifications.show({ title: 'Recording scheduled' });
    },
    [findChannelByTvgId]
  );

  const saveSeriesRule = useCallback(async (program, mode) => {
    await API.createSeriesRule({
      tvg_id: program.tvg_id,
      mode,
      title: program.title,
    });
    await API.evaluateSeriesRules(program.tvg_id);
    try {
      await useChannelsStore.getState().fetchRecordings();
    } catch (error) {
      console.warn(
        'Failed to refresh recordings after saving series rule',
        error
      );
    }
    notifications.show({
      title: mode === 'new' ? 'Record new episodes' : 'Record all episodes',
    });
  }, []);

  const openRules = useCallback(async () => {
    setRulesOpen(true);
    try {
      const r = await API.listSeriesRules();
      setRules(r);
    } catch (error) {
      console.warn('Failed to load series rules', error);
    }
  }, []);

  // The “Watch Now” click => show floating video
  const showVideo = useVideoStore((s) => s.showVideo);
  const handleWatchStream = useCallback(
    (program) => {
      const matched = findChannelByTvgId(program.tvg_id);
      if (!matched) {
        console.warn(`No channel found for tvg_id=${program.tvg_id}`);
        return;
      }

      let vidUrl = `/proxy/ts/stream/${matched.uuid}`;
      if (env_mode === 'dev') {
        vidUrl = `${window.location.protocol}//${window.location.hostname}:5656${vidUrl}`;
      }

      showVideo(vidUrl);
    },
    [env_mode, findChannelByTvgId, showVideo]
  );

  const handleLogoClick = useCallback(
    (channel, event) => {
      event.stopPropagation();

      let vidUrl = `/proxy/ts/stream/${channel.uuid}`;
      if (env_mode === 'dev') {
        vidUrl = `${window.location.protocol}//${window.location.hostname}:5656${vidUrl}`;
      }

      showVideo(vidUrl);
    },
    [env_mode, showVideo]
  );

  const handleProgramClick = useCallback(
    (program, event) => {
      event.stopPropagation();

      const programStartMs =
        program.startMs ?? dayjs(program.start_time).valueOf();
      const startOffsetMinutes = (programStartMs - start.valueOf()) / 60000;
      const leftPx =
        (startOffsetMinutes / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH;
      const desiredScrollPosition = Math.max(0, leftPx - 20);

      if (expandedProgramId === program.id) {
        setExpandedProgramId(null);
        setRecordingForProgram(null);
      } else {
        setExpandedProgramId(program.id);
        setRecordingForProgram(recordingsByProgramId.get(program.id) || null);
      }

      const guideNode = guideRef.current;
      if (guideNode) {
        const currentScrollPosition = guideNode.scrollLeft;
        if (
          desiredScrollPosition < currentScrollPosition ||
          leftPx - currentScrollPosition < 100
        ) {
          syncScrollLeft(desiredScrollPosition, 'smooth');
        }
      }
    },
    [expandedProgramId, recordingsByProgramId, start, syncScrollLeft]
  );

  // Close the expanded program when clicking elsewhere
  const handleClickOutside = () => {
    if (expandedProgramId) {
      setExpandedProgramId(null);
      setRecordingForProgram(null);
    }
  };

  const scrollToNow = useCallback(() => {
    if (nowPosition < 0) {
      return;
    }

    const roundedNow =
      now.minute() < 30
        ? now.startOf('hour')
        : now.startOf('hour').add(30, 'minute');
    const nowOffset = roundedNow.diff(start, 'minute');
    const scrollPosition =
      (nowOffset / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH - MINUTE_BLOCK_WIDTH;

    const scrollPos = Math.max(scrollPosition, 0);
    syncScrollLeft(scrollPos, 'smooth');
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
    setGuideScrollLeft(nextLeft);

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
      const rect = event.currentTarget.getBoundingClientRect();
      const clickPositionX = event.clientX - rect.left;
      const percentageAcross = clickPositionX / rect.width;
      const minuteWithinHour = Math.floor(percentageAcross * 60);

      let snappedMinute;
      if (minuteWithinHour < 7.5) {
        snappedMinute = 0;
      } else if (minuteWithinHour < 22.5) {
        snappedMinute = 15;
      } else if (minuteWithinHour < 37.5) {
        snappedMinute = 30;
      } else if (minuteWithinHour < 52.5) {
        snappedMinute = 45;
      } else {
        snappedMinute = 0;
        clickedTime = clickedTime.add(1, 'hour');
      }

      const snappedTime = clickedTime.minute(snappedMinute);
      const snappedOffset = snappedTime.diff(start, 'minute');
      const scrollPosition =
        (snappedOffset / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH;

      syncScrollLeft(scrollPosition, 'smooth');
    },
    [start, syncScrollLeft]
  );
  const renderProgram = useCallback(
    (program, channelStart = start, channel = null) => {
      const programStartMs =
        program.startMs ?? dayjs(program.start_time).valueOf();
      const programEndMs = program.endMs ?? dayjs(program.end_time).valueOf();
      const programStart = dayjs(programStartMs);
      const programEnd = dayjs(programEndMs);

      const startOffsetMinutes =
        (programStartMs - channelStart.valueOf()) / 60000;
      const durationMinutes = (programEndMs - programStartMs) / 60000;
      const leftPx =
        (startOffsetMinutes / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH;

      const gapSize = 2;
      const widthPx =
        (durationMinutes / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH - gapSize * 2;

      const recording = recordingsByProgramId.get(program.id);

      const isLive = now.isAfter(programStart) && now.isBefore(programEnd);
      const isPast = now.isAfter(programEnd);
      const isExpanded = expandedProgramId === program.id;

      const rowHeight = isExpanded ? EXPANDED_PROGRAM_HEIGHT : PROGRAM_HEIGHT;
      const MIN_EXPANDED_WIDTH = 450;
      const expandedWidthPx = Math.max(widthPx, MIN_EXPANDED_WIDTH);

      const programStartInView = leftPx + gapSize;
      const programEndInView = leftPx + gapSize + widthPx;
      const viewportLeft = guideScrollLeft;
      const startsBeforeView = programStartInView < viewportLeft;
      const extendsIntoView = programEndInView > viewportLeft;

      let textOffsetLeft = 0;
      if (startsBeforeView && extendsIntoView) {
        const visibleStart = Math.max(viewportLeft - programStartInView, 0);
        const maxOffset = widthPx - 200;
        textOffsetLeft = Math.min(visibleStart, maxOffset);
      }

      return (
        <Box
          className="guide-program-container"
          key={`${channel?.id || 'unknown'}-${program.id || `${program.tvg_id}-${program.start_time}`}`}
          style={{
            position: 'absolute',
            left: leftPx + gapSize,
            top: 0,
            width: isExpanded ? expandedWidthPx : widthPx,
            height: rowHeight - 4,
            cursor: 'pointer',
            zIndex: isExpanded ? 25 : 5,
            transition: isExpanded
              ? 'height 0.2s ease, width 0.2s ease'
              : 'height 0.2s ease',
          }}
          onClick={(event) => handleProgramClick(program, event)}
        >
          <Paper
            elevation={isExpanded ? 4 : 2}
            className={`guide-program ${isLive ? 'live' : isPast ? 'past' : 'not-live'} ${isExpanded ? 'expanded' : ''}`}
            style={{
              width: '100%',
              height: '100%',
              overflow: 'hidden',
              position: 'relative',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: isExpanded ? 'flex-start' : 'space-between',
              padding: isExpanded ? '12px' : '8px',
              backgroundColor: isExpanded
                ? isLive
                  ? '#1a365d'
                  : isPast
                    ? '#18181B'
                    : '#1e40af'
                : isLive
                  ? '#18181B'
                  : isPast
                    ? '#27272A'
                    : '#2c5282',
              color: isPast ? '#a0aec0' : '#fff',
              boxShadow: isExpanded ? '0 4px 8px rgba(0,0,0,0.4)' : 'none',
              transition: 'all 0.2s ease',
            }}
          >
            <Box
              style={{
                transform: `translateX(${textOffsetLeft}px)`,
                transition: 'transform 0.1s ease-out',
              }}
            >
              <Text
                component="div"
                size={isExpanded ? 'lg' : 'md'}
                style={{
                  fontWeight: 'bold',
                  whiteSpace: 'nowrap',
                  textOverflow: 'ellipsis',
                  overflow: 'hidden',
                }}
              >
                <Group gap="xs">
                  {recording && (
                    <div
                      style={{
                        borderRadius: '50%',
                        width: '10px',
                        height: '10px',
                        display: 'flex',
                        backgroundColor: 'red',
                      }}
                    ></div>
                  )}
                  {program.title}
                </Group>
              </Text>
              <Text
                size="sm"
                style={{
                  whiteSpace: 'nowrap',
                  textOverflow: 'ellipsis',
                  overflow: 'hidden',
                }}
              >
                {programStart.format(timeFormat)} -{' '}
                {programEnd.format(timeFormat)}
              </Text>
            </Box>

            {program.description && (
              <Box
                style={{
                  transform: `translateX(${textOffsetLeft}px)`,
                  transition: 'transform 0.1s ease-out',
                }}
              >
                <Text
                  size="xs"
                  style={{
                    marginTop: '4px',
                    whiteSpace: isExpanded ? 'normal' : 'nowrap',
                    textOverflow: isExpanded ? 'clip' : 'ellipsis',
                    overflow: isExpanded ? 'auto' : 'hidden',
                    color: isPast ? '#718096' : '#cbd5e0',
                    maxHeight: isExpanded ? '80px' : 'unset',
                  }}
                >
                  {program.description}
                </Text>
              </Box>
            )}

            {isExpanded && (
              <Box style={{ marginTop: 'auto' }}>
                <Flex gap="md" justify="flex-end" mt={8}>
                  {!isPast && (
                    <Button
                      leftSection={<Calendar size={14} />}
                      variant="filled"
                      color="red"
                      size="xs"
                      onClick={(event) => {
                        event.stopPropagation();
                        openRecordChoice(program);
                      }}
                    >
                      Record
                    </Button>
                  )}

                  {isLive && (
                    <Button
                      leftSection={<Video size={14} />}
                      variant="filled"
                      color="blue"
                      size="xs"
                      onClick={(event) => {
                        event.stopPropagation();
                        handleWatchStream(program);
                      }}
                    >
                      Watch Now
                    </Button>
                  )}
                </Flex>
              </Box>
            )}
          </Paper>
        </Box>
      );
    },
    [
      expandedProgramId,
      guideScrollLeft,
      handleProgramClick,
      handleWatchStream,
      now,
      openRecordChoice,
      recordingsByProgramId,
      start,
      timeFormat,
    ]
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
      expandedProgramId,
      rowHeights,
      logos,
      hoveredChannelId,
      setHoveredChannelId,
      renderProgram,
      handleLogoClick,
      contentWidth,
    }),
    [
      filteredChannels,
      programsByChannelId,
      expandedProgramId,
      rowHeights,
      logos,
      hoveredChannelId,
      renderProgram,
      handleLogoClick,
      contentWidth,
      setHoveredChannelId,
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

  // Create group options for dropdown - but only include groups used by guide channels
  const groupOptions = useMemo(() => {
    const options = [{ value: 'all', label: 'All Channel Groups' }];

    if (channelGroups && guideChannels.length > 0) {
      // Get unique channel group IDs from the channels that have program data
      const usedGroupIds = new Set();
      guideChannels.forEach((channel) => {
        if (channel.channel_group_id) {
          usedGroupIds.add(channel.channel_group_id);
        }
      });
      // Only add groups that are actually used by channels in the guide
      Object.values(channelGroups)
        .filter((group) => usedGroupIds.has(group.id))
        .sort((a, b) => a.name.localeCompare(b.name)) // Sort alphabetically
        .forEach((group) => {
          options.push({
            value: group.id.toString(),
            label: group.name,
          });
        });
    }
    return options;
  }, [channelGroups, guideChannels]);

  // Create profile options for dropdown
  const profileOptions = useMemo(() => {
    const options = [{ value: 'all', label: 'All Profiles' }];

    if (profiles) {
      Object.values(profiles).forEach((profile) => {
        if (profile.id !== '0') {
          // Skip the 'All' default profile
          options.push({
            value: profile.id.toString(),
            label: profile.name,
          });
        }
      });
    }

    return options;
  }, [profiles]);

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

  return (
    <Box
      ref={tvGuideRef}
      className="tv-guide"
      style={{
        overflow: 'hidden',
        width: '100%',
        height: '100%',
        // backgroundColor: 'rgb(39, 39, 42)',
        color: '#fff',
        fontFamily: 'Roboto, sans-serif',
      }}
      onClick={handleClickOutside} // Close expanded program when clicking outside
    >
      {/* Sticky top bar */}
      <Flex
        direction="column"
        style={{
          // backgroundColor: '#424242',
          color: '#fff',
          padding: '12px 20px',
          position: 'sticky',
          top: 0,
          zIndex: 1000,
        }}
      >
        {/* Title and current time */}
        <Flex justify="space-between" align="center" mb={12}>
          <Title order={3} style={{ fontWeight: 'bold' }}>
            TV Guide
          </Title>
          <Flex align="center" gap="md">
            <Text>
              {now.format(`dddd, ${dateFormat}, YYYY • ${timeFormat}`)}
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
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{ width: '250px' }} // Reduced width from flex: 1
            leftSection={<Search size={16} />}
            rightSection={
              searchQuery ? (
                <ActionIcon
                  onClick={() => setSearchQuery('')}
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
            style={{ width: '220px' }}
            clearable={true} // Allow clearing the selection
          />

          <Select
            placeholder="Filter by profile"
            data={profileOptions}
            value={selectedProfileId}
            onChange={handleProfileChange} // Use the new handler
            style={{ width: '180px' }}
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
              border: '1px solid #3BA882',
              color: '#FFFFFF',
            }}
          >
            Series Rules
          </Button>

          <Text size="sm" color="dimmed">
            {filteredChannels.length}{' '}
            {filteredChannels.length === 1 ? 'channel' : 'channels'}
          </Text>
        </Flex>
      </Flex>

      {/* Guide container with headers and scrollable content */}
      <Box
        style={{
          display: 'flex',
          flexDirection: 'column',
          height: 'calc(100vh - 120px)',
        }}
      >
        {/* Logo header - Sticky, non-scrollable */}
        <Box
          style={{
            display: 'flex',
            position: 'sticky',
            top: 0,
            zIndex: 100,
          }}
        >
          {/* Logo header cell - sticky in both directions */}
          <Box
            style={{
              width: CHANNEL_WIDTH,
              minWidth: CHANNEL_WIDTH,
              flexShrink: 0,
              height: '40px',
              backgroundColor: '#18181B',
              borderBottom: '1px solid #27272A',
              borderRight: '1px solid #27272A', // Increased border width
              position: 'sticky',
              left: 0,
              zIndex: 200,
            }}
          />

          {/* Timeline header with its own scrollbar */}
          <Box
            style={{
              flex: 1,
              overflow: 'hidden',
              position: 'relative',
            }}
          >
            <Box
              ref={timelineRef}
              style={{
                overflowX: 'auto',
                overflowY: 'hidden',
                position: 'relative',
              }}
              onScroll={handleTimelineScroll}
              onWheel={handleTimelineWheel} // Add wheel event handler
            >
              <Box
                style={{
                  display: 'flex',
                  backgroundColor: '#1E2A27',
                  borderBottom: '1px solid #27272A',
                  width: hourTimeline.length * HOUR_WIDTH,
                }}
              >
                {' '}
                {hourTimeline.map((hourData) => {
                  const { time, isNewDay } = hourData;

                  return (
                    <Box
                      key={time.format()}
                      style={{
                        width: HOUR_WIDTH,
                        height: '40px',
                        position: 'relative',
                        color: '#a0aec0',
                        borderRight: '1px solid #8DAFAA',
                        cursor: 'pointer',
                        borderLeft: isNewDay ? '2px solid #3BA882' : 'none', // Highlight day boundaries
                        backgroundColor: isNewDay ? '#1E2A27' : '#1B2421', // Subtle background for new days
                      }}
                      onClick={(e) => handleTimeClick(time, e)}
                    >
                      {/* Remove the special day label for new days since we'll show day for all hours */}

                      {/* Position time label at the left border of each hour block */}
                      <Text
                        size="sm"
                        style={{
                          position: 'absolute',
                          top: '8px', // Consistent positioning for all hours
                          left: '4px',
                          transform: 'none',
                          borderRadius: '2px',
                          lineHeight: 1.2,
                          textAlign: 'left',
                        }}
                      >
                        {/* Show day above time for every hour using the same format */}
                        <Text
                          span
                          size="xs"
                          style={{
                            display: 'block',
                            opacity: 0.7,
                            fontWeight: isNewDay ? 600 : 400, // Still emphasize day transitions
                            color: isNewDay ? '#3BA882' : undefined,
                          }}
                        >
                          {formatDayLabel(time)}{' '}
                          {/* Use same formatDayLabel function for all hours */}
                        </Text>
                        {time.format(timeFormat)}
                        <Text span size="xs" ml={1} opacity={0.7}>
                          {/*time.format('A')*/}
                        </Text>
                      </Text>

                      {/* Hour boundary marker - more visible */}
                      <Box
                        style={{
                          position: 'absolute',
                          left: 0,
                          top: 0,
                          bottom: 0,
                          width: '1px',
                          backgroundColor: '#27272A',
                          zIndex: 10,
                        }}
                      />

                      {/* Quarter hour tick marks */}
                      <Box
                        style={{
                          position: 'absolute',
                          bottom: 0,
                          width: '100%',
                          display: 'flex',
                          justifyContent: 'space-between',
                          padding: '0 1px',
                        }}
                      >
                        {[15, 30, 45].map((minute) => (
                          <Box
                            key={minute}
                            style={{
                              width: '1px',
                              height: '8px',
                              backgroundColor: '#718096',
                              position: 'absolute',
                              bottom: 0,
                              left: `${(minute / 60) * 100}%`,
                            }}
                          />
                        ))}
                      </Box>
                    </Box>
                  );
                })}
              </Box>
            </Box>
          </Box>
        </Box>

        {/* Main scrollable container for program content */}
        <Box
          ref={guideContainerRef}
          style={{
            flex: 1,
            position: 'relative',
            overflow: 'hidden',
          }}
        >
          {nowPosition >= 0 && (
            <Box
              style={{
                position: 'absolute',
                left: nowPosition + CHANNEL_WIDTH - guideScrollLeft,
                top: 0,
                bottom: 0,
                width: '2px',
                backgroundColor: '#38b2ac',
                zIndex: 15,
                pointerEvents: 'none',
              }}
            />
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
              overscanCount={8}
            >
              {GuideRow}
            </VariableSizeList>
          ) : (
            <Box
              style={{
                padding: '30px',
                textAlign: 'center',
                color: '#a0aec0',
              }}
            >
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
        <Modal
          opened={recordChoiceOpen}
          onClose={() => setRecordChoiceOpen(false)}
          title={`Record: ${recordChoiceProgram.title}`}
          centered
          radius="md"
          zIndex={9999}
          overlayProps={{ color: '#000', backgroundOpacity: 0.55, blur: 0 }}
          styles={{
            content: { backgroundColor: '#18181B', color: 'white' },
            header: { backgroundColor: '#18181B', color: 'white' },
            title: { color: 'white' },
          }}
        >
          <Flex direction="column" gap="sm">
            <Button
              onClick={() => {
                recordOne(recordChoiceProgram);
                setRecordChoiceOpen(false);
              }}
            >
              Just this one
            </Button>
            <Button
              variant="light"
              onClick={() => {
                saveSeriesRule(recordChoiceProgram, 'all');
                setRecordChoiceOpen(false);
              }}
            >
              Every episode
            </Button>
            <Button
              variant="light"
              onClick={() => {
                saveSeriesRule(recordChoiceProgram, 'new');
                setRecordChoiceOpen(false);
              }}
            >
              New episodes only
            </Button>
            {recordingForProgram && (
              <>
                <Button
                  color="orange"
                  variant="light"
                  onClick={async () => {
                    try {
                      await API.deleteRecording(recordingForProgram.id);
                    } catch (error) {
                      console.warn('Failed to delete recording', error);
                    }
                    try {
                      await useChannelsStore.getState().fetchRecordings();
                    } catch (error) {
                      console.warn(
                        'Failed to refresh recordings after delete',
                        error
                      );
                    }
                    setRecordChoiceOpen(false);
                  }}
                >
                  Remove this recording
                </Button>
                <Button
                  color="red"
                  variant="light"
                  onClick={async () => {
                    try {
                      await API.bulkRemoveSeriesRecordings({
                        tvg_id: recordChoiceProgram.tvg_id,
                        title: recordChoiceProgram.title,
                        scope: 'title',
                      });
                    } catch (error) {
                      console.warn(
                        'Failed to remove scheduled series recordings',
                        error
                      );
                    }
                    try {
                      await API.deleteSeriesRule(recordChoiceProgram.tvg_id);
                    } catch (error) {
                      console.warn('Failed to delete series rule', error);
                    }
                    try {
                      await useChannelsStore.getState().fetchRecordings();
                    } catch (error) {
                      console.warn(
                        'Failed to refresh recordings after series delete',
                        error
                      );
                    }
                    setRecordChoiceOpen(false);
                  }}
                >
                  Remove this series (scheduled)
                </Button>
              </>
            )}
            {existingRuleMode && (
              <Button
                color="red"
                variant="subtle"
                onClick={async () => {
                  await API.deleteSeriesRule(recordChoiceProgram.tvg_id);
                  setExistingRuleMode(null);
                  setRecordChoiceOpen(false);
                }}
              >
                Remove series rule ({existingRuleMode})
              </Button>
            )}
          </Flex>
        </Modal>
      )}

      {/* Series rules modal */}
      {rulesOpen && (
        <Modal
          opened={rulesOpen}
          onClose={() => setRulesOpen(false)}
          title="Series Recording Rules"
          centered
          radius="md"
          zIndex={9999}
          overlayProps={{ color: '#000', backgroundOpacity: 0.55, blur: 0 }}
          styles={{
            content: { backgroundColor: '#18181B', color: 'white' },
            header: { backgroundColor: '#18181B', color: 'white' },
            title: { color: 'white' },
          }}
        >
          <Stack gap="sm">
            {(!rules || rules.length === 0) && (
              <Text size="sm" c="dimmed">
                No series rules configured
              </Text>
            )}
            {rules &&
              rules.map((r) => (
                <Flex
                  key={`${r.tvg_id}-${r.mode}`}
                  justify="space-between"
                  align="center"
                >
                  <Text size="sm">
                    {r.title || r.tvg_id} —{' '}
                    {r.mode === 'new' ? 'New episodes' : 'Every episode'}
                  </Text>
                  <Group gap="xs">
                    <Button
                      size="xs"
                      variant="subtle"
                      onClick={async () => {
                        await API.evaluateSeriesRules(r.tvg_id);
                        try {
                          await useChannelsStore.getState().fetchRecordings();
                        } catch (error) {
                          console.warn(
                            'Failed to refresh recordings after evaluation',
                            error
                          );
                        }
                        notifications.show({
                          title: 'Evaluated',
                          message: 'Checked for episodes',
                        });
                      }}
                    >
                      Evaluate Now
                    </Button>
                    <Button
                      size="xs"
                      variant="light"
                      color="orange"
                      onClick={async () => {
                        await API.bulkRemoveSeriesRecordings({
                          tvg_id: r.tvg_id,
                          title: r.title,
                          scope: 'title',
                        });
                        try {
                          await API.deleteSeriesRule(r.tvg_id);
                        } catch (error) {
                          console.warn(
                            'Failed to delete series rule during removal',
                            error
                          );
                        }
                        try {
                          await useChannelsStore.getState().fetchRecordings();
                        } catch (error) {
                          console.warn(
                            'Failed to refresh recordings after bulk removal',
                            error
                          );
                        }
                        const updated = await API.listSeriesRules();
                        setRules(updated);
                      }}
                    >
                      Remove this series (scheduled)
                    </Button>
                  </Group>
                </Flex>
              ))}
          </Stack>
        </Modal>
      )}
    </Box>
  );
}
