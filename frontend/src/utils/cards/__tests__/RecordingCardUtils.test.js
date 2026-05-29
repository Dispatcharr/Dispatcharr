import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  removeRecording, getPosterUrl, getShowVideoUrl, runComSkip,
  deleteRecordingById, deleteSeriesAndRule, getRecordingUrl, getSeasonLabel, getSeriesInfo,
} from '../RecordingCardUtils';
import API from '../../../api';
import useChannelsStore from '../../../store/channels';

vi.mock('../../../api');
vi.mock('../../../store/channels');

describe('RecordingCardUtils', () => {
  beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); });

  describe('getShowVideoUrl', () => {
    it('returns proxy URL with mpegts output format', () => {
      expect(getShowVideoUrl({ uuid: 'channel-123' }, 'production'))
        .toBe('/proxy/ts/stream/channel-123?output_format=mpegts');
    });
    it('includes output_profile when set in player prefs', () => {
      localStorage.setItem('dispatcharr-player-prefs', JSON.stringify({ webPlayerOutputProfileId: 5 }));
      expect(getShowVideoUrl({ uuid: 'channel-123' }, 'production'))
        .toBe('/proxy/ts/stream/channel-123?output_format=mpegts&output_profile=5');
    });
    it('prepends dev server URL in dev mode with output params', () => {
      expect(getShowVideoUrl({ uuid: 'channel-123' }, 'dev')).toMatch(/^https?:\/\/.*:5656\/proxy\/ts\/stream\/channel-123\?output_format=mpegts$/);
    });
  });

  describe('removeRecording', () => {
    let mockRemoveRecording, mockFetchRecordings;
    beforeEach(() => {
      mockRemoveRecording = vi.fn(); mockFetchRecordings = vi.fn();
      useChannelsStore.getState = vi.fn(() => ({ removeRecording: mockRemoveRecording, fetchRecordings: mockFetchRecordings }));
    });
    it('optimistically removes recording from store', () => {
      API.deleteRecording.mockResolvedValue();
      removeRecording('recording-1');
      expect(mockRemoveRecording).toHaveBeenCalledWith('recording-1');
    });
    it('calls API to delete recording', () => {
      API.deleteRecording.mockResolvedValue();
      removeRecording('recording-1');
      expect(API.deleteRecording).toHaveBeenCalledWith('recording-1');
    });
    it('refetches recordings when API delete fails', async () => {
      API.deleteRecording.mockRejectedValue(new Error('Delete failed'));
      removeRecording('recording-1');
      await vi.waitFor(() => { expect(mockFetchRecordings).toHaveBeenCalled(); });
    });
  });

  describe('runComSkip', () => {
    it('calls API runComskip with recording id', async () => {
      API.runComskip.mockResolvedValue();
      await runComSkip({ id: 'recording-1' });
      expect(API.runComskip).toHaveBeenCalledWith('recording-1');
    });
  });

  describe('deleteRecordingById', () => {
    it('calls API deleteRecording with id', async () => {
      API.deleteRecording.mockResolvedValue();
      await deleteRecordingById('recording-1');
      expect(API.deleteRecording).toHaveBeenCalledWith('recording-1');
    });
  });

  describe('getRecordingUrl', () => {
    it('returns file_url when available', () => {
      expect(getRecordingUrl({ file_url: '/recordings/file.mp4' }, 'production')).toBe('/recordings/file.mp4');
    });
    it('returns undefined when no file URL available', () => {
      expect(getRecordingUrl({}, 'production')).toBeUndefined();
    });
    it('handles null customProps', () => {
      expect(getRecordingUrl(null, 'production')).toBeUndefined();
    });
  });

  describe('getSeasonLabel', () => {
    it('returns formatted label', () => { expect(getSeasonLabel(1, 5, null)).toBe('S01E05'); });
    it('returns onscreen when season missing', () => { expect(getSeasonLabel(null, 5, 'Episode 5')).toBe('Episode 5'); });
    it('returns null when nothing provided', () => { expect(getSeasonLabel(null, null, null)).toBeNull(); });
  });

  describe('getSeriesInfo', () => {
    it('extracts tvg_id and title', () => {
      expect(getSeriesInfo({ program: { tvg_id: 'series-123', title: 'Test Series' } }))
        .toEqual({ tvg_id: 'series-123', title: 'Test Series' });
    });
    it('handles null', () => { expect(getSeriesInfo(null)).toEqual({ tvg_id: undefined, title: undefined }); });
  });
});
