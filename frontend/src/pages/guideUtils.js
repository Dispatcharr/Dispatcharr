import dayjs from 'dayjs';

export const PROGRAM_HEIGHT = 90;
export const EXPANDED_PROGRAM_HEIGHT = 180;

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

export function mapProgramsByChannel(programs, channelIdByTvgId) {
  if (!programs?.length || !channelIdByTvgId?.size) {
    return new Map();
  }

  const map = new Map();
  programs.forEach((program) => {
    const channelIds = channelIdByTvgId.get(String(program.tvg_id));
    if (!channelIds || channelIds.length === 0) {
      return;
    }

    const startMs = program.startMs ?? dayjs(program.start_time).valueOf();
    const endMs = program.endMs ?? dayjs(program.end_time).valueOf();

    const programData = {
      ...program,
      startMs,
      endMs,
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
}

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
