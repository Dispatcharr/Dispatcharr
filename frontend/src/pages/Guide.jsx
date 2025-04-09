// frontend/src/pages/Guide.js
import React, { useMemo, useState, useEffect, useRef } from 'react';
import dayjs from 'dayjs';
import API from '../api';
import useChannelsStore from '../store/channels';
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
} from '@mantine/core';
import { Search, X, Clock, Video, Calendar } from 'lucide-react';
import './guide.css';

/** Layout constants */
const CHANNEL_WIDTH = 120; // Width of the channel/logo column
const PROGRAM_HEIGHT = 90; // Height of each channel row
const EXPANDED_PROGRAM_HEIGHT = 180; // Height for expanded program rows
const HOUR_WIDTH = 450; // Increased from 300 to 450 to make each program wider
const MINUTE_INCREMENT = 15; // For positioning programs every 15 min
const MINUTE_BLOCK_WIDTH = HOUR_WIDTH / (60 / MINUTE_INCREMENT);

export default function TVChannelGuide({ startDate, endDate }) {
  const { channels, recordings, channelGroups, profiles } = useChannelsStore();

  const [programs, setPrograms] = useState([]);
  const [guideChannels, setGuideChannels] = useState([]);
  const [filteredChannels, setFilteredChannels] = useState([]);
  const [now, setNow] = useState(dayjs());
  const [expandedProgramId, setExpandedProgramId] = useState(null); // Track expanded program
  const [recordingForProgram, setRecordingForProgram] = useState(null);
  const [loading, setLoading] = useState(true);
  const [initialScrollComplete, setInitialScrollComplete] = useState(false);

  // New filter states
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedGroupId, setSelectedGroupId] = useState('all');
  const [selectedProfileId, setSelectedProfileId] = useState('all');

  const {
    environment: { env_mode },
  } = useSettingsStore();

  const guideRef = useRef(null);
  const timelineRef = useRef(null); // New ref for timeline scrolling

  // Load program data once
  useEffect(() => {
    if (!Object.keys(channels).length === 0) {
      console.warn('No channels provided or empty channels array');
      notifications.show({ title: 'No channels available', color: 'red.5' });
      setLoading(false);
      return;
    }

    const fetchPrograms = async () => {
      console.log('Fetching program grid...');
      const fetched = await API.getGrid(); // GETs your EPG grid
      console.log(`Received ${fetched.length} programs`);

      // Unique tvg_ids from returned programs
      const programIds = [...new Set(fetched.map((p) => p.tvg_id))];

      // Filter your Redux/Zustand channels by matching tvg_id
      const filteredChannels = Object.values(channels)
        .filter((ch) => programIds.includes(ch.epg_data?.tvg_id))
        // Add sorting by channel_number
        .sort((a, b) => (a.channel_number || Infinity) - (b.channel_number || Infinity));

      console.log(
        `found ${filteredChannels.length} channels with matching tvg_ids`
      );

      setGuideChannels(filteredChannels);
      setFilteredChannels(filteredChannels); // Initialize filtered channels
      console.log(fetched);
      setPrograms(fetched);
      setLoading(false);
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
      result = result.filter(channel =>
        channel.name.toLowerCase().includes(query)
      );
    }

    // Apply channel group filter
    if (selectedGroupId !== 'all') {
      result = result.filter(channel =>
        channel.channel_group?.id === parseInt(selectedGroupId)
      );
    }

    // Apply profile filter
    if (selectedProfileId !== 'all') {
      // Get the profile's enabled channels
      const profileChannels = profiles[selectedProfileId]?.channels || [];
      const enabledChannelIds = profileChannels
        .filter(pc => pc.enabled)
        .map(pc => pc.id);

      result = result.filter(channel =>
        enabledChannelIds.includes(channel.id)
      );
    }

    setFilteredChannels(result);
  }, [searchQuery, selectedGroupId, selectedProfileId, guideChannels, profiles]);

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

  // Time increments in 15-min steps (for placing programs)
  const programTimeline = useMemo(() => {
    const times = [];
    let current = start;
    while (current.isBefore(end)) {
      times.push(current);
      current = current.add(MINUTE_INCREMENT, 'minute');
    }
    return times;
  }, [start, end]);

  // Hourly marks
  const hourTimeline = useMemo(() => {
    const hours = [];
    let current = start;
    while (current.isBefore(end)) {
      hours.push(current);
      current = current.add(1, 'hour');
    }
    return hours;
  }, [start, end]);

  // Scroll to the nearest half-hour mark ONLY on initial load
  useEffect(() => {
    if (guideRef.current && timelineRef.current && programs.length > 0 && !initialScrollComplete) {
      // Round the current time to the nearest half-hour mark
      const roundedNow = now.minute() < 30 ? now.startOf('hour') : now.startOf('hour').add(30, 'minute');
      const nowOffset = roundedNow.diff(start, 'minute');
      const scrollPosition =
        (nowOffset / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH - MINUTE_BLOCK_WIDTH;

      const scrollPos = Math.max(scrollPosition, 0);
      guideRef.current.scrollLeft = scrollPos;
      timelineRef.current.scrollLeft = scrollPos; // Sync timeline scroll

      // Mark initial scroll as complete
      setInitialScrollComplete(true);
    }
  }, [programs, start, now, initialScrollComplete]);

  // Update “now” every second
  useEffect(() => {
    const interval = setInterval(() => {
      setNow(dayjs());
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  // Pixel offset for the “now” vertical line
  const nowPosition = useMemo(() => {
    if (now.isBefore(start) || now.isAfter(end)) return -1;
    const minutesSinceStart = now.diff(start, 'minute');
    return (minutesSinceStart / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH;
  }, [now, start, end]);

  // Helper: find channel by tvg_id
  function findChannelByTvgId(tvgId) {
    return guideChannels.find((ch) => ch.epg_data?.tvg_id === tvgId);
  }

  const record = async (program) => {
    const channel = findChannelByTvgId(program.tvg_id);
    await API.createRecording({
      channel: `${channel.id}`,
      start_time: program.start_time,
      end_time: program.end_time,
      custom_properties: JSON.stringify({
        program,
      }),
    });
    notifications.show({ title: 'Recording scheduled' });
  };

  // The “Watch Now” click => show floating video
  const { showVideo } = useVideoStore(); // or useVideoStore()
  function handleWatchStream(program) {
    const matched = findChannelByTvgId(program.tvg_id);
    if (!matched) {
      console.warn(`No channel found for tvg_id=${program.tvg_id}`);
      return;
    }
    // Build a playable stream URL for that channel
    let vidUrl = `/proxy/ts/stream/${matched.uuid}`;
    if (env_mode == 'dev') {
      vidUrl = `${window.location.protocol}//${window.location.hostname}:5656${vidUrl}`;
    }

    showVideo(vidUrl);
  }

  // On program click, toggle the expanded state
  function handleProgramClick(program, event) {
    // Prevent event from bubbling up to parent elements
    event.stopPropagation();

    // Get the program's start time and calculate its position
    const programStart = dayjs(program.start_time);
    const startOffsetMinutes = programStart.diff(start, 'minute');
    const leftPx = (startOffsetMinutes / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH;

    // Calculate desired scroll position (account for channel column width)
    const desiredScrollPosition = Math.max(0, leftPx - 20); // 20px buffer

    // If already expanded, collapse it
    if (expandedProgramId === program.id) {
      setExpandedProgramId(null);
      setRecordingForProgram(null);
      return;
    }

    // Otherwise expand this program
    setExpandedProgramId(program.id);

    // Check if this program has a recording
    const programRecording = recordings.find((recording) => {
      if (recording.custom_properties) {
        const customProps = JSON.parse(recording.custom_properties);
        if (customProps.program && customProps.program.id == program.id) {
          return true;
        }
      }
      return false;
    });

    setRecordingForProgram(programRecording);

    // Scroll to show the start of the program if it's not already fully visible
    if (guideRef.current && timelineRef.current) {
      const currentScrollPosition = guideRef.current.scrollLeft;

      // Check if we need to scroll (if program start is before current view or too close to edge)
      if (desiredScrollPosition < currentScrollPosition ||
        leftPx - currentScrollPosition < 100) { // 100px from left edge

        // Smooth scroll to the program's start
        guideRef.current.scrollTo({
          left: desiredScrollPosition,
          behavior: 'smooth'
        });

        // Also sync the timeline scroll
        timelineRef.current.scrollTo({
          left: desiredScrollPosition,
          behavior: 'smooth'
        });
      }
    }
  }

  // Close the expanded program when clicking elsewhere
  const handleClickOutside = () => {
    if (expandedProgramId) {
      setExpandedProgramId(null);
      setRecordingForProgram(null);
    }
  };

  // Function to scroll to current time - matches initial loading position
  const scrollToNow = () => {
    if (guideRef.current && timelineRef.current && nowPosition >= 0) {
      // Round the current time to the nearest half-hour mark
      const roundedNow = now.minute() < 30 ? now.startOf('hour') : now.startOf('hour').add(30, 'minute');
      const nowOffset = roundedNow.diff(start, 'minute');
      const scrollPosition =
        (nowOffset / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH - MINUTE_BLOCK_WIDTH;

      const scrollPos = Math.max(scrollPosition, 0);
      guideRef.current.scrollLeft = scrollPos;
      timelineRef.current.scrollLeft = scrollPos; // Sync timeline scroll
    }
  };

  // Sync scrolling between timeline and main content
  const handleTimelineScroll = () => {
    if (timelineRef.current && guideRef.current) {
      guideRef.current.scrollLeft = timelineRef.current.scrollLeft;
    }
  };

  // Sync scrolling between main content and timeline
  const handleGuideScroll = () => {
    if (guideRef.current && timelineRef.current) {
      timelineRef.current.scrollLeft = guideRef.current.scrollLeft;
    }
  };

  // Handle wheel events on the timeline for horizontal scrolling
  const handleTimelineWheel = (e) => {
    if (timelineRef.current) {
      // Prevent the default vertical scroll
      e.preventDefault();

      // Determine scroll amount (with shift key for faster scrolling)
      const scrollAmount = e.shiftKey ? 250 : 125;

      // Scroll horizontally based on wheel direction
      timelineRef.current.scrollLeft += e.deltaY > 0 ? scrollAmount : -scrollAmount;

      // Sync the main content scroll position
      if (guideRef.current) {
        guideRef.current.scrollLeft = timelineRef.current.scrollLeft;
      }
    }
  };

  // Function to handle timeline time clicks with 15-minute snapping
  const handleTimeClick = (clickedTime, event) => {
    if (timelineRef.current && guideRef.current) {
      // Calculate where in the hour block the click happened
      const hourBlockElement = event.currentTarget;
      const rect = hourBlockElement.getBoundingClientRect();
      const clickPositionX = event.clientX - rect.left; // Position within the hour block
      const percentageAcross = clickPositionX / rect.width; // 0 to 1 value

      // Calculate the minute within the hour based on click position
      const minuteWithinHour = Math.floor(percentageAcross * 60);

      // Create a new time object with the calculated minute
      const exactTime = clickedTime.minute(minuteWithinHour);

      // Determine the nearest 15-minute interval (0, 15, 30, 45)
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
        // If we're past 52.5 minutes, snap to the next hour
        snappedMinute = 0;
        clickedTime = clickedTime.add(1, 'hour');
      }

      // Create the snapped time
      const snappedTime = clickedTime.minute(snappedMinute);

      // Calculate the offset from the start of the timeline to the snapped time
      const snappedOffset = snappedTime.diff(start, 'minute');

      // Convert to pixels
      const scrollPosition = (snappedOffset / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH;

      // Scroll both containers to the snapped position
      timelineRef.current.scrollLeft = scrollPosition;
      guideRef.current.scrollLeft = scrollPosition;
    }
  };

  // Renders each program block
  function renderProgram(program, channelStart) {
    const programKey = `${program.tvg_id}-${program.start_time}`;
    const programStart = dayjs(program.start_time);
    const programEnd = dayjs(program.end_time);
    const startOffsetMinutes = programStart.diff(channelStart, 'minute');
    const durationMinutes = programEnd.diff(programStart, 'minute');
    const leftPx = (startOffsetMinutes / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH;
    const widthPx = (durationMinutes / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH;

    // Check if we have a recording for this program
    const recording = recordings.find((recording) => {
      if (recording.custom_properties) {
        const customProps = JSON.parse(recording.custom_properties);
        if (customProps.program && customProps.program.id == program.id) {
          return recording;
        }
      }
      return null;
    });

    // Highlight if currently live
    const isLive = now.isAfter(programStart) && now.isBefore(programEnd);

    // Determine if the program has ended
    const isPast = now.isAfter(programEnd);

    // Check if this program is expanded
    const isExpanded = expandedProgramId === program.id;

    // Calculate how much of the program is cut off
    const cutOffMinutes = Math.max(0, channelStart.diff(programStart, 'minute'));
    const cutOffPx = (cutOffMinutes / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH;

    // Set the height based on expanded state
    const rowHeight = isExpanded ? EXPANDED_PROGRAM_HEIGHT : PROGRAM_HEIGHT;

    // Determine expanded width - if program is short, ensure it has a minimum expanded width
    // This will allow it to overlap programs to the right
    const MIN_EXPANDED_WIDTH = 450; // Minimum width in pixels when expanded
    const expandedWidthPx = Math.max(widthPx, MIN_EXPANDED_WIDTH);

    return (
      <Box
        className="guide-program-container"
        key={programKey}
        style={{
          position: 'absolute',
          left: leftPx,
          top: 0,
          width: isExpanded ? expandedWidthPx : widthPx, // Expand right for short programs
          height: rowHeight - 4, // Adjust for the parent row padding
          cursor: 'pointer',
          zIndex: isExpanded ? 25 : 5, // Increase z-index when expanded
          transition: isExpanded ? 'height 0.2s ease, width 0.2s ease' : 'height 0.2s ease',
        }}
        onClick={(e) => handleProgramClick(program, e)}
      >
        <Paper
          elevation={isExpanded ? 4 : 2}
          className={`guide-program ${isLive ? 'live' : isPast ? 'past' : 'not-live'} ${isExpanded ? 'expanded' : ''}`}
          style={{
            width: "100%", // Fill container width (which may be expanded)
            height: '100%',
            overflow: 'hidden',
            position: 'relative',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: isExpanded ? 'flex-start' : 'space-between',
            padding: isExpanded ? '12px' : '8px',
            backgroundColor: isExpanded
              ? isLive
                ? '#1a365d' // Darker blue when expanded and live
                : isPast
                  ? '#2d3748' // Darker gray when expanded and past
                  : '#1e40af' // Darker blue when expanded and upcoming
              : isLive
                ? '#2d3748' // Default live program color
                : isPast
                  ? '#4a5568' // Slightly darker color for past programs
                  : '#2c5282', // Default color for upcoming programs
            color: isPast ? '#a0aec0' : '#fff', // Dim text color for past programs
            boxShadow: isExpanded ? '0 4px 8px rgba(0,0,0,0.4)' : 'none',
            transition: 'all 0.2s ease',
          }}
        >
          <Box>
            <Text
              size={isExpanded ? "lg" : "md"}
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
              {programStart.format('h:mma')} - {programEnd.format('h:mma')}
            </Text>
          </Box>

          {/* Description is always shown but expands when row is expanded */}
          {program.description && (
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
          )}

          {/* Expanded content */}
          {isExpanded && (
            <Box style={{ marginTop: 'auto' }}>
              <Flex gap="md" justify="flex-end" mt={8}>
                {/* Only show Record button if not already recording AND not in the past */}
                {!recording && !isPast && (
                  <Button
                    leftSection={<Calendar size={14} />}
                    variant="filled"
                    color="red"
                    size="xs"
                    onClick={(e) => {
                      e.stopPropagation();
                      record(program);
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
                    onClick={(e) => {
                      e.stopPropagation();
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
  }

  // Create group options for dropdown
  const groupOptions = useMemo(() => {
    const options = [{ value: 'all', label: 'All Channel Groups' }];

    if (channelGroups) {
      Object.values(channelGroups).forEach(group => {
        options.push({
          value: group.id.toString(),
          label: group.name
        });
      });
    }

    return options;
  }, [channelGroups]);

  // Create profile options for dropdown
  const profileOptions = useMemo(() => {
    const options = [{ value: 'all', label: 'All Profiles' }];

    if (profiles) {
      Object.values(profiles).forEach(profile => {
        if (profile.id !== '0') { // Skip the 'All' default profile
          options.push({
            value: profile.id.toString(),
            label: profile.name
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

  return (
    <Box
      className="tv-guide"
      style={{
        overflow: 'hidden',
        width: '100%',
        height: '100%',
        backgroundColor: '#1a202c',
        color: '#fff',
        fontFamily: 'Roboto, sans-serif',
      }}
      onClick={handleClickOutside} // Close expanded program when clicking outside
    >
      {/* Sticky top bar */}
      <Flex
        direction="column"
        style={{
          backgroundColor: '#2d3748',
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
            <Text>{now.format('dddd, MMMM D, YYYY • h:mm A')}</Text>
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
                <ActionIcon onClick={() => setSearchQuery('')} variant="subtle" color="gray" size="sm">
                  <X size={14} />
                </ActionIcon>
              ) : null
            }
          />

          <Select
            placeholder="Filter by group"
            data={groupOptions}
            value={selectedGroupId}
            onChange={setSelectedGroupId}
            style={{ width: '220px' }}
            clearable={false}
          />

          <Select
            placeholder="Filter by profile"
            data={profileOptions}
            value={selectedProfileId}
            onChange={setSelectedProfileId}
            style={{ width: '180px' }}
            clearable={false}
          />

          {(searchQuery !== '' || selectedGroupId !== 'all' || selectedProfileId !== 'all') && (
            <Button variant="subtle" onClick={clearFilters} size="sm" compact>
              Clear Filters
            </Button>
          )}

          <Text size="sm" color="dimmed">
            {filteredChannels.length} {filteredChannels.length === 1 ? 'channel' : 'channels'}
          </Text>
        </Flex>
      </Flex>

      {/* Guide container with headers and scrollable content */}
      <Box style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 120px)' }}>
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
              backgroundColor: '#2d3748',
              borderBottom: '1px solid #4a5568',
              borderRight: '1px solid #4a5568', // Increased border width
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
                  backgroundColor: '#171923',
                  borderBottom: '1px solid #4a5568',
                  width: hourTimeline.length * HOUR_WIDTH,
                }}
              >
                {hourTimeline.map((time, hourIndex) => (
                  <Box
                    key={time.format()}
                    style={{
                      width: HOUR_WIDTH,
                      height: '40px',
                      position: 'relative',
                      color: '#a0aec0',
                      borderRight: '1px solid #4a5568',
                      cursor: 'pointer', // Add pointer cursor to indicate clickable
                    }}
                    onClick={(e) => handleTimeClick(time, e)} // Pass the event to get click position
                  >
                    <Text
                      size="sm"
                      style={{
                        position: 'absolute',
                        top: '50%',
                        left: hourIndex === 0 ? 4 : 'calc(50% - 16px)',
                        transform: 'translateY(-50%)',
                      }}
                    >
                      {time.format('h:mma')}
                    </Text>
                    <Box
                      style={{
                        position: 'absolute',
                        bottom: 0,
                        top: 0,
                        width: '100%',
                        display: 'grid',
                        gridTemplateColumns: 'repeat(4, 1fr)',
                        alignItems: 'end',
                      }}
                    >
                      {[0, 1, 2, 3].map((i) => (
                        <Box
                          key={i}
                          style={{
                            width: '1px',
                            height: '10px',
                            backgroundColor: '#718096',
                            marginRight: i < 3 ? HOUR_WIDTH / 4 - 1 + 'px' : 0,
                          }}
                        />
                      ))}
                    </Box>
                  </Box>
                ))}
              </Box>
            </Box>
          </Box>
        </Box>

        {/* Main scrollable container for program content */}
        <Box
          ref={guideRef}
          style={{
            flex: 1,
            overflowY: 'auto',
            overflowX: 'hidden',
            position: 'relative',
          }}
          onScroll={handleGuideScroll}
        >
          {/* Content wrapper with min-width to ensure scroll range */}
          <Box style={{
            width: hourTimeline.length * HOUR_WIDTH + CHANNEL_WIDTH,
            position: 'relative',
            display: 'flex',
            flexDirection: 'column'
          }}>
            {/* Now line - positioned absolutely within content */}
            {nowPosition >= 0 && (
              <Box
                style={{
                  position: 'absolute',
                  left: nowPosition + CHANNEL_WIDTH,
                  top: 0,
                  height: '100%',
                  width: '2px',
                  backgroundColor: '#38b2ac',
                  zIndex: 15,
                  pointerEvents: 'none', // Allow clicking through the line
                }}
              />
            )}

            {/* Channel rows with logos and programs */}
            {filteredChannels.length > 0 ? (
              filteredChannels.map((channel) => {
                const channelPrograms = programs.filter(
                  (p) => p.tvg_id === channel.epg_data?.tvg_id
                );
                // Check if any program in this channel is expanded
                const hasExpandedProgram = channelPrograms.some(prog => prog.id === expandedProgramId);
                const rowHeight = hasExpandedProgram ? EXPANDED_PROGRAM_HEIGHT : PROGRAM_HEIGHT;

                return (
                  <Box
                    key={channel.name}
                    style={{
                      display: 'flex',
                      height: rowHeight,
                      borderBottom: '1px solid #4a5568', // Increased border width for better visibility
                      transition: 'height 0.2s ease',
                      position: 'relative', // Added for proper stacking
                      overflow: 'visible', // Changed from 'hidden' to 'visible' to allow expanded programs to overflow
                    }}
                  >
                    {/* Channel logo - sticky horizontally */}
                    <Box
                      className="channel-logo"
                      style={{
                        width: CHANNEL_WIDTH,
                        minWidth: CHANNEL_WIDTH,
                        flexShrink: 0,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        backgroundColor: '#2d3748',
                        borderRight: '1px solid #4a5568', // Increased border width for visibility
                        borderBottom: '1px solid #4a5568', // Match the row border
                        boxShadow: '2px 0 5px rgba(0,0,0,0.2)', // Added shadow for depth
                        position: 'sticky',
                        left: 0,
                        zIndex: 30, // Higher than expanded programs to prevent overlap
                        height: rowHeight,
                        transition: 'height 0.2s ease',
                      }}
                    >
                      {/* Logo content */}
                      <Flex
                        direction="column"
                        align="center"
                        justify="center"
                        style={{
                          maxWidth: CHANNEL_WIDTH * 0.8,
                          maxHeight: rowHeight * 0.9,
                        }}
                      >
                        <img
                          src={channel.logo?.cache_url || logo}
                          alt={channel.name}
                          style={{
                            width: '100%',
                            height: 'auto',
                            objectFit: 'contain',
                            maxHeight: rowHeight * 0.65,
                          }}
                        />
                        <Text
                          size="sm"
                          weight={600}
                          style={{
                            marginTop: 4,
                            backgroundColor: '#2d3748',
                            padding: '2px 6px',
                            borderRadius: 4,
                            fontSize: '0.85em',
                            border: '1px solid #4a5568',
                          }}
                        >
                          {channel.channel_number || '-'}
                        </Text>
                      </Flex>
                    </Box>

                    {/* Programs for this channel */}
                    <Box style={{
                      flex: 1,
                      position: 'relative',
                      height: rowHeight,
                      transition: 'height 0.2s ease',
                      paddingLeft: 0, // Remove any padding that might push content
                    }}>
                      {channelPrograms.map((prog) => renderProgram(prog, start))}
                    </Box>
                  </Box>
                );
              })
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
      </Box>

      {/* Modal removed since we're using expanded rows instead */}
    </Box>
  );
}

