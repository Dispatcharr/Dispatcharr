import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import FloatingVideo from '../FloatingVideo';
import useVideoStore from '../../store/useVideoStore';

// Mock the video store
vi.mock('../../store/useVideoStore');

// Mock mpegts.js
vi.mock('mpegts.js', () => ({
  default: {
    createPlayer: vi.fn(),
    getFeatureList: vi.fn(),
    Events: {
      LOADING_COMPLETE: 'loading_complete',
      METADATA_ARRIVED: 'metadata_arrived',
      ERROR: 'error',
      MEDIA_INFO: 'media_info',
    },
  },
}));

const mockHlsInstance = {
  attachMedia: vi.fn(),
  loadSource: vi.fn(),
  destroy: vi.fn(),
  on: vi.fn(),
};

let capturedHlsConfig = null;
let forceHlsInitError = false;

vi.mock('hls.js', () => ({
  default: class MockHls {
    static isSupported = vi.fn(() => true);

    static Events = {
      ERROR: 'error',
      MEDIA_ATTACHED: 'media_attached',
    };

    static ErrorTypes = {
      NETWORK_ERROR: 'networkError',
      MEDIA_ERROR: 'mediaError',
    };

    constructor(config) {
      if (forceHlsInitError) {
        throw new Error('Illegal hls.js config');
      }
      capturedHlsConfig = config;
      Object.assign(this, mockHlsInstance);
    }
  },
}));

vi.mock('../../store/auth', () => ({
  default: {
    getState: vi.fn(() => ({ accessToken: 'test-token' })),
  },
}));

// Import the mocked module after mocking
const mpegts = (await import('mpegts.js')).default;
const Hls = (await import('hls.js')).default;

// Mock react-draggable
vi.mock('react-draggable', () => ({
  default: ({ children, nodeRef }) => <div ref={nodeRef}>{children}</div>,
}));

// Mock Mantine components
vi.mock('@mantine/core', async () => {
  return {
    CloseButton: ({ onClick, onTouchEnd }) => (
      <button
        data-testid="close-button"
        onClick={onClick}
        onTouchEnd={onTouchEnd}
      >
        Close
      </button>
    ),
    Flex: ({ children, ...props }) => <div {...props}>{children}</div>,
    Box: ({ children, ...props }) => <div {...props}>{children}</div>,
    Loader: () => <div data-testid="loader">Loading...</div>,
    Text: ({ children, ...props }) => <div {...props}>{children}</div>,
  };
});

describe('FloatingVideo', () => {
  const mockHideVideo = vi.fn();
  let mockPlayer;

  beforeEach(async () => {
    vi.clearAllMocks();
    capturedHlsConfig = null;
    forceHlsInitError = false;

    // Mock HTMLVideoElement methods
    HTMLVideoElement.prototype.load = vi.fn();
    HTMLVideoElement.prototype.play = vi.fn(() => Promise.resolve());
    HTMLVideoElement.prototype.pause = vi.fn();

    mockPlayer = {
      attachMediaElement: vi.fn(),
      load: vi.fn(),
      play: vi.fn(() => Promise.resolve()),
      pause: vi.fn(),
      destroy: vi.fn(),
      on: vi.fn(),
    };

    mpegts.createPlayer.mockReturnValue(mockPlayer);
    mpegts.getFeatureList.mockReturnValue({ mseLivePlayback: true });

    useVideoStore.mockImplementation((selector) => {
      const state = {
        isVisible: false,
        streamUrl: null,
        contentType: 'live',
        metadata: null,
        hideVideo: mockHideVideo,
      };
      return selector ? selector(state) : state;
    });
  });

  describe('Visibility', () => {
    it('should not render when isVisible is false', () => {
      const { container } = render(<FloatingVideo />);
      expect(container.firstChild).toBeNull();
    });

    it('should not render when streamUrl is null', () => {
      useVideoStore.mockImplementation((selector) => {
        {
          const state = {
            isVisible: true,
            streamUrl: null,
            contentType: 'live',
            metadata: null,
            hideVideo: mockHideVideo,
          };
          return selector ? selector(state) : state;
        }
      });

      const { container } = render(<FloatingVideo />);
      expect(container.firstChild).toBeNull();
    });

    it('should render when isVisible is true and streamUrl is provided', () => {
      useVideoStore.mockImplementation((selector) => {
        {
          const state = {
            isVisible: true,
            streamUrl: 'http://example.com/stream',
            contentType: 'live',
            metadata: null,
            hideVideo: mockHideVideo,
          };
          return selector ? selector(state) : state;
        }
      });

      render(<FloatingVideo />);
      expect(screen.getByTestId('close-button')).toBeInTheDocument();
    });
  });

  describe('Live Stream Player', () => {
    beforeEach(() => {
      useVideoStore.mockImplementation((selector) => {
        {
          const state = {
            isVisible: true,
            streamUrl: 'http://example.com/stream.ts',
            contentType: 'live',
            metadata: null,
            hideVideo: mockHideVideo,
          };
          return selector ? selector(state) : state;
        }
      });
    });

    it('should initialize mpegts player for live streams', () => {
      render(<FloatingVideo />);

      expect(mpegts.createPlayer).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'mpegts',
          url: 'http://example.com/stream.ts',
          isLive: true,
        }),
        expect.objectContaining({
          enableWorker: true,
          enableStashBuffer: false,
        })
      );
    });

    it('should show loading state initially', () => {
      render(<FloatingVideo />);
      expect(screen.getByTestId('loader')).toBeInTheDocument();
      expect(screen.getByText('Loading stream...')).toBeInTheDocument();
    });

    it('should attach player to video element', () => {
      render(<FloatingVideo />);
      expect(mockPlayer.attachMediaElement).toHaveBeenCalled();
    });

    it('should handle player errors', async () => {
      render(<FloatingVideo />);

      const errorCallback = mockPlayer.on.mock.calls.find(
        (call) => call[0] === mpegts.Events.ERROR
      )?.[1];

      errorCallback('MediaError', 'AC3 codec not supported');

      await screen.findByText(/Audio codec not supported/i);
    });

    it('should handle unsupported browser', () => {
      mpegts.getFeatureList.mockReturnValue({
        mseLivePlayback: false,
      });

      render(<FloatingVideo />);

      expect(
        screen.getByText(/browser doesn't support live video streaming/i)
      ).toBeInTheDocument();
    });

    it('should play video on MEDIA_INFO event', async () => {
      render(<FloatingVideo />);

      const mediaInfoCallback = mockPlayer.on.mock.calls.find(
        (call) => call[0] === mpegts.Events.MEDIA_INFO
      )?.[1];

      await mediaInfoCallback();

      expect(mockPlayer.play).toHaveBeenCalled();
    });
  });

  describe('Live stream reconnect', () => {
    beforeEach(() => {
      useVideoStore.mockImplementation((selector) => {
        const state = {
          isVisible: true,
          streamUrl: 'http://example.com/stream.ts',
          contentType: 'live',
          metadata: null,
          hideVideo: mockHideVideo,
        };
        return selector ? selector(state) : state;
      });
    });

    // The mock always returns the same mockPlayer instance across
    // destroy+recreate cycles, so mockPlayer.on.mock.calls accumulates every
    // registration made so far. Grab the most recently registered handler --
    // the one bound to the currently "live" player -- not the first.
    const getErrorCallback = () =>
      mockPlayer.on.mock.calls
        .filter((call) => call[0] === mpegts.Events.ERROR)
        .at(-1)?.[1];

    afterEach(() => {
      vi.useRealTimers();
    });

    it('should destroy and recreate the player after a NetworkError, with backoff', async () => {
      vi.useFakeTimers();
      render(<FloatingVideo />);

      expect(mpegts.createPlayer).toHaveBeenCalledTimes(1);

      const errorCallback = getErrorCallback();
      act(() => {
        errorCallback('NetworkError', 'connection lost');
      });

      expect(
        screen.getByText(/reconnecting\.\.\. \(attempt 1\/5\)/i)
      ).toBeInTheDocument();
      expect(mockPlayer.destroy).not.toHaveBeenCalled();

      // First retry fires after the base delay (1000ms), not immediately.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(999);
      });
      expect(mpegts.createPlayer).toHaveBeenCalledTimes(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1);
      });
      expect(mockPlayer.destroy).toHaveBeenCalledTimes(1);
      expect(mpegts.createPlayer).toHaveBeenCalledTimes(2);
    });

    it('should give up after 5 NetworkError attempts and show a permanent error', async () => {
      vi.useFakeTimers();
      render(<FloatingVideo />);

      const delays = [1000, 2000, 4000, 8000, 10000];
      for (let i = 0; i < delays.length; i++) {
        const errorCallback = getErrorCallback();
        act(() => {
          errorCallback('NetworkError', 'connection lost');
        });
        expect(
          screen.getByText(new RegExp(`attempt ${i + 1}/5`, 'i'))
        ).toBeInTheDocument();
        await act(async () => {
          await vi.advanceTimersByTimeAsync(delays[i]);
        });
      }

      // All 5 attempts used -- the 6th NetworkError should not schedule
      // another retry and should surface the real error message instead.
      const finalErrorCallback = getErrorCallback();
      act(() => {
        finalErrorCallback('NetworkError', 'connection lost');
      });

      expect(
        screen.getByText(/NetworkError - connection lost/i)
      ).toBeInTheDocument();
      expect(screen.queryByText(/reconnecting/i)).not.toBeInTheDocument();
    });

    it('should not retry a MediaError (non-transient, retrying would not help)', async () => {
      vi.useFakeTimers();
      render(<FloatingVideo />);

      const errorCallback = getErrorCallback();
      act(() => {
        errorCallback('MediaError', 'AC3 codec not supported');
      });

      expect(
        screen.getByText(/Audio codec not supported/i)
      ).toBeInTheDocument();
      expect(screen.queryByText(/reconnecting/i)).not.toBeInTheDocument();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(15000);
      });
      expect(mpegts.createPlayer).toHaveBeenCalledTimes(1);
    });

    it('should reset the retry budget after the stream recovers', async () => {
      vi.useFakeTimers();
      render(<FloatingVideo />);

      let errorCallback = getErrorCallback();
      act(() => {
        errorCallback('NetworkError', 'connection lost');
      });
      expect(screen.getByText(/attempt 1\/5/i)).toBeInTheDocument();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
      expect(mpegts.createPlayer).toHaveBeenCalledTimes(2);

      // Stream recovers -- LOADING_COMPLETE resets the attempt counter.
      const loadingCompleteCallback = mockPlayer.on.mock.calls
        .filter((call) => call[0] === mpegts.Events.LOADING_COMPLETE)
        .at(-1)?.[1];
      act(() => {
        loadingCompleteCallback();
      });

      // A subsequent error should again start at attempt 1, not 2.
      errorCallback = getErrorCallback();
      act(() => {
        errorCallback('NetworkError', 'connection lost');
      });
      expect(screen.getByText(/attempt 1\/5/i)).toBeInTheDocument();
    });

    it('should not fire a queued reconnect after the player is closed', async () => {
      vi.useFakeTimers();
      render(<FloatingVideo />);

      const errorCallback = getErrorCallback();
      act(() => {
        errorCallback('NetworkError', 'connection lost');
      });
      expect(screen.getByText(/attempt 1\/5/i)).toBeInTheDocument();

      fireEvent.click(screen.getByTestId('close-button'));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(50); // handleClose's setTimeout(hideVideo, 50)
      });

      const createPlayerCallsAfterClose = mpegts.createPlayer.mock.calls.length;

      // Advance well past the scheduled reconnect delay -- it must not fire.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10000);
      });
      expect(mpegts.createPlayer).toHaveBeenCalledTimes(
        createPlayerCallsAfterClose
      );
    });
  });

  describe('Live stream stale-player-instance guards', () => {
    beforeEach(() => {
      useVideoStore.mockImplementation((selector) => {
        const state = {
          isVisible: true,
          streamUrl: 'http://example.com/stream.ts',
          contentType: 'live',
          metadata: null,
          hideVideo: mockHideVideo,
        };
        return selector ? selector(state) : state;
      });
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    // Every other test in this file reuses one shared mockPlayer instance
    // across destroy+recreate cycles, so `playerRef.current !== player`
    // (the guard under test here) can never actually be true there -- it's
    // trivially the same object. These tests give each createPlayer() call
    // its own distinct instance instead, so a "stale" callback captured
    // from an earlier, since-replaced instance is meaningfully different
    // from the current one, the way it is in a real browser.
    const mockDistinctPlayerInstances = () => {
      const instances = [];
      mpegts.createPlayer.mockImplementation(() => {
        const instance = {
          attachMediaElement: vi.fn(),
          load: vi.fn(),
          play: vi.fn(() => Promise.resolve()),
          pause: vi.fn(),
          destroy: vi.fn(),
          on: vi.fn(),
        };
        instances.push(instance);
        return instance;
      });
      return instances;
    };

    const getCallback = (instance, eventName) =>
      instance.on.mock.calls.find((call) => call[0] === eventName)?.[1];

    it('should ignore a late NetworkError from a player already replaced by a reconnect', async () => {
      vi.useFakeTimers();
      const instances = mockDistinctPlayerInstances();
      render(<FloatingVideo />);
      expect(instances).toHaveLength(1);

      // Player #1 hits a NetworkError -> schedules a reconnect (1000ms).
      act(() => {
        getCallback(instances[0], mpegts.Events.ERROR)(
          'NetworkError',
          'connection lost'
        );
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
      expect(instances).toHaveLength(2); // reconnect created player #2

      // A second NetworkError arrives late from player #1 -- already
      // replaced by player #2 by the time this fires (mirrors a real
      // mpegts.js worker message that was already in flight when we tore
      // player #1 down).
      act(() => {
        getCallback(instances[0], mpegts.Events.ERROR)(
          'NetworkError',
          'connection lost'
        );
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10000);
      });

      // Must be a no-op: no third player created, and the current player
      // #2 must not have been torn down.
      expect(instances).toHaveLength(2);
      expect(instances[1].destroy).not.toHaveBeenCalled();
    });

    it('should ignore a late autoplay-prevented rejection from a replaced player', async () => {
      vi.useFakeTimers();
      const instances = mockDistinctPlayerInstances();
      // Player #1's play() call resolves only after we've moved on to
      // player #2, simulating a slow/late-settling promise.
      let rejectFirstPlay;
      render(<FloatingVideo />);
      instances[0].play.mockReturnValue(
        new Promise((_resolve, reject) => {
          rejectFirstPlay = reject;
        })
      );

      // Trigger player #1's MEDIA_INFO -> its play() call is now pending.
      act(() => {
        getCallback(instances[0], mpegts.Events.MEDIA_INFO)();
      });

      // A NetworkError replaces player #1 with player #2 (reconnect).
      act(() => {
        getCallback(instances[0], mpegts.Events.ERROR)(
          'NetworkError',
          'connection lost'
        );
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
      expect(instances).toHaveLength(2);

      // Player #1's play() promise finally rejects (autoplay-prevented),
      // long after player #2 took over.
      await act(async () => {
        rejectFirstPlay(new DOMException('', 'NotAllowedError'));
        await Promise.resolve().catch(() => {});
      });

      // Must not show the stale "Auto-play was prevented" message, since
      // it refers to a player instance that is no longer active.
      expect(
        screen.queryByText(/Auto-play was prevented/i)
      ).not.toBeInTheDocument();
    });
  });

  describe('VOD Player', () => {
    beforeEach(() => {
      useVideoStore.mockImplementation((selector) => {
        {
          const state = {
            isVisible: true,
            streamUrl: 'http://example.com/video.mp4',
            contentType: 'vod',
            metadata: {
              name: 'Test Movie',
              year: '2024',
              logo: { url: 'http://example.com/poster.jpg' },
            },
            hideVideo: mockHideVideo,
          };
          return selector ? selector(state) : state;
        }
      });
    });

    it('should use native video player for VOD', () => {
      render(<FloatingVideo />);
      expect(mpegts.createPlayer).not.toHaveBeenCalled();
    });

    it('should set video source for VOD', () => {
      const { container } = render(<FloatingVideo />);
      const video = container.querySelector('video');
      expect(video).toBeInTheDocument();
      expect(video.src).toBe('http://example.com/video.mp4');
      expect(video.poster).toBe('http://example.com/poster.jpg');
    });

    it('should disable live-edge sync for in-progress recording HLS', () => {
      useVideoStore.mockImplementation((selector) => {
        const state = {
          isVisible: true,
          streamUrl:
            'http://example.com/api/channels/recordings/1/hls/index.m3u8',
          contentType: 'vod',
          metadata: { name: 'News Recording' },
          hideVideo: mockHideVideo,
        };
        return selector ? selector(state) : state;
      });

      Hls.isSupported.mockReturnValue(true);

      render(<FloatingVideo />);

      expect(capturedHlsConfig).toEqual(
        expect.objectContaining({
          startPosition: 0,
        })
      );
      expect(capturedHlsConfig).not.toHaveProperty(
        'liveMaxLatencyDurationCount'
      );
      expect(capturedHlsConfig).not.toHaveProperty('liveSyncDurationCount');
    });

    it('shows an in-player error when hls.js config is invalid', () => {
      useVideoStore.mockImplementation((selector) => {
        const state = {
          isVisible: true,
          streamUrl:
            'http://example.com/api/channels/recordings/1/hls/index.m3u8',
          contentType: 'vod',
          metadata: { name: 'News Recording' },
          hideVideo: mockHideVideo,
        };
        return selector ? selector(state) : state;
      });

      Hls.isSupported.mockReturnValue(true);
      forceHlsInitError = true;

      render(<FloatingVideo />);

      expect(
        screen.getByText(/HLS initialization error: Illegal hls.js config/i)
      ).toBeInTheDocument();
    });

    it('should show metadata overlay', () => {
      const { container } = render(<FloatingVideo />);
      const video = container.querySelector('video');

      // Simulate video loaded and canplay events to clear loading state and show overlay
      fireEvent.loadedData(video);
      fireEvent.canPlay(video);

      expect(screen.getAllByText('Test Movie').length).toBeGreaterThanOrEqual(
        1
      );
      expect(screen.getByText('2024')).toBeInTheDocument();
    });

    it('should hide overlay after 4 seconds', () => {
      vi.useFakeTimers();

      const { container } = render(<FloatingVideo />);
      const video = container.querySelector('video');

      fireEvent.loadedData(video);
      fireEvent.canPlay(video);

      expect(screen.getAllByText('Test Movie').length).toBeGreaterThanOrEqual(
        1
      );

      vi.advanceTimersByTime(4000);

      waitFor(() => {
        // After overlay hides, only the header title remains
        expect(screen.getAllByText('Test Movie').length).toBe(1);
      });

      vi.useRealTimers();
    });

    it('should show overlay on mouse enter', () => {
      const { container } = render(<FloatingVideo />);
      const video = container.querySelector('video');

      fireEvent.loadedData(video);
      fireEvent.canPlay(video);

      const videoContainer = video.parentElement;

      fireEvent.mouseEnter(videoContainer);

      expect(screen.getAllByText('Test Movie').length).toBeGreaterThanOrEqual(
        1
      );
    });

    it('should hide overlay on mouse leave', () => {
      vi.useFakeTimers();

      const { container } = render(<FloatingVideo />);
      const video = container.querySelector('video');

      fireEvent.loadedData(video);
      fireEvent.canPlay(video);

      const videoContainer = video.parentElement;

      fireEvent.mouseEnter(videoContainer);
      fireEvent.mouseLeave(videoContainer);

      vi.advanceTimersByTime(4000);

      waitFor(() => {
        // After overlay hides, only the header title remains
        expect(screen.getAllByText('Test Movie').length).toBe(1);
      });

      vi.useRealTimers();
    });
  });

  describe('Close functionality', () => {
    beforeEach(() => {
      useVideoStore.mockImplementation((selector) => {
        {
          const state = {
            isVisible: true,
            streamUrl: 'http://example.com/stream.ts',
            contentType: 'live',
            metadata: null,
            hideVideo: mockHideVideo,
          };
          return selector ? selector(state) : state;
        }
      });
    });

    it('should call hideVideo when close button is clicked', () => {
      vi.useFakeTimers();

      render(<FloatingVideo />);

      fireEvent.click(screen.getByTestId('close-button'));

      vi.advanceTimersByTime(50);

      waitFor(() => {
        expect(mockHideVideo).toHaveBeenCalled();
        expect(mockPlayer.destroy).toHaveBeenCalled();
      });

      vi.useRealTimers();
    });
  });

  describe('Error handling', () => {
    beforeEach(() => {
      useVideoStore.mockImplementation((selector) => {
        {
          const state = {
            isVisible: true,
            streamUrl: 'http://example.com/video.mp4',
            contentType: 'vod',
            metadata: null,
            hideVideo: mockHideVideo,
          };
          return selector ? selector(state) : state;
        }
      });
    });

    it('should display video error messages', () => {
      const { container } = render(<FloatingVideo />);
      const video = container.querySelector('video');

      Object.defineProperty(video, 'error', {
        value: { code: 3, message: 'MEDIA_ERR_DECODE' },
        writable: true,
      });

      fireEvent.error(video);

      expect(screen.getByText(/MEDIA_ERR_DECODE/i)).toBeInTheDocument();
    });

    it('should handle network errors', () => {
      const { container } = render(<FloatingVideo />);
      const video = container.querySelector('video');

      Object.defineProperty(video, 'error', {
        value: { code: 2, message: 'MEDIA_ERR_NETWORK' },
        writable: true,
      });

      fireEvent.error(video);

      expect(screen.getByText(/MEDIA_ERR_NETWORK/i)).toBeInTheDocument();
    });
  });

  describe('Player cleanup', () => {
    it('should cleanup player on unmount', () => {
      useVideoStore.mockImplementation((selector) => {
        {
          const state = {
            isVisible: true,
            streamUrl: 'http://example.com/stream.ts',
            contentType: 'live',
            metadata: null,
            hideVideo: mockHideVideo,
          };
          return selector ? selector(state) : state;
        }
      });

      const { unmount } = render(<FloatingVideo />);

      unmount();

      expect(mockPlayer.destroy).toHaveBeenCalled();
    });

    it('should cleanup player when streamUrl changes', () => {
      useVideoStore.mockImplementation((selector) => {
        {
          const state = {
            isVisible: true,
            streamUrl: 'http://example.com/stream1.ts',
            contentType: 'live',
            metadata: null,
            hideVideo: mockHideVideo,
          };
          return selector ? selector(state) : state;
        }
      });

      const { rerender } = render(<FloatingVideo />);

      useVideoStore.mockImplementation((selector) => {
        {
          const state = {
            isVisible: true,
            streamUrl: 'http://example.com/stream2.ts',
            contentType: 'live',
            metadata: null,
            hideVideo: mockHideVideo,
          };
          return selector ? selector(state) : state;
        }
      });

      rerender(<FloatingVideo />);

      expect(mockPlayer.destroy).toHaveBeenCalled();
    });
  });

  describe('Resize functionality', () => {
    beforeEach(() => {
      useVideoStore.mockImplementation((selector) => {
        {
          const state = {
            isVisible: true,
            streamUrl: 'http://example.com/stream.ts',
            contentType: 'live',
            metadata: null,
            hideVideo: mockHideVideo,
          };
          return selector ? selector(state) : state;
        }
      });
    });

    it('should render resize handles', () => {
      const { container } = render(<FloatingVideo />);
      const handles = container.querySelectorAll(
        '[class*="floating-video-no-drag"]'
      );

      // Should have 4 resize handles plus video element
      expect(handles.length).toBeGreaterThanOrEqual(4);
    });
  });
});
