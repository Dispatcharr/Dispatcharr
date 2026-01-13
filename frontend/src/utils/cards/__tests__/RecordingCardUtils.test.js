import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  removeRecording,
  getPosterUrl,
  getShowVideoUrl,
  runComSkip,
  deleteRecordingById,
  deleteSeriesAndRule,
  getRecordingUrl,
  getSeasonLabel,
  getSeriesInfo,
} from '../RecordingCardUtils';
import API from '../../../api';
import useChannelsStore from '../../../store/channels';

vi.mock('../../../api');
vi.mock('../../../store/channels');

describe('RecordingCardUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('removeRecording', () => {
    let mockRemoveRecording;
    let mockFetchRecordings;

    beforeEach(() => {
      mockRemoveRecording = vi.fn();
      mockFetchRecordings = vi.fn();
      useChannelsStore.getState = vi.fn(() => ({
        removeRecording: mockRemoveRecording,
        fetchRecordings: mockFetchRecordings,
      }));
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

    it('handles optimistic removal error', () => {
      const consoleError = vi.spyOn(console, 'error').mockImplementation();
      mockRemoveRecording.mockImplementation(() => {
        throw new Error('Store error');
      });
      API.deleteRecording.mockResolvedValue();

      removeRecording('recording-1');

      expect(consoleError).toHaveBeenCalledWith(
        'Failed to optimistically remove recording',
        expect.any(Error)
      );
      consoleError.mockRestore();
    });

    it('refetches recordings when API delete fails', async () => {
      API.deleteRecording.mockRejectedValue(new Error('Delete failed'));

      removeRecording('recording-1');

      await vi.waitFor(() => {
        expect(mockFetchRecordings).toHaveBeenCalled();
      });
    });

    it('handles fetch error after failed delete', async () => {
      const consoleError = vi.spyOn(console, 'error').mockImplementation();
      API.deleteRecording.mockRejectedValue(new Error('Delete failed'));
      mockFetchRecordings.mockImplementation(() => {
        throw new Error('Fetch error');
      });

      removeRecording('recording-1');

      await vi.waitFor(() => {
        expect(consoleError).toHaveBeenCalledWith(
          'Failed to refresh recordings after delete',
          expect.any(Error)
        );
      });
      consoleError.mockRestore();
    });
  });

  describe('getPosterUrl', () => {
    afterEach(() => {
      vi.unstubAllEnvs();
    });

    it('returns logo URL when posterLogoId is provided', () => {
      vi.stubEnv('DEV', false);
      const result = getPosterUrl('logo-123', {}, '');

      expect(result).toBe('/api/channels/logos/logo-123/cache/');
    });

    it('returns custom poster_url when no posterLogoId', () => {
      vi.stubEnv('DEV', false);
      const customProps = { poster_url: '/custom/poster.jpg' };
      const result = getPosterUrl(null, customProps, '');

      expect(result).toBe('/custom/poster.jpg');
    });

    it('returns posterUrl when no posterLogoId or custom poster_url', () => {
      vi.stubEnv('DEV', false);
      const result = getPosterUrl(null, {}, '/fallback/poster.jpg');

      expect(result).toBe('/fallback/poster.jpg');
    });

    it('returns default logo when no parameters provided', () => {
      vi.stubEnv('DEV', false);
      const result = getPosterUrl(null, {}, '');

      expect(result).toBe('/logo.png');
    });

    it('prepends dev server URL in dev mode for relative paths', () => {
      vi.stubEnv('DEV', true);
      const result = getPosterUrl(null, {}, '/poster.jpg');

      expect(result).toMatch(/^https?:\/\/.*:5656\/poster\.jpg$/);
    });

    it('does not prepend dev URL for absolute URLs', () => {
      vi.stubEnv('DEV', true);
      const result = getPosterUrl(null, {}, 'https://example.com/poster.jpg');

      expect(result).toBe('https://example.com/poster.jpg');
    });
  });

  describe('getShowVideoUrl', () => {
    it('returns proxy URL for channel', () => {
      const channel = { uuid: 'channel-123' };
      const result = getShowVideoUrl(channel, 'production');

      expect(result).toBe('/proxy/ts/stream/channel-123');
    });

    it('prepends dev server URL in dev mode', () => {
      const channel = { uuid: 'channel-123' };
      const result = getShowVideoUrl(channel, 'dev');

      expect(result).toMatch(/^https?:\/\/.*:5656\/proxy\/ts\/stream\/channel-123$/);
    });
  });

  describe('runComSkip', () => {
    it('calls API runComskip with recording id', async () => {
      API.runComskip.mockResolvedValue();
      const recording = { id: 'recording-1' };

      await runComSkip(recording);

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

  describe('deleteSeriesAndRule', () => {
    it('removes series recordings and deletes series rule', async () => {
      API.bulkRemoveSeriesRecordings.mockResolvedValue();
      API.deleteSeriesRule.mockResolvedValue();
      const seriesInfo = { tvg_id: 'series-123', title: 'Test Series' };

      await deleteSeriesAndRule(seriesInfo);

      expect(API.bulkRemoveSeriesRecordings).toHaveBeenCalledWith({
        tvg_id: 'series-123',
        title: 'Test Series',
        scope: 'title',
      });
      expect(API.deleteSeriesRule).toHaveBeenCalledWith('series-123');
    });

    it('does nothing when tvg_id is not provided', async () => {
      const seriesInfo = { title: 'Test Series' };

      await deleteSeriesAndRule(seriesInfo);

      expect(API.bulkRemoveSeriesRecordings).not.toHaveBeenCalled();
      expect(API.deleteSeriesRule).not.toHaveBeenCalled();
    });

    it('handles bulk remove error gracefully', async () => {
      const consoleError = vi.spyOn(console, 'error').mockImplementation();
      API.bulkRemoveSeriesRecordings.mockRejectedValue(new Error('Bulk remove failed'));
      API.deleteSeriesRule.mockResolvedValue();
      const seriesInfo = { tvg_id: 'series-123', title: 'Test Series' };

      await deleteSeriesAndRule(seriesInfo);

      expect(consoleError).toHaveBeenCalledWith(
        'Failed to remove series recordings',
        expect.any(Error)
      );
      expect(API.deleteSeriesRule).toHaveBeenCalled();
      consoleError.mockRestore();
    });

    it('handles delete rule error gracefully', async () => {
      const consoleError = vi.spyOn(console, 'error').mockImplementation();
      API.bulkRemoveSeriesRecordings.mockResolvedValue();
      API.deleteSeriesRule.mockRejectedValue(new Error('Delete rule failed'));
      const seriesInfo = { tvg_id: 'series-123', title: 'Test Series' };

      await deleteSeriesAndRule(seriesInfo);

      expect(consoleError).toHaveBeenCalledWith(
        'Failed to delete series rule',
        expect.any(Error)
      );
      consoleError.mockRestore();
    });
  });

  describe('getRecordingUrl', () => {
    it('returns file_url when available', () => {
      const customProps = { file_url: '/recordings/file.mp4' };
      const result = getRecordingUrl(customProps, 'production');

      expect(result).toBe('/recordings/file.mp4');
    });

    it('returns output_file_url when file_url is not available', () => {
      const customProps = { output_file_url: '/output/file.mp4' };
      const result = getRecordingUrl(customProps, 'production');

      expect(result).toBe('/output/file.mp4');
    });

    it('prefers file_url over output_file_url', () => {
      const customProps = {
        file_url: '/recordings/file.mp4',
        output_file_url: '/output/file.mp4',
      };
      const result = getRecordingUrl(customProps, 'production');

      expect(result).toBe('/recordings/file.mp4');
    });

    it('prepends dev server URL in dev mode for relative paths', () => {
      const customProps = { file_url: '/recordings/file.mp4' };
      const result = getRecordingUrl(customProps, 'dev');

      expect(result).toMatch(/^https?:\/\/.*:5656\/recordings\/file\.mp4$/);
    });

    it('does not prepend dev URL for absolute URLs', () => {
      const customProps = { file_url: 'https://example.com/file.mp4' };
      const result = getRecordingUrl(customProps, 'dev');

      expect(result).toBe('https://example.com/file.mp4');
    });

    it('returns undefined when no file URL is available', () => {
      const result = getRecordingUrl({}, 'production');

      expect(result).toBeUndefined();
    });

    it('handles null customProps', () => {
      const result = getRecordingUrl(null, 'production');

      expect(result).toBeUndefined();
    });
  });

  describe('getSeasonLabel', () => {
    it('returns formatted season and episode label', () => {
      const result = getSeasonLabel(1, 5, null);

      expect(result).toBe('S01E05');
    });

    it('pads single digit season and episode numbers', () => {
      const result = getSeasonLabel(2, 3, null);

      expect(result).toBe('S02E03');
    });

    it('handles multi-digit season and episode numbers', () => {
      const result = getSeasonLabel(12, 34, null);

      expect(result).toBe('S12E34');
    });

    it('returns onscreen value when season or episode is missing', () => {
      const result = getSeasonLabel(null, 5, 'Episode 5');

      expect(result).toBe('Episode 5');
    });

    it('returns onscreen value when only episode is missing', () => {
      const result = getSeasonLabel(1, null, 'Special');

      expect(result).toBe('Special');
    });

    it('returns null when no season, episode, or onscreen provided', () => {
      const result = getSeasonLabel(null, null, null);

      expect(result).toBeNull();
    });

    it('returns formatted label even when onscreen is provided', () => {
      const result = getSeasonLabel(1, 5, 'Episode 5');

      expect(result).toBe('S01E05');
    });
  });

  describe('getSeriesInfo', () => {
    it('extracts tvg_id and title from program', () => {
      const customProps = {
        program: { tvg_id: 'series-123', title: 'Test Series' },
      };
      const result = getSeriesInfo(customProps);

      expect(result).toEqual({
        tvg_id: 'series-123',
        title: 'Test Series',
      });
    });

    it('handles missing program object', () => {
      const customProps = {};
      const result = getSeriesInfo(customProps);

      expect(result).toEqual({
        tvg_id: undefined,
        title: undefined,
      });
    });

    it('handles null customProps', () => {
      const result = getSeriesInfo(null);

      expect(result).toEqual({
        tvg_id: undefined,
        title: undefined,
      });
    });

    it('handles undefined customProps', () => {
      const result = getSeriesInfo(undefined);

      expect(result).toEqual({
        tvg_id: undefined,
        title: undefined,
      });
    });

    it('handles partial program data', () => {
      const customProps = {
        program: { tvg_id: 'series-123' },
      };
      const result = getSeriesInfo(customProps);

      expect(result).toEqual({
        tvg_id: 'series-123',
        title: undefined,
      });
    });
  });
});
