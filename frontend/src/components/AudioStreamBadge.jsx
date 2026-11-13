import { Badge, Tooltip } from '@mantine/core';
import {
  formatAudioStreamsTooltip,
  formatBestAudioBadge,
} from '../utils/audioStreamUtils.js';

/** Pink audio badge shared by the live card, the timeshift card and the streams table. */
const AudioStreamBadge = ({ stats, size = 'sm' }) => {
  if (!stats?.audio_codec && !stats?.audio_channels) return null;

  const streams = stats.audio_streams;
  const label =
    Array.isArray(streams) && streams.length > 0
      ? formatAudioStreamsTooltip(streams)
      : 'Audio track';

  return (
    <Tooltip
      label={label}
      multiline
      maw={420}
      style={{ whiteSpace: 'pre-line' }}
    >
      <Badge
        size={size}
        variant="light"
        color="pink"
        style={{ textTransform: 'none' }}
      >
        {formatBestAudioBadge(stats)}
      </Badge>
    </Tooltip>
  );
};

export default AudioStreamBadge;
