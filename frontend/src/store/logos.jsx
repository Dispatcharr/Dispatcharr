import { create } from 'zustand';
import api from '../api';

const useLogosStore = create((set, get) => ({
  logos: {},
  channelLogos: {}, // Separate cache for channel forms to avoid reloading
  isLoading: false,
  backgroundLoading: false,
  hasLoadedAll: false, // Track if we've loaded all logos
  hasLoadedChannelLogos: false, // Track if we've loaded channel logos
  error: null,
  allowLogoRendering: false, // Gate to prevent logo rendering until tables are ready

  // Enable logo rendering (call this after tables have loaded and painted)
  enableLogoRendering: () => set({ allowLogoRendering: true }),

  addLogo: (newLogo) =>
    set((state) => {
      // Add to main logos store always
      const newLogos = {
        ...state.logos,
        [newLogo.id]: { ...newLogo },
      };

      // Add to channelLogos if the user has loaded channel logos
      // This means they're using channel forms and the new logo should be available there
      let newChannelLogos = state.channelLogos;
      if (state.hasLoadedChannelLogos) {
        newChannelLogos = {
          ...state.channelLogos,
          [newLogo.id]: { ...newLogo },
        };
      }

      return {
        logos: newLogos,
        channelLogos: newChannelLogos,
      };
    }),

  updateLogo: (logo) =>
    set((state) => ({
      logos: {
        ...state.logos,
        [logo.id]: { ...logo },
      },
      // Update in channelLogos if it exists there
      channelLogos: state.channelLogos[logo.id]
        ? {
            ...state.channelLogos,
            [logo.id]: { ...logo },
          }
        : state.channelLogos,
    })),

  removeLogo: (logoId) =>
    set((state) => {
      const newLogos = { ...state.logos };
      const newChannelLogos = { ...state.channelLogos };
      delete newLogos[logoId];
      delete newChannelLogos[logoId];
      return {
        logos: newLogos,
        channelLogos: newChannelLogos,
      };
    }),

  // Smart loading methods
  fetchLogos: async (pageSize = 100) => {
    // Don't fetch if logo fetching is not allowed yet
    if (!get().allowLogoFetching) return [];

    set({ isLoading: true, error: null });
    try {
      const response = await api.getLogos({ page_size: pageSize });

      // Handle both paginated and non-paginated responses
      const logos = Array.isArray(response) ? response : response.results || [];

      set({
        logos: logos.reduce((acc, logo) => {
          acc[logo.id] = { ...logo };
          return acc;
        }, {}),
        isLoading: false,
      });
      return response;
    } catch (error) {
      console.error('Failed to fetch logos:', error);
      set({ error: 'Failed to load logos.', isLoading: false });
      throw error;
    }
  },

  fetchAllLogos: async (force = false) => {
    const { isLoading, hasLoadedAll, logos } = get();

    // Prevent unnecessary reloading if we already have all logos
    if (
      !force &&
      (isLoading || (hasLoadedAll && Object.keys(logos).length > 0))
    ) {
      return Object.values(logos);
    }

    set({ isLoading: true, error: null });
    try {
      // Disable pagination to get all logos for management interface
      const response = await api.getLogos({ no_pagination: 'true' });

      // Handle both paginated and non-paginated responses
      const logosArray = Array.isArray(response)
        ? response
        : response.results || [];

      set({
        logos: logosArray.reduce((acc, logo) => {
          acc[logo.id] = { ...logo };
          return acc;
        }, {}),
        hasLoadedAll: true, // Mark that we've loaded all logos
        isLoading: false,
      });
      return logosArray;
    } catch (error) {
      console.error('Failed to fetch all logos:', error);
      set({ error: 'Failed to load all logos.', isLoading: false });
      throw error;
    }
  },

  fetchUsedLogos: async (pageSize = 100) => {
    set({ isLoading: true, error: null });
    try {
      // Load used logos with pagination for better performance
      const response = await api.getLogos({
        used: 'true',
        page_size: pageSize,
      });

      // Handle both paginated and non-paginated responses
      const logos = Array.isArray(response) ? response : response.results || [];

      set((state) => ({
        logos: {
          ...state.logos,
          ...logos.reduce((acc, logo) => {
            acc[logo.id] = { ...logo };
            return acc;
          }, {}),
        },
        isLoading: false,
      }));
      return response;
    } catch (error) {
      console.error('Failed to fetch used logos:', error);
      set({ error: 'Failed to load used logos.', isLoading: false });
      throw error;
    }
  },

  fetchChannelAssignableLogos: async () => {
    const { hasLoadedChannelLogos, channelLogos } = get();

    // Return cached if already loaded
    if (hasLoadedChannelLogos && Object.keys(channelLogos).length > 0) {
      return Object.values(channelLogos);
    }

    // Fetch all logos and cache them as channel logos
    const logos = await get().fetchAllLogos();

    set({
      channelLogos: logos.reduce((acc, logo) => {
        acc[logo.id] = { ...logo };
        return acc;
      }, {}),
      hasLoadedChannelLogos: true,
    });

    return logos;
  },

  fetchLogosByIds: async (logoIds) => {
    try {
      // Filter out logos we already have
      const missingIds = logoIds.filter((id) => !get().logos[id]);
      if (missingIds.length === 0) return [];

      const response = await api.getLogosByIds(missingIds);

      // Handle both paginated and non-paginated responses
      const logos = Array.isArray(response) ? response : response.results || [];

      set((state) => ({
        logos: {
          ...state.logos,
          ...logos.reduce((acc, logo) => {
            acc[logo.id] = { ...logo };
            return acc;
          }, {}),
        },
      }));
      return logos;
    } catch (error) {
      console.error('Failed to fetch logos by IDs:', error);
      throw error;
    }
  },

  fetchLogosInBackground: async () => {
    set({ backgroundLoading: true });
    try {
      // Load logos in chunks using pagination for better performance
      let page = 1;
      const pageSize = 200;
      let hasMore = true;

      while (hasMore) {
        const response = await api.getLogos({ page, page_size: pageSize });

        set((state) => ({
          logos: {
            ...state.logos,
            ...response.results.reduce((acc, logo) => {
              acc[logo.id] = { ...logo };
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
      console.error('Background logo loading failed:', error);
      // Don't throw error for background loading
    } finally {
      set({ backgroundLoading: false });
    }
  },

  // Background loading specifically for all logos after login
  backgroundLoadAllLogos: async () => {
    const { backgroundLoading, hasLoadedAll } = get();

    // Don't start if already loading or if we already have all logos loaded
    if (backgroundLoading || hasLoadedAll) {
      return;
    }

    set({ backgroundLoading: true });

    // Use setTimeout to make this truly non-blocking
    setTimeout(async () => {
      try {
        // Use the API directly to avoid interfering with the main isLoading state
        const response = await api.getLogos({ no_pagination: 'true' });
        const logosArray = Array.isArray(response)
          ? response
          : response.results || [];

        // Process logos in smaller chunks to avoid blocking the main thread
        const chunkSize = 1000;
        const logoObject = {};

        for (let i = 0; i < logosArray.length; i += chunkSize) {
          const chunk = logosArray.slice(i, i + chunkSize);
          chunk.forEach((logo) => {
            logoObject[logo.id] = { ...logo };
          });

          // Yield control back to the main thread between chunks
          if (i + chunkSize < logosArray.length) {
            await new Promise((resolve) => setTimeout(resolve, 0));
          }
        }

        set({
          logos: logoObject,
          hasLoadedAll: true,
          backgroundLoading: false,
        });
      } catch (error) {
        console.error('Background all logos loading failed:', error);
        set({ backgroundLoading: false });
      }
    }, 0); // Execute immediately but asynchronously
  },

  // Background loading for channel logos after login
  backgroundLoadChannelLogos: async () => {
    const { backgroundLoading, channelLogos, hasLoadedChannelLogos } = get();

    // Don't start if already loading or if we already have channel logos loaded
    if (
      backgroundLoading ||
      hasLoadedChannelLogos ||
      Object.keys(channelLogos).length > 100
    ) {
      return;
    }

    set({ backgroundLoading: true });
    try {
      console.log('Background loading channel logos...');
      await get().fetchChannelAssignableLogos();
      console.log(
        `Background loaded ${Object.keys(get().channelLogos).length} channel logos`
      );
    } catch (error) {
      console.error('Background channel logo loading failed:', error);
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
        .backgroundLoadAllLogos()
        .catch((error) => {
          console.error('Background logo loading failed:', error);
        });
    }, 3000); // Wait 3 seconds after app initialization
  },

  // Helper methods
  getLogoById: (logoId) => {
    return get().logos[logoId] || null;
  },

  hasLogo: (logoId) => {
    return !!get().logos[logoId];
  },

  getLogosCount: () => {
    return Object.keys(get().logos).length;
  },

  // Check if we need to fetch all logos (haven't loaded them yet or store is empty)
  needsAllLogos: () => {
    const state = get();
    return !state.hasLoadedAll || Object.keys(state.logos).length === 0;
  },
}));

export default useLogosStore;
