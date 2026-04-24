import { render, screen, fireEvent, waitFor } from '@testing-library/react';
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

// Import the mocked module after mocking
const mpegts = (await import('mpegts.js')).default;

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
