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
import useVideoStore from '../store/useVideoStore'; // NEW import
import useSettingsStore from '../store/settings';
import {
  ActionIcon,
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
import { Calendar, Clock, Search, Video, X } from 'lucide-react';
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
  EXPANDED_PROGRAM_HEIGHT,
  fetchPrograms,
  fetchRules,
  filterGuideChannels,
  formatTime,
  getGroupOptions,
  getProfileOptions,
  getRuleByProgram,
  HOUR_WIDTH,
  mapChannelsById,
  mapProgramsByChannel,
  mapRecordingsByProgramId,
  matchChannelByTvgId,
  MINUTE_BLOCK_WIDTH,
  MINUTE_INCREMENT,
  PROGRAM_HEIGHT,
  sortChannels,
} from './guideUtils';
import {
  getShowVideoUrl,
} from '../utils/cards/RecordingCardUtils.js';
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
const ProgramRecordingModal = React.lazy(() =>
  import('../components/forms/ProgramRecordingModal'));
const SeriesRecordingModal = React.lazy(() =>
  import('../components/forms/SeriesRecordingModal'));
import { showNotification } from '../utils/notificationUtils.js';
import ErrorBoundary from '../components/ErrorBoundary.jsx';

export default function TVChannelGuide({ startDate, endDate }) {
  const channels = useChannelsStore((s) => s.channels);
  const recordings = useChannelsStore((s) => s.recordings);
  const channelGroups = useChannelsStore((s) => s.channelGroups);
  const profiles = useChannelsStore((s) => s.profiles);
  const isLoading = useChannelsStore((s) => s.isLoading);
  const [isProgramsLoading, setIsProgramsLoading] = useState(true);
  const logos = useLogosStore((s) => s.logos);

  const tvgsById = useEPGsStore((s) => s.tvgsById);
  const epgs = useEPGsStore((s) => s.epgs);

  const [programs, setPrograms] = useState([]);
  const [guideChannels, setGuideChannels] = useState([]);
  const [now, setNow] = useState(getNow());
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
    if (Object.keys(channels).length === 0) {
      console.warn('No channels provided or empty channels array');
      showNotification({ title: 'No channels available', color: 'red.5' });
      setIsProgramsLoading(false);
      return;
    }

    const sortedChannels = sortChannels(channels);
    setGuideChannels(sortedChannels);

    fetchPrograms()
      .then((data) => {
        setPrograms(data);
        setIsProgramsLoading(false);
      })
      .catch((error) => {
        console.error('Failed to fetch programs:', error);
        setIsProgramsLoading(false);
      });
  }, [channels]);

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

  const channelIdByTvgId = useMemo(
    () => buildChannelIdMap(guideChannels, tvgsById, epgs),
    [guideChannels, tvgsById, epgs]
  );

  const channelById = useMemo(
    () => mapChannelsById(guideChannels),
    [guideChannels]
  );

  const programsByChannelId = useMemo(
    () => mapProgramsByChannel(programs, channelIdByTvgId),
    [programs, channelIdByTvgId]
  );

  const recordingsByProgramId = useMemo(
    () => mapRecordingsByProgramId(recordings),
    [recordings]
  );

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

  const [timeFormat, dateFormat] = useDateTimeFormat();

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
      setNow(getNow());
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  // Pixel offset for the "now" vertical line
  const nowPosition = useMemo(
    () => calculateNowPosition(now, start, end),
    [now, start, end]
  );

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
      syncScrollLeft(calculateScrollPosition(now, start));

      setInitialScrollComplete(true);
    }
  }, [programs, start, now, initialScrollComplete, syncScrollLeft]);

  const findChannelByTvgId = useCallback(
    (tvgId) => matchChannelByTvgId(channelIdByTvgId, channelById, tvgId),
    [channelById, channelIdByTvgId]
  );

  const openRecordChoice = useCallback(
    async (program) => {
      setRecordChoiceProgram(program);
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
    async (program) => {
      const channel = findChannelByTvgId(program.tvg_id);
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
    [findChannelByTvgId]
  );

  const saveSeriesRule = useCallback(async (program, mode) => {
    await createSeriesRule(program, mode);
    await evaluateSeriesRule(program);
    try {
      await useChannelsStore.getState().fetchRecordings();
    } catch (error) {
      console.warn(
        'Failed to refresh recordings after saving series rule',
        error
      );
    }
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

  // The “Watch Now” click => show floating video
  const showVideo = useVideoStore((s) => s.showVideo);
  const handleWatchStream = useCallback(
    (program) => {
      const matched = findChannelByTvgId(program.tvg_id);
      if (!matched) {
        console.warn(`No channel found for tvg_id=${program.tvg_id}`);
        return;
      }

      showVideo(getShowVideoUrl(matched, env_mode));
    },
    [env_mode, findChannelByTvgId, showVideo]
  );

  const handleLogoClick = useCallback(
    (channel, event) => {
      event.stopPropagation();

      showVideo(getShowVideoUrl(channel, env_mode));
    },
    [env_mode, showVideo]
  );

  const handleProgramClick = useCallback(
    (program, event) => {
      event.stopPropagation();

      if (expandedProgramId === program.id) {
        setExpandedProgramId(null);
        setRecordingForProgram(null);
      } else {
        setExpandedProgramId(program.id);
        setRecordingForProgram(recordingsByProgramId.get(program.id) || null);
      }

      const leftPx = calculateLeftScrollPosition(program, start);
      const desiredScrollPosition = calculateDesiredScrollPosition(leftPx);

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

      const gapSize = 2;
      const widthPx =
        (durationMinutes / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH - gapSize * 2;

      const recording = recordingsByProgramId.get(program.id);

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

      const RecordButton = () => {
        return (
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
        );
      };
      const WatchNow = () => {
        return (
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
        );
      };
      return (
        <Box
          className="guide-program-container"
          key={`${channel?.id || 'unknown'}-${program.id || `${program.tvg_id}-${program.start_time}`}`}
          style={{
            cursor: 'pointer',
            zIndex: isExpanded ? 25 : 5,
            transition: isExpanded ? 'height 0.2s ease, width 0.2s ease' : 'height 0.2s ease',
          }}
          pos='absolute'
          left={leftPx + gapSize}
          top={0}
          w={isExpanded ? expandedWidthPx : widthPx}
          h={rowHeight - 4}
          onClick={(event) => handleProgramClick(program, event)}
        >
          <Paper
            elevation={isExpanded ? 4 : 2}
            className={`guide-program ${isLive ? 'live' : isPast ? 'past' : 'not-live'} ${isExpanded ? 'expanded' : ''}`}
            style={{
              overflow: 'hidden',
              flexDirection: 'column',
              justifyContent: isExpanded ? 'flex-start' : 'space-between',
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
              boxShadow: isExpanded ? '0 4px 8px rgba(0,0,0,0.4)' : 'none',
              transition: 'all 0.2s ease',
            }}
            w={'100%'}
            h={'100%'}
            pos='relative'
            display={'flex'}
            p={isExpanded ? 12 : 8}
            c={isPast ? '#a0aec0' : '#fff'}
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
                  whiteSpace: 'nowrap',
                  textOverflow: 'ellipsis',
                  overflow: 'hidden',
                }}
                fw={'bold'}
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
                {format(programStart, timeFormat)} -{' '}
                {format(programEnd, timeFormat)}
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
                    whiteSpace: isExpanded ? 'normal' : 'nowrap',
                    textOverflow: isExpanded ? 'clip' : 'ellipsis',
                    overflow: isExpanded ? 'auto' : 'hidden',
                  }}
                  mt={4}
                  c={isPast ? '#718096' : '#cbd5e0'}
                  mah={isExpanded ? '80px' : 'unset'}
                >
                  {program.description}
                </Text>
              </Box>
            )}

            {isExpanded && (
              <Box mt={'auto'}>
                <Flex gap="md" justify="flex-end" mt={8}>
                  {!isPast && <RecordButton />}

                  {isLive && <WatchNow />}
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
  const groupOptions = useMemo(
    () => getGroupOptions(channelGroups, guideChannels),
    [channelGroups, guideChannels]
  );

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
      c='#ffffff'
      ff={'Roboto, sans-serif'}
      onClick={handleClickOutside} // Close expanded program when clicking outside
    >
      {/* Sticky top bar */}
      <Flex
        direction="column"
        style={{
          zIndex: 1000,
          position: 'sticky'
        }}
        c='#ffffff'
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
            clearable={true} // Allow clearing the selection
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
            color='#FFFFFF'
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
            position: 'sticky'
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
            pos='sticky'
            left={0}
          />

          {/* Timeline header with its own scrollbar */}
          <Box
            style={{
              flex: 1,
              overflow: 'hidden',
            }}
            pos='relative'
          >
            <Box
              ref={timelineRef}
              style={{
                overflowX: 'auto',
                overflowY: 'hidden',
              }}
              pos='relative'
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
          pos='relative'
        >
          <LoadingOverlay visible={isLoading || isProgramsLoading} />
          {nowPosition >= 0 && (
            <Box
              style={{
                backgroundColor: '#38b2ac',
                zIndex: 15,
                pointerEvents: 'none',
              }}
              pos='absolute'
              left={nowPosition + CHANNEL_WIDTH - guideScrollLeft}
              top={0}
              bottom={0}
              w={'2px'}
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
            <Box p={'30px'} ta='center' color='#a0aec0'>
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
              onRecordOne={() => recordOne(recordChoiceProgram)}
              onRecordSeriesAll={() => saveSeriesRule(recordChoiceProgram, 'all')}
              onRecordSeriesNew={() => saveSeriesRule(recordChoiceProgram, 'new')}
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
    </Box>
  );
}
