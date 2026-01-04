import {
  convertToMs,
  initializeTime,
  startOfDay,
  isBefore,
  isAfter,
  isSame,
  add,
  diff,
  format,
  getNow,
  getNowMs,
  roundToNearest
} from '../utils/dateTimeUtils.js';
import API from '../api.js';

export const PROGRAM_HEIGHT = 90;
export const EXPANDED_PROGRAM_HEIGHT = 180;
/** Layout constants */
export const CHANNEL_WIDTH = 120; // Width of the channel/logo column
export const HOUR_WIDTH = 450; // Increased from 300 to 450 to make each program wider
export const MINUTE_INCREMENT = 15; // For positioning programs every 15 min
export const MINUTE_BLOCK_WIDTH = HOUR_WIDTH / (60 / MINUTE_INCREMENT);

export function buildChannelIdMap(channels, tvgsById, epgs = {}) {
  const map = new Map();
  channels.forEach((channel) => {
    const tvgRecord = channel.epg_data_id
      ? tvgsById[channel.epg_data_id]
      : null;
    
    // For dummy EPG sources, ALWAYS use channel UUID to ensure unique programs per channel
    // This prevents multiple channels with the same dummy EPG from showing identical data
    let tvgId;
    if (tvgRecord?.epg_source) {
      const epgSource = epgs[tvgRecord.epg_source];
      if (epgSource?.source_type === 'dummy') {
        // Dummy EPG: use channel UUID for uniqueness
        tvgId = channel.uuid;
      } else {
        // Regular EPG: use tvg_id from EPG data, or fall back to channel UUID
        tvgId = tvgRecord.tvg_id ?? channel.uuid;
      }
    } else {
      // No EPG data: use channel UUID
      tvgId = channel.uuid;
    }
    
    if (tvgId) {
      const tvgKey = String(tvgId);
      if (!map.has(tvgKey)) {
        map.set(tvgKey, []);
      }
      map.get(tvgKey).push(channel.id);
    }
  });
  return map;
}

export const mapProgramsByChannel = (programs, channelIdByTvgId) => {
  if (!programs?.length || !channelIdByTvgId?.size) {
    return new Map();
  }

  const map = new Map();
  const nowMs = getNowMs();

  programs.forEach((program) => {
    const channelIds = channelIdByTvgId.get(String(program.tvg_id));
    if (!channelIds || channelIds.length === 0) {
      return;
    }

    const startMs = program.startMs ?? convertToMs(program.start_time);
    const endMs = program.endMs ?? convertToMs(program.end_time);

    const programData = {
      ...program,
      startMs,
      endMs,
      programStart: initializeTime(program.startMs),
      programEnd: initializeTime(program.endMs),
      // Precompute live/past status
      isLive: nowMs >= program.startMs && nowMs < program.endMs,
      isPast: nowMs >= program.endMs,
    };

    // Add this program to all channels that share the same TVG ID
    channelIds.forEach((channelId) => {
      if (!map.has(channelId)) {
        map.set(channelId, []);
      }
      map.get(channelId).push(programData);
    });
  });

  map.forEach((list) => {
    list.sort((a, b) => a.startMs - b.startMs);
  });

  return map;
};

export function computeRowHeights(
  filteredChannels,
  programsByChannelId,
  expandedProgramId,
  defaultHeight = PROGRAM_HEIGHT,
  expandedHeight = EXPANDED_PROGRAM_HEIGHT
) {
  if (!filteredChannels?.length) {
    return [];
  }

  return filteredChannels.map((channel) => {
    const channelPrograms = programsByChannelId.get(channel.id) || [];
    const expanded = channelPrograms.some(
      (program) => program.id === expandedProgramId
    );
    return expanded ? expandedHeight : defaultHeight;
  });
}

export const fetchPrograms = async () => {
  console.log('Fetching program grid...');
  const fetched = await API.getGrid(); // GETs your EPG grid
  console.log(`Received ${fetched.length} programs`);

  return fetched.map((program) => {
    return {
      ...program,
      startMs: convertToMs(program.start_time),
      endMs: convertToMs(program.end_time),
    };
  });
};

export const sortChannels = (channels) => {
  // Include ALL channels, sorted by channel number - don't filter by EPG data
  const sortedChannels = Object.values(channels).sort(
      (a, b) =>
          (a.channel_number || Infinity) - (b.channel_number || Infinity)
  );

  console.log(`Using all ${sortedChannels.length} available channels`);
  return sortedChannels;
}

export const filterGuideChannels = (guideChannels, searchQuery, selectedGroupId, selectedProfileId, profiles) => {
  return guideChannels.filter((channel) => {
    // Search filter
    if (searchQuery) {
      if (!channel.name.toLowerCase().includes(searchQuery.toLowerCase())) return false;
    }

    // Channel group filter
    if (selectedGroupId !== 'all') {
      if (channel.channel_group_id !== parseInt(selectedGroupId)) return false;
    }

    // Profile filter
    if (selectedProfileId !== 'all') {
      const profileChannels = profiles[selectedProfileId]?.channels || [];
      const enabledChannelIds = Array.isArray(profileChannels)
          ? profileChannels.filter((pc) => pc.enabled).map((pc) => pc.id)
          : profiles[selectedProfileId]?.channels instanceof Set
              ? Array.from(profiles[selectedProfileId].channels)
              : [];

      if (!enabledChannelIds.includes(channel.id)) return false;
    }

    return true;
  });
}

export const calculateEarliestProgramStart = (programs, defaultStart) => {
  if (!programs.length) return defaultStart;
  return programs.reduce((acc, p) => {
    const s = initializeTime(p.start_time);
    return isBefore(s, acc) ? s : acc;
  }, defaultStart);
}

export const calculateLatestProgramEnd = (programs, defaultEnd) => {
  if (!programs.length) return defaultEnd;
  return programs.reduce((acc, p) => {
    const e = initializeTime(p.end_time);
    return isAfter(e, acc) ? e : acc;
  }, defaultEnd);
}

export const calculateStart = (earliestProgramStart, defaultStart) => {
  return isBefore(earliestProgramStart, defaultStart)
    ? earliestProgramStart
    : defaultStart;
}

export const calculateEnd = (latestProgramEnd, defaultEnd) => {
  return isAfter(latestProgramEnd, defaultEnd) ? latestProgramEnd : defaultEnd;
}

export const mapChannelsById = (guideChannels) => {
  const map = new Map();
  guideChannels.forEach((channel) => {
    map.set(channel.id, channel);
  });
  return map;
}

export const mapRecordingsByProgramId = (recordings) => {
  const map = new Map();
  (recordings || []).forEach((recording) => {
    const programId = recording?.custom_properties?.program?.id;
    if (programId != null) {
      map.set(programId, recording);
    }
  });
  return map;
}

export const formatTime = (time, dateFormat) => {
  const today = startOfDay(getNow());
  const tomorrow = add(today, 1, 'day');
  const weekLater = add(today, 7, 'day');
  const day = startOfDay(time);

  if (isSame(day, today, 'day')) {
    return 'Today';
  } else if (isSame(day, tomorrow, 'day')) {
    return 'Tomorrow';
  } else if (isBefore(day, weekLater)) {
    // Within a week, show day name
    return format(time, 'dddd');
  } else {
    // Beyond a week, show month and day
    return format(time, dateFormat);
  }
}

export const calculateHourTimeline = (start, end, formatDayLabel) => {
  const hours = [];
  let current = start;
  let currentDay = null;

  while (isBefore(current, end)) {
    // Check if we're entering a new day
    const day = startOfDay(current);
    const isNewDay = !currentDay || !isSame(day, currentDay, 'day');

    if (isNewDay) {
      currentDay = day;
    }

    // Add day information to our hour object
    hours.push({
      time: current,
      isNewDay,
      dayLabel: formatDayLabel(current),
    });

    current = add(current, 1, 'hour');
  }
  return hours;
}

export const calculateNowPosition = (now, start, end) => {
  if (isBefore(now, start) || isAfter(now, end)) return -1;
  const minutesSinceStart = diff(now, start, 'minute');
  return (minutesSinceStart / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH;
};

export const calculateScrollPosition = (now, start) => {
  const roundedNow = roundToNearest(now, 30);
  const nowOffset = diff(roundedNow, start, 'minute');
  const scrollPosition =
    (nowOffset / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH - MINUTE_BLOCK_WIDTH;

  return Math.max(scrollPosition, 0);
};

export const matchChannelByTvgId = (channelIdByTvgId, channelById, tvgId) => {
  const channelIds = channelIdByTvgId.get(String(tvgId));
  if (!channelIds || channelIds.length === 0) {
    return null;
  }
  // Return the first channel that matches this TVG ID
  return channelById.get(channelIds[0]) || null;
}

export const fetchRules = async () => {
  return await API.listSeriesRules();
}

export const getRuleByProgram = (rules, program) => {
  return (rules || []).find(
    (r) =>
      String(r.tvg_id) === String(program.tvg_id) &&
      (!r.title || r.title === program.title)
  );
}

export const createRecording = async (channel, program) => {
  await API.createRecording({
    channel: `${channel.id}`,
    start_time: program.start_time,
    end_time: program.end_time,
    custom_properties: { program },
  });
}

export const createSeriesRule = async (program, mode) => {
  await API.createSeriesRule({
    tvg_id: program.tvg_id,
    mode,
    title: program.title,
  });
}

export const evaluateSeriesRule = async (program) => {
  await API.evaluateSeriesRules(program.tvg_id);
}

export const calculateLeftScrollPosition = (program, start) => {
  const programStartMs =
    program.startMs ?? convertToMs(program.start_time);
  const startOffsetMinutes = (programStartMs - convertToMs(start)) / 60000;

  return (startOffsetMinutes / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH;
};

export const calculateDesiredScrollPosition = (leftPx) => {
  return Math.max(0, leftPx - 20);
}

export const calculateScrollPositionByTimeClick = (event, clickedTime, start) => {
  const rect = event.currentTarget.getBoundingClientRect();
  const clickPositionX = event.clientX - rect.left;
  const percentageAcross = clickPositionX / rect.width;
  const minuteWithinHour = percentageAcross * 60;

  const snappedMinute = Math.round(minuteWithinHour / 15) * 15;

  const adjustedTime = (snappedMinute === 60)
    ? add(clickedTime, 1, 'hour').minute(0)
    : clickedTime.minute(snappedMinute);

  const snappedOffset = diff(adjustedTime, start, 'minute');
  return (snappedOffset / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH;
};

export const getGroupOptions = (channelGroups, guideChannels) => {
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
}

export const getProfileOptions = (profiles) => {
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
}

export const deleteSeriesRuleByTvgId = async (tvg_id) => {
  await API.deleteSeriesRule(tvg_id);
}

export const evaluateSeriesRulesByTvgId = async (tvg_id) => {
  await API.evaluateSeriesRules(tvg_id);
}