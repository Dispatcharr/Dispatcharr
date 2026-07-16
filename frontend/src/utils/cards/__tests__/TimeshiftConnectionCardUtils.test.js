import { describe, it, expect } from 'vitest';
import {
  computeCatchupPlaybackSeconds,
  parseCatchupTimestampMs,
} from '../TimeshiftConnectionCardUtils.js';

describe('parseCatchupTimestampMs', () => {
  it('parses colon-dash catch-up timestamps as UTC', () => {
    const ms = parseCatchupTimestampMs('2026-07-10:14-19');
    expect(new Date(ms).toISOString()).toBe('2026-07-10T14:19:00.000Z');
  });
});

describe('computeCatchupPlaybackSeconds', () => {
  it('combines URL offset with elapsed time since anchor', () => {
    const epgStart = '2026-07-10T14:00:00+00:00';
    const position = computeCatchupPlaybackSeconds({
      programmeStart: '2026-07-10:14-19',
      programStartTime: epgStart,
      programDurationSecs: 3600,
      positionAnchorAt: 1000,
      nowMs: 1030 * 1000,
    });
    expect(position).toBeCloseTo(19 * 60 + 30, 5);
  });

  it('uses playback base for byte-range seeks', () => {
    const position = computeCatchupPlaybackSeconds({
      programmeStart: '2026-07-10:14-00',
      programStartTime: '2026-07-10T14:00:00+00:00',
      programDurationSecs: 3600,
      positionAnchorAt: 1000,
      playbackBaseSecs: 1800,
      nowMs: 1030 * 1000,
    });
    expect(position).toBeCloseTo(1830, 5);
  });

  it('does not advance while paused', () => {
    const position = computeCatchupPlaybackSeconds({
      programmeStart: '2026-07-10:14-00',
      programStartTime: '2026-07-10T14:00:00+00:00',
      programDurationSecs: 3600,
      positionAnchorAt: 1000,
      playbackBaseSecs: 900,
      paused: true,
      nowMs: 1300 * 1000,
    });
    expect(position).toBeCloseTo(900, 5);
  });
});
