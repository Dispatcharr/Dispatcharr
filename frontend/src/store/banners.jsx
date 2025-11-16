import { create } from 'zustand';
import api from '../api';

const useBannersStore = create((set, get) => ({
  banners: {},
  channelBanners: {}, // Keep this for simplicity, but we'll be more careful about when we populate it
  isLoading: false,
  backgroundLoading: false,
  hasLoadedAll: false, // Track if we've loaded all banners
  hasLoadedChannelBanners: false, // Track if we've loaded channel-assignable banners
  error: null,

  // Basic CRUD operations
  setBanners: (banners) => {
    set({
      banners: banners.reduce((acc, banner) => {
        acc[banner.id] = { ...banner };
        return acc;
      }, {}),
    });
  },

  addBanner: (newBanner) =>
    set((state) => {
      // Add to main banners store always
      const newBanners = {
        ...state.banners,
        [newBanner.id]: { ...newBanner },
      };

      // Add to channelBanners if the user has loaded channel-assignable banners
      // This means they're using channel forms and the new banner should be available there
      // Newly created banners are channel-assignable (they start unused)
      let newChannelBanners = state.channelBanners;
      if (state.hasLoadedChannelBanners) {
        newChannelBanners = {
          ...state.channelBanners,
          [newBanner.id]: { ...newBanner },
        };
      }

      return {
        banners: newBanners,
        channelBanners: newChannelBanners,
      };
    }),

  updateBanner: (banner) =>
    set((state) => ({
      banners: {
        ...state.banners,
        [banner.id]: { ...banner },
      },
      // Update in channelBanners if it exists there
      channelBanners: state.channelBanners[banner.id]
        ? {
            ...state.channelBanners,
            [banner.id]: { ...banner },
          }
        : state.channelBanners,
    })),

  removeBanner: (bannerId) =>
    set((state) => {
      const newBanners = { ...state.banners };
      const newChannelBanners = { ...state.channelBanners };
      delete newBanners[bannerId];
      delete newChannelBanners[bannerId];
      return {
        banners: newBanners,
        channelBanners: newChannelBanners,
      };
    }),

  // Smart loading methods
  fetchBanners: async (pageSize = 100) => {
    set({ isLoading: true, error: null });
    try {
      const response = await api.getBanners({ page_size: pageSize });

      // Handle both paginated and non-paginated responses
      const banners = Array.isArray(response) ? response : response.results || [];

      set({
        banners: banners.reduce((acc, banner) => {
          acc[banner.id] = { ...banner };
          return acc;
        }, {}),
        isLoading: false,
      });
      return response;
    } catch (error) {
      console.error('Failed to fetch banners:', error);
      set({ error: 'Failed to load banners.', isLoading: false });
      throw error;
    }
  },

  fetchAllBanners: async () => {
    const { isLoading, hasLoadedAll, banners } = get();

    // Prevent unnecessary reloading if we already have all banners
    if (isLoading || (hasLoadedAll && Object.keys(banners).length > 0)) {
      return Object.values(banners);
    }

    set({ isLoading: true, error: null });
    try {
      // Disable pagination to get all banners for management interface
      const response = await api.getBanners({ no_pagination: 'true' });

      // Handle both paginated and non-paginated responses
      const bannersArray = Array.isArray(response)
        ? response
        : response.results || [];

      set({
        banners: bannersArray.reduce((acc, banner) => {
          acc[banner.id] = { ...banner };
          return acc;
        }, {}),
        hasLoadedAll: true, // Mark that we've loaded all banners
        isLoading: false,
      });
      return bannersArray;
    } catch (error) {
      console.error('Failed to fetch all banners:', error);
      set({ error: 'Failed to load all banners.', isLoading: false });
      throw error;
    }
  },

  fetchUsedBanners: async (pageSize = 100) => {
    set({ isLoading: true, error: null });
    try {
      // Load used banners with pagination for better performance
      const response = await api.getBanners({
        used: 'true',
        page_size: pageSize,
      });

      // Handle both paginated and non-paginated responses
      const banners = Array.isArray(response) ? response : response.results || [];

      set((state) => ({
        banners: {
          ...state.banners,
          ...banners.reduce((acc, banner) => {
            acc[banner.id] = { ...banner };
            return acc;
          }, {}),
        },
        isLoading: false,
      }));
      return response;
    } catch (error) {
      console.error('Failed to fetch used banners:', error);
      set({ error: 'Failed to load used banners.', isLoading: false });
      throw error;
    }
  },

  fetchChannelAssignableBanners: async () => {
    const { backgroundLoading, hasLoadedChannelBanners, channelBanners } = get();

    // Prevent concurrent calls
    if (
      backgroundLoading ||
      (hasLoadedChannelBanners && Object.keys(channelBanners).length > 0)
    ) {
      return Object.values(channelBanners);
    }

    set({ backgroundLoading: true, error: null });
    try {
      // Load banners suitable for channel assignment (unused + channel-used)
      const response = await api.getBanners({
        no_pagination: 'true', // Get all channel-assignable banners
      });

      // Handle both paginated and non-paginated responses
      const banners = Array.isArray(response) ? response : response.results || [];

      console.log(`Fetched ${banners.length} channel-assignable banners`);

      // Store in both places, but this is intentional and only when specifically requested
      set({
        banners: {
          ...get().banners, // Keep existing banners
          ...banners.reduce((acc, banner) => {
            acc[banner.id] = { ...banner };
            return acc;
          }, {}),
        },
        channelBanners: banners.reduce((acc, banner) => {
          acc[banner.id] = { ...banner };
          return acc;
        }, {}),
        hasLoadedChannelBanners: true,
        backgroundLoading: false,
      });

      return banners;
    } catch (error) {
      console.error('Failed to fetch channel-assignable banners:', error);
      set({
        error: 'Failed to load channel-assignable banners.',
        backgroundLoading: false,
      });
      throw error;
    }
  },

  fetchBannersByIds: async (bannerIds) => {
    if (!bannerIds || bannerIds.length === 0) return [];

    try {
      // Filter out banners we already have
      const missingIds = bannerIds.filter((id) => !get().banners[id]);
      if (missingIds.length === 0) return [];

      const response = await api.getBannersByIds(missingIds);

      // Handle both paginated and non-paginated responses
      const banners = Array.isArray(response) ? response : response.results || [];

      set((state) => ({
        banners: {
          ...state.banners,
          ...banners.reduce((acc, banner) => {
            acc[banner.id] = { ...banner };
            return acc;
          }, {}),
        },
      }));
      return banners;
    } catch (error) {
      console.error('Failed to fetch banners by IDs:', error);
      throw error;
    }
  },

  fetchBannersInBackground: async () => {
    set({ backgroundLoading: true });
    try {
      // Load banners in chunks using pagination for better performance
      let page = 1;
      const pageSize = 200;
      let hasMore = true;

      while (hasMore) {
        const response = await api.getBanners({ page, page_size: pageSize });

        set((state) => ({
          banners: {
            ...state.banners,
            ...response.results.reduce((acc, banner) => {
              acc[banner.id] = { ...banner };
              return acc;
            }, {}),
          },
        }));

        // Check if there are more pages
        hasMore = !!response.next;
        page++;

        // Add a small delay between chunks to avoid overwhelming the server
        if (hasMore) {
          await new Promise((resolve) => setTimeout(resolve, 100));
        }
      }
    } catch (error) {
      console.error('Background banner loading failed:', error);
      // Don't throw error for background loading
    } finally {
      set({ backgroundLoading: false });
    }
  },

  // Background loading specifically for all banners after login
  backgroundLoadAllBanners: async () => {
    const { backgroundLoading, hasLoadedAll } = get();

    // Don't start if already loading or if we already have all banners loaded
    if (backgroundLoading || hasLoadedAll) {
      return;
    }

    set({ backgroundLoading: true });

    // Use setTimeout to make this truly non-blocking
    setTimeout(async () => {
      try {
        // Use the API directly to avoid interfering with the main isLoading state
        const response = await api.getBanners({ no_pagination: 'true' });
        const bannersArray = Array.isArray(response)
          ? response
          : response.results || [];

        // Process banners in smaller chunks to avoid blocking the main thread
        const chunkSize = 1000;
        const bannerObject = {};

        for (let i = 0; i < bannersArray.length; i += chunkSize) {
          const chunk = bannersArray.slice(i, i + chunkSize);
          chunk.forEach((banner) => {
            bannerObject[banner.id] = { ...banner };
          });

          // Yield control back to the main thread between chunks
          if (i + chunkSize < bannersArray.length) {
            await new Promise((resolve) => setTimeout(resolve, 0));
          }
        }

        set({
          banners: bannerObject,
          hasLoadedAll: true,
          backgroundLoading: false,
        });
      } catch (error) {
        console.error('Background all banners loading failed:', error);
        set({ backgroundLoading: false });
      }
    }, 0); // Execute immediately but asynchronously
  },

  // Background loading specifically for channel-assignable banners after login
  backgroundLoadChannelBanners: async () => {
    const { backgroundLoading, channelBanners, hasLoadedChannelBanners } = get();

    // Don't start if already loading or if we already have channel banners loaded
    if (
      backgroundLoading ||
      hasLoadedChannelBanners ||
      Object.keys(channelBanners).length > 100
    ) {
      return;
    }

    set({ backgroundLoading: true });
    try {
      console.log('Background loading channel-assignable banners...');
      await get().fetchChannelAssignableBanners();
      console.log(
        `Background loaded ${Object.keys(get().channelBanners).length} channel-assignable banners`
      );
    } catch (error) {
      console.error('Background channel banner loading failed:', error);
      // Don't throw error for background loading
    } finally {
      set({ backgroundLoading: false });
    }
  },

  // Start background loading after app is fully initialized
  startBackgroundLoading: () => {
    // Use a longer delay to ensure app is fully loaded
    setTimeout(() => {
      // Fire and forget - don't await this
      get()
        .backgroundLoadAllBanners()
        .catch((error) => {
          console.error('Background banner loading failed:', error);
        });
    }, 3000); // Wait 3 seconds after app initialization
  },

  // Helper methods
  getBannerById: (bannerId) => {
    return get().banners[bannerId] || null;
  },

  hasBanner: (bannerId) => {
    return !!get().banners[bannerId];
  },

  getBannersCount: () => {
    return Object.keys(get().banners).length;
  },

  // Check if we need to fetch all banners (haven't loaded them yet or store is empty)
  needsAllBanners: () => {
    const state = get();
    return !state.hasLoadedAll || Object.keys(state.banners).length === 0;
  },
}));

export default useBannersStore;