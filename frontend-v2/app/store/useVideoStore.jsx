// frontend/src/store/useVideoStore.js
import { create } from 'zustand';

/**
 * Global store to track whether a floating video is visible and which URL is playing.
 */
const useVideoStore = create((set) => ({
  isVisible: false,
  streamUrl: null,
  contentType: 'live', // 'live' for MPEG-TS streams, 'vod' for MP4/MKV files
  metadata: null, // Store additional metadata for VOD content

  showVideo: (url, type = 'live', metadata = null) =>
    set({
      isVisible: true,
      streamUrl: url,
      contentType: type,
      metadata: metadata,
    }),

  hideVideo: () =>
    set({
      isVisible: false,
      streamUrl: null,
      contentType: 'live',
      metadata: null,
    }),
}));

export default useVideoStore;
