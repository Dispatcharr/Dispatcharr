import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach } from 'vitest';
import useVideoStore from '../useVideoStore';

describe('useVideoStore', () => {
  beforeEach(() => {
    useVideoStore.setState({
      isVisible: false,
      streamUrl: null,
      contentType: 'live',
      metadata: null,
    });
  });

  it('should initialize with default state', () => {
    const { result } = renderHook(() => useVideoStore());

    expect(result.current.isVisible).toBe(false);
    expect(result.current.streamUrl).toBe(null);
    expect(result.current.contentType).toBe('live');
    expect(result.current.metadata).toBe(null);
  });

  it('should show video with live stream', () => {
    const { result } = renderHook(() => useVideoStore());
    const streamUrl = 'http://example.com/stream.ts';

    act(() => {
      result.current.showVideo(streamUrl);
    });

    expect(result.current.isVisible).toBe(true);
    expect(result.current.streamUrl).toBe(streamUrl);
    expect(result.current.contentType).toBe('live');
    expect(result.current.metadata).toBe(null);
  });

  it('should show video with VOD content', () => {
    const { result } = renderHook(() => useVideoStore());
    const streamUrl = 'http://example.com/video.mp4';
    const metadata = { title: 'Test Video', duration: 120 };

    act(() => {
      result.current.showVideo(streamUrl, 'vod', metadata);
    });

    expect(result.current.isVisible).toBe(true);
    expect(result.current.streamUrl).toBe(streamUrl);
    expect(result.current.contentType).toBe('vod');
    expect(result.current.metadata).toEqual(metadata);
  });

  it('should show video with custom content type', () => {
    const { result } = renderHook(() => useVideoStore());
    const streamUrl = 'http://example.com/video.mkv';

    act(() => {
      result.current.showVideo(streamUrl, 'vod');
    });

    expect(result.current.isVisible).toBe(true);
    expect(result.current.streamUrl).toBe(streamUrl);
    expect(result.current.contentType).toBe('vod');
    expect(result.current.metadata).toBe(null);
  });

  it('should hide video and reset state', () => {
    const { result } = renderHook(() => useVideoStore());

    act(() => {
      result.current.showVideo('http://example.com/stream.ts', 'vod', { title: 'Test' });
    });

    expect(result.current.isVisible).toBe(true);

    act(() => {
      result.current.hideVideo();
    });

    expect(result.current.isVisible).toBe(false);
    expect(result.current.streamUrl).toBe(null);
    expect(result.current.contentType).toBe('live');
    expect(result.current.metadata).toBe(null);
  });

  it('should update stream when showing different video', () => {
    const { result } = renderHook(() => useVideoStore());
    const firstUrl = 'http://example.com/stream1.ts';
    const secondUrl = 'http://example.com/stream2.ts';

    act(() => {
      result.current.showVideo(firstUrl);
    });

    expect(result.current.streamUrl).toBe(firstUrl);

    act(() => {
      result.current.showVideo(secondUrl);
    });

    expect(result.current.streamUrl).toBe(secondUrl);
    expect(result.current.isVisible).toBe(true);
  });

  it('should handle showing video with null metadata explicitly', () => {
    const { result } = renderHook(() => useVideoStore());
    const streamUrl = 'http://example.com/stream.ts';

    act(() => {
      result.current.showVideo(streamUrl, 'live', null);
    });

    expect(result.current.isVisible).toBe(true);
    expect(result.current.streamUrl).toBe(streamUrl);
    expect(result.current.contentType).toBe('live');
    expect(result.current.metadata).toBe(null);
  });

  it('should preserve metadata when showing VOD content', () => {
    const { result } = renderHook(() => useVideoStore());
    const metadata = {
      title: 'Test Video',
      duration: 120,
      thumbnailUrl: 'http://example.com/thumb.jpg'
    };

    act(() => {
      result.current.showVideo('http://example.com/video.mp4', 'vod', metadata);
    });

    expect(result.current.metadata).toEqual(metadata);
    expect(result.current.metadata.title).toBe('Test Video');
    expect(result.current.metadata.duration).toBe(120);
  });

  it('should override previous metadata when showing new video', () => {
    const { result } = renderHook(() => useVideoStore());
    const firstMetadata = { title: 'First Video' };
    const secondMetadata = { title: 'Second Video' };

    act(() => {
      result.current.showVideo('http://example.com/first.mp4', 'vod', firstMetadata);
    });

    expect(result.current.metadata).toEqual(firstMetadata);

    act(() => {
      result.current.showVideo('http://example.com/second.mp4', 'vod', secondMetadata);
    });

    expect(result.current.metadata).toEqual(secondMetadata);
  });

  it('should handle hiding video when already hidden', () => {
    const { result } = renderHook(() => useVideoStore());

    expect(result.current.isVisible).toBe(false);

    act(() => {
      result.current.hideVideo();
    });

    expect(result.current.isVisible).toBe(false);
    expect(result.current.streamUrl).toBe(null);
  });

  it('should handle showing video multiple times consecutively', () => {
    const { result } = renderHook(() => useVideoStore());
    const url1 = 'http://example.com/stream1.ts';
    const url2 = 'http://example.com/stream2.ts';
    const url3 = 'http://example.com/stream3.ts';

    act(() => {
      result.current.showVideo(url1);
      result.current.showVideo(url2);
      result.current.showVideo(url3);
    });

    expect(result.current.isVisible).toBe(true);
    expect(result.current.streamUrl).toBe(url3);
  });
});
