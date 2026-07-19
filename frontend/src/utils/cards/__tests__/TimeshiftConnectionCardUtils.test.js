import { describe, it, expect } from 'vitest';
import {
  computeCatchupPlaybackSeconds,
  computeCatchupArchivePositionSecs,
  isCatchupPlayheadOutsideProgram,
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

  it('rebases byte-range playhead onto a later displayed programme', () => {
    const position = computeCatchupPlaybackSeconds({
      programmeStart: '2026-07-10:14-00',
      programStartTime: '2026-07-10T14:30:00+00:00',
      programDurationSecs: 1800,
      positionAnchorAt: 1000,
      playbackBaseSecs: 1900,
      nowMs: 1000 * 1000,
    });
    // 1900s from 14:00 is 100s into the 14:30 programme.
    expect(position).toBeCloseTo(100, 5);
  });

  it('can return uncapped position past programme end', () => {
    const position = computeCatchupPlaybackSeconds({
      programmeStart: '2026-07-10:14-00',
      programStartTime: '2026-07-10T14:00:00+00:00',
      programDurationSecs: 1800,
      positionAnchorAt: 1000,
      playbackBaseSecs: 1790,
      nowMs: 1040 * 1000,
      capToDuration: false,
    });
    expect(position).toBeCloseTo(1830, 5);
  });
});

describe('isCatchupPlayheadOutsideProgram', () => {
  it('is false while playhead is inside the programme', () => {
    expect(
      isCatchupPlayheadOutsideProgram({
        programmeStart: '2026-07-10:14-00',
        programStartTime: '2026-07-10T14:00:00+00:00',
        programDurationSecs: 1800,
        positionAnchorAt: 1000,
        playbackBaseSecs: 900,
        nowMs: 1000 * 1000,
      })
    ).toBe(false);
  });

  it('is true once playhead reaches programme end', () => {
    expect(
      isCatchupPlayheadOutsideProgram({
        programmeStart: '2026-07-10:14-00',
        programStartTime: '2026-07-10T14:00:00+00:00',
        programDurationSecs: 1800,
        positionAnchorAt: 1000,
        playbackBaseSecs: 1800,
        nowMs: 1000 * 1000,
      })
    ).toBe(true);
  });

  it('detects leaving a later displayed programme', () => {
    expect(
      isCatchupPlayheadOutsideProgram({
        programmeStart: '2026-07-10:14-00',
        programStartTime: '2026-07-10T14:30:00+00:00',
        programDurationSecs: 1800,
        positionAnchorAt: 1000,
        playbackBaseSecs: 3600,
        nowMs: 1000 * 1000,
      })
    ).toBe(true);
  });

  it('detects rewind before a later displayed programme', () => {
    expect(
      isCatchupPlayheadOutsideProgram({
        programmeStart: '2026-07-10:14-00',
        programStartTime: '2026-07-10T14:30:00+00:00',
        programDurationSecs: 1800,
        positionAnchorAt: 1000,
        playbackBaseSecs: 1200,
        nowMs: 1000 * 1000,
      })
    ).toBe(true);
  });
});

describe('computeCatchupArchivePositionSecs', () => {
  it('returns uncapped absolute playhead from playback base', () => {
    const position = computeCatchupArchivePositionSecs({
      programmeStart: '2026-07-10:14-00',
      programStartTime: '2026-07-10T14:00:00+00:00',
      positionAnchorAt: 1000,
      playbackBaseSecs: 1900,
      nowMs: 1030 * 1000,
    });
    expect(position).toBeCloseTo(1930, 5);
  });

  it('keeps URL-relative base after the card advances to a later programme', () => {
    const position = computeCatchupArchivePositionSecs({
      programmeStart: '2026-07-10:14-00',
      programStartTime: '2026-07-10T14:30:00+00:00',
      positionAnchorAt: 1000,
      playbackBaseSecs: 1900,
      nowMs: 1000 * 1000,
    });
    expect(position).toBeCloseTo(1900, 5);
  });
});
