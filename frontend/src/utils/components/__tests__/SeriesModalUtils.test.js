import { describe, it, expect, beforeEach } from 'vitest';
import {
  imdbUrl,
  tmdbUrl,
  formatDuration,
  formatStreamLabel,
  sortEpisodesList,
  groupEpisodesBySeason,
  sortBySeasonNumber,
  getEpisodeStreamUrl,
  getYouTubeEmbedUrl,
  getEpisodeAirdate,
  getTmdbUrlLink
} from '../SeriesModalUtils';

describe('SeriesModalUtils', () => {
  describe('imdbUrl', () => {
    it('should return IMDb URL with valid ID', () => {
      expect(imdbUrl('tt1234567')).toBe('https://www.imdb.com/title/tt1234567');
    });

    it('should return empty string when ID is null', () => {
      expect(imdbUrl(null)).toBe('');
    });

    it('should return empty string when ID is undefined', () => {
      expect(imdbUrl(undefined)).toBe('');
    });
  });

  describe('tmdbUrl', () => {
    it('should return TMDB movie URL by default', () => {
      expect(tmdbUrl('12345')).toBe('https://www.themoviedb.org/movie/12345');
    });

    it('should return TMDB TV URL when type is tv', () => {
      expect(tmdbUrl('12345', 'tv')).toBe('https://www.themoviedb.org/tv/12345');
    });

    it('should return empty string when ID is null', () => {
      expect(tmdbUrl(null)).toBe('');
    });
  });

  describe('formatDuration', () => {
    it('should format hours and minutes', () => {
      expect(formatDuration(7200)).toBe('2h 0m');
    });

    it('should format hours, minutes and seconds', () => {
      expect(formatDuration(3665)).toBe('1h 1m');
    });

    it('should format minutes and seconds when under an hour', () => {
      expect(formatDuration(125)).toBe('2m 5s');
    });

    it('should return empty string for 0 seconds', () => {
      expect(formatDuration(0)).toBe('');
    });

    it('should return empty string for null', () => {
      expect(formatDuration(null)).toBe('');
    });
  });

  describe('formatStreamLabel', () => {
    const baseRelation = {
      m3u_account: { name: 'Provider 1' },
      stream_id: 100
    };

    it('should format label with quality from quality_info', () => {
      const relation = {
        ...baseRelation,
        quality_info: { quality: '1080p' }
      };
      expect(formatStreamLabel(relation)).toBe('Provider 1 - 1080p (Stream 100)');
    });

    it('should format label with quality from resolution', () => {
      const relation = {
        ...baseRelation,
        quality_info: { resolution: '4K' }
      };
      expect(formatStreamLabel(relation)).toBe('Provider 1 - 4K (Stream 100)');
    });

    it('should format label with quality from bitrate', () => {
      const relation = {
        ...baseRelation,
        quality_info: { bitrate: '8000kbps' }
      };
      expect(formatStreamLabel(relation)).toBe('Provider 1 - 8000kbps (Stream 100)');
    });

    it('should detect 4K from video dimensions', () => {
      const relation = {
        ...baseRelation,
        custom_properties: {
          detailed_info: {
            video: { width: 3840, height: 2160 }
          }
        }
      };
      expect(formatStreamLabel(relation)).toBe('Provider 1 - 4K (Stream 100)');
    });

    it('should detect 1080p from video dimensions', () => {
      const relation = {
        ...baseRelation,
        custom_properties: {
          detailed_info: {
            video: { width: 1920, height: 1080 }
          }
        }
      };
      expect(formatStreamLabel(relation)).toBe('Provider 1 - 1080p (Stream 100)');
    });

    it('should detect 720p from video dimensions', () => {
      const relation = {
        ...baseRelation,
        custom_properties: {
          detailed_info: {
            video: { width: 1280, height: 720 }
          }
        }
      };
      expect(formatStreamLabel(relation)).toBe('Provider 1 - 720p (Stream 100)');
    });

    it('should show custom dimensions for non-standard resolutions', () => {
      const relation = {
        ...baseRelation,
        custom_properties: {
          detailed_info: {
            video: { width: 640, height: 480 }
          }
        }
      };
      expect(formatStreamLabel(relation)).toBe('Provider 1 - 640x480 (Stream 100)');
    });

    it('should detect quality from detailed_info name field', () => {
      const relation = {
        ...baseRelation,
        custom_properties: {
          detailed_info: {
            name: 'Stream 4K HDR'
          }
        }
      };
      expect(formatStreamLabel(relation)).toBe('Provider 1 - 4K (Stream 100)');
    });

    it('should detect quality from stream_name', () => {
      const relation = {
        ...baseRelation,
        stream_name: 'Channel 1080p FHD'
      };
      expect(formatStreamLabel(relation)).toBe('Provider 1 - 1080p (Stream 100)');
    });

    it('should detect 2160p as 4K', () => {
      const relation = {
        ...baseRelation,
        stream_name: 'Stream 2160p'
      };
      expect(formatStreamLabel(relation)).toBe('Provider 1 - 4K (Stream 100)');
    });

    it('should detect FHD as 1080p', () => {
      const relation = {
        ...baseRelation,
        stream_name: 'Stream FHD'
      };
      expect(formatStreamLabel(relation)).toBe('Provider 1 - 1080p (Stream 100)');
    });

    it('should detect HD as 720p', () => {
      const relation = {
        ...baseRelation,
        stream_name: 'Stream HD'
      };
      expect(formatStreamLabel(relation)).toBe('Provider 1 - 720p (Stream 100)');
    });

    it('should format without stream ID when not provided', () => {
      const relation = {
        m3u_account: { name: 'Provider 1' },
        quality_info: { quality: '1080p' }
      };
      expect(formatStreamLabel(relation)).toBe('Provider 1 - 1080p');
    });

    it('should format without quality when not detected', () => {
      const relation = {
        m3u_account: { name: 'Provider 1' },
        stream_id: 100
      };
      expect(formatStreamLabel(relation)).toBe('Provider 1 (Stream 100)');
    });

    it('should prioritize quality_info over detailed_info', () => {
      const relation = {
        ...baseRelation,
        quality_info: { quality: '4K' },
        custom_properties: {
          detailed_info: {
            video: { width: 1920, height: 1080 }
          }
        }
      };
      expect(formatStreamLabel(relation)).toBe('Provider 1 - 4K (Stream 100)');
    });
  });

  describe('sortEpisodesList', () => {
    it('should sort episodes by season then episode number', () => {
      const episodes = [
        { season_number: 2, episode_number: 1 },
        { season_number: 1, episode_number: 2 },
        { season_number: 1, episode_number: 1 }
      ];
      const sorted = sortEpisodesList(episodes);
      expect(sorted).toEqual([
        { season_number: 1, episode_number: 1 },
        { season_number: 1, episode_number: 2 },
        { season_number: 2, episode_number: 1 }
      ]);
    });

    it('should handle missing season numbers as 0', () => {
      const episodes = [
        { season_number: 1, episode_number: 1 },
        { episode_number: 1 }
      ];
      const sorted = sortEpisodesList(episodes);
      expect(sorted[0].season_number).toBeUndefined();
    });
  });

  describe('groupEpisodesBySeason', () => {
    it('should group episodes by season number', () => {
      const episodes = [
        { season_number: 1, episode_number: 1 },
        { season_number: 1, episode_number: 2 },
        { season_number: 2, episode_number: 1 }
      ];
      const grouped = groupEpisodesBySeason(episodes);
      expect(grouped[1]).toHaveLength(2);
      expect(grouped[2]).toHaveLength(1);
    });

    it('should default missing season numbers to 1', () => {
      const episodes = [{ episode_number: 1 }];
      const grouped = groupEpisodesBySeason(episodes);
      expect(grouped[1]).toHaveLength(1);
    });
  });

  describe('sortBySeasonNumber', () => {
    it('should return season numbers in ascending order', () => {
      const episodesBySeason = {
        3: [],
        1: [],
        2: []
      };
      const sorted = sortBySeasonNumber(episodesBySeason);
      expect(sorted).toEqual([1, 2, 3]);
    });
  });

  describe('getEpisodeStreamUrl', () => {
    beforeEach(() => {
      delete window.location;
      window.location = {
        protocol: 'https:',
        hostname: 'example.com',
        origin: 'https://example.com'
      };
    });

    it('should generate stream URL without provider in production', () => {
      const episode = { uuid: 'episode-123' };
      const url = getEpisodeStreamUrl(episode, null, 'prod');
      expect(url).toBe('https://example.com/proxy/vod/episode/episode-123');
    });

    it('should generate stream URL with stream_id parameter', () => {
      const episode = { uuid: 'episode-123' };
      const provider = {
        stream_id: 'stream-456',
        m3u_account: { id: 1 }
      };
      const url = getEpisodeStreamUrl(episode, provider, 'prod');
      expect(url).toBe('https://example.com/proxy/vod/episode/episode-123?stream_id=stream-456');
    });

    it('should generate stream URL with m3u_account_id when no stream_id', () => {
      const episode = { uuid: 'episode-123' };
      const provider = {
        m3u_account: { id: 1 }
      };
      const url = getEpisodeStreamUrl(episode, provider, 'prod');
      expect(url).toBe('https://example.com/proxy/vod/episode/episode-123?m3u_account_id=1');
    });

    it('should use dev port in dev mode', () => {
      const episode = { uuid: 'episode-123' };
      const url = getEpisodeStreamUrl(episode, null, 'dev');
      expect(url).toBe('https://example.com:5656/proxy/vod/episode/episode-123');
    });

    it('should encode special characters in stream_id', () => {
      const episode = { uuid: 'episode-123' };
      const provider = {
        stream_id: 'stream with spaces',
        m3u_account: { id: 1 }
      };
      const url = getEpisodeStreamUrl(episode, provider, 'prod');
      expect(url).toContain('stream%20with%20spaces');
    });
  });

  describe('getYouTubeEmbedUrl', () => {
    it('should convert youtube.com watch URL to embed URL', () => {
      const url = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ';
      expect(getYouTubeEmbedUrl(url)).toBe('https://www.youtube.com/embed/dQw4w9WgXcQ');
    });

    it('should convert youtu.be URL to embed URL', () => {
      const url = 'https://youtu.be/dQw4w9WgXcQ';
      expect(getYouTubeEmbedUrl(url)).toBe('https://www.youtube.com/embed/dQw4w9WgXcQ');
    });

    it('should handle bare video ID', () => {
      const videoId = 'dQw4w9WgXcQ';
      expect(getYouTubeEmbedUrl(videoId)).toBe('https://www.youtube.com/embed/dQw4w9WgXcQ');
    });

    it('should return empty string for null', () => {
      expect(getYouTubeEmbedUrl(null)).toBe('');
    });

    it('should return empty string for empty string', () => {
      expect(getYouTubeEmbedUrl('')).toBe('');
    });
  });

  describe('getEpisodeAirdate', () => {
    it('should format valid air date', () => {
      const episode = { air_date: '2024-01-15' };
      const formatted = getEpisodeAirdate(episode);
      expect(formatted).toMatch(/1\/1[4|5]\/2024/);
    });

    it('should return N/A for missing air date', () => {
      const episode = {};
      expect(getEpisodeAirdate(episode)).toBe('N/A');
    });

    it('should return N/A for null air date', () => {
      const episode = { air_date: null };
      expect(getEpisodeAirdate(episode)).toBe('N/A');
    });
  });

  describe('getTmdbUrlLink', () => {
    const displaySeries = { tmdb_id: '12345' };

    it('should return TV show URL without episode details', () => {
      const episode = {};
      const url = getTmdbUrlLink(displaySeries, episode);
      expect(url).toBe('https://www.themoviedb.org/tv/12345');
    });

    it('should return TV show URL with season and episode', () => {
      const episode = { season_number: 2, episode_number: 5 };
      const url = getTmdbUrlLink(displaySeries, episode);
      expect(url).toBe('https://www.themoviedb.org/tv/12345/season/2/episode/5');
    });

    it('should not append episode details if only season is present', () => {
      const episode = { season_number: 2 };
      const url = getTmdbUrlLink(displaySeries, episode);
      expect(url).toBe('https://www.themoviedb.org/tv/12345');
    });

    it('should not append episode details if only episode is present', () => {
      const episode = { episode_number: 5 };
      const url = getTmdbUrlLink(displaySeries, episode);
      expect(url).toBe('https://www.themoviedb.org/tv/12345');
    });
  });
});
