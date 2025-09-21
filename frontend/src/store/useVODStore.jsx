import { create } from 'zustand';
import api from '../api';

const useVODStore = create((set, get) => ({
  content: {}, // Store for individual content details (when fetching movie/series details)
  currentPageContent: [], // Store the current page's results
  episodes: {},
  categories: {},
  loading: false,
  error: null,
  filters: {
    type: 'all', // 'all', 'movies', 'series'
    search: '',
    category: '',
  },
  currentPage: 1,
  totalCount: 0,
  pageSize: 24,

  setFilters: (newFilters) =>
    set((state) => ({
      filters: { ...state.filters, ...newFilters },
      currentPage: 1, // Reset to first page when filters change
    })),

  setPage: (page) =>
    set(() => ({
      currentPage: page,
    })),

  setPageSize: (size) =>
    set(() => ({
      pageSize: size,
      currentPage: 1, // Reset to first page when page size changes
    })),

  fetchContent: async () => {
    try {
      set({ loading: true, error: null });
      const state = get();

      const params = new URLSearchParams();
      params.append('page', state.currentPage);
      params.append('page_size', state.pageSize);

      if (state.filters.search) {
        params.append('search', state.filters.search);
      }

      if (state.filters.category) {
        params.append('category', state.filters.category);
      }

      let allResults = [];
      let totalCount = 0;

      if (state.filters.type === 'movies') {
        // Fetch only movies
        const response = await api.getMovies(params);
        const results = response.results || response;
        allResults = results.map((item) => ({ ...item, contentType: 'movie' }));
        totalCount = response.count || results.length;
      } else if (state.filters.type === 'series') {
        // Fetch only series
        const response = await api.getSeries(params);
        const results = response.results || response;
        allResults = results.map((item) => ({
          ...item,
          contentType: 'series',
        }));
        totalCount = response.count || results.length;
      } else {
        // Use the new unified backend endpoint for 'all' view
        const response = await api.getAllContent(params);
        console.log('getAllContent response:', response);
        console.log('response type:', typeof response);
        console.log(
          'response keys:',
          response ? Object.keys(response) : 'no response'
        );

        const results = response.results || response;
        console.log('results:', results);
        console.log('results type:', typeof results);
        console.log('results is array:', Array.isArray(results));

        // Check if results is actually an array before calling map
        if (!Array.isArray(results)) {
          console.error('Results is not an array:', results);
          throw new Error('Invalid response format - results is not an array');
        }

        // The backend already provides content_type and proper sorting/pagination
        allResults = results.map((item) => ({
          ...item,
          contentType: item.content_type, // Backend provides this field
        }));
        totalCount = response.count || results.length;
      }

      // Store the current page results directly (don't accumulate all pages)
      set({
        currentPageContent: allResults, // This is the paginated data for current page
        totalCount,
        loading: false,
      });
    } catch (error) {
      console.error('Failed to fetch content:', error);
      set({ error: 'Failed to load content.', loading: false });
    }
  },

  fetchSeriesEpisodes: async (seriesId) => {
    set({ loading: true, error: null });
    try {
      const response = await api.getSeriesEpisodes(seriesId);

      set((state) => ({
        episodes: {
          ...state.episodes,
          ...response.reduce((acc, episode) => {
            acc[episode.id] = episode;
            return acc;
          }, {}),
        },
        loading: false,
      }));

      return response;
    } catch (error) {
      console.error('Failed to fetch series episodes:', error);
      set({ error: 'Failed to load episodes.', loading: false });
      throw error; // Re-throw to allow calling component to handle
    }
  },

  fetchMovieDetails: async (movieId) => {
    set({ loading: true, error: null });
    try {
      const response = await api.getMovieDetails(movieId);

      // Transform the response data to match our expected format
      const movieDetails = {
        id: response.id || movieId,
        name: response.name || '',
        description: response.description || '',
        year: response.year || null,
        genre: response.genre || '',
        rating: response.rating || '',
        duration_secs: response.duration_secs || null,
        stream_url: response.url || '',
        logo: response.logo_url || null,
        type: 'movie',
        director: response.director || '',
        actors: response.actors || '',
        country: response.country || '',
        tmdb_id: response.tmdb_id || '',
        imdb_id: response.imdb_id || '',
        m3u_account: response.m3u_account || '',
      };
      console.log('Fetched Movie Details:', movieDetails);
      set((state) => ({
        content: {
          ...state.content,
          [`movie_${movieDetails.id}`]: {
            ...movieDetails,
            contentType: 'movie',
          },
        },
        loading: false,
      }));

      return movieDetails;
    } catch (error) {
      console.error('Failed to fetch movie details:', error);
      set({ error: 'Failed to load movie details.', loading: false });
      throw error;
    }
  },

  fetchMovieDetailsFromProvider: async (movieId) => {
    set({ loading: true, error: null });
    try {
      const response = await api.getMovieProviderInfo(movieId);

      // Transform the response data to match our expected format
      const movieDetails = {
        id: response.id || movieId,
        name: response.name || '',
        description: response.description || response.plot || '',
        year: response.year || null,
        genre: response.genre || '',
        rating: response.rating || '',
        duration_secs: response.duration_secs || null,
        stream_url: response.stream_url || '',
        logo: response.logo || response.cover || null,
        type: 'movie',
        director: response.director || '',
        actors: response.actors || response.cast || '',
        country: response.country || '',
        tmdb_id: response.tmdb_id || '',
        youtube_trailer: response.youtube_trailer || '',
        // Additional provider fields
        backdrop_path: response.backdrop_path || [],
        release_date: response.release_date || response.releasedate || '',
        movie_image: response.movie_image || null,
        o_name: response.o_name || '',
        age: response.age || '',
        episode_run_time: response.episode_run_time || null,
        bitrate: response.bitrate || 0,
        video: response.video || {},
        audio: response.audio || {},
      };

      set({ loading: false }); // Only update loading state

      // Do NOT merge or overwrite the store entry
      return movieDetails;
    } catch (error) {
      console.error('Failed to fetch movie details from provider:', error);
      set({
        error: 'Failed to load movie details from provider.',
        loading: false,
      });
      throw error;
    }
  },

  fetchMovieProviders: async (movieId) => {
    try {
      const response = await api.getMovieProviders(movieId);
      return response || [];
    } catch (error) {
      console.error('Failed to fetch movie providers:', error);
      throw error;
    }
  },

  fetchSeriesProviders: async (seriesId) => {
    try {
      const response = await api.getSeriesProviders(seriesId);
      return response || [];
    } catch (error) {
      console.error('Failed to fetch series providers:', error);
      throw error;
    }
  },

  fetchCategories: async () => {
    try {
      const response = await api.getVODCategories();
      // Handle both array and paginated responses
      const results = response.results || response;

      set({
        categories: results.reduce((acc, category) => {
          acc[category.id] = category;
          return acc;
        }, {}),
      });
    } catch (error) {
      console.error('Failed to fetch VOD categories:', error);
      set({ error: 'Failed to load categories.' });
    }
  },

  addMovie: (movie) =>
    set((state) => ({
      content: {
        ...state.content,
        [`movie_${movie.id}`]: { ...movie, contentType: 'movie' },
      },
    })),

  updateMovie: (movie) =>
    set((state) => ({
      content: {
        ...state.content,
        [`movie_${movie.id}`]: { ...movie, contentType: 'movie' },
      },
    })),

  removeMovie: (movieId) =>
    set((state) => {
      const updatedContent = { ...state.content };
      delete updatedContent[`movie_${movieId}`];
      return { content: updatedContent };
    }),

  addSeries: (series) =>
    set((state) => ({
      content: {
        ...state.content,
        [`series_${series.id}`]: { ...series, contentType: 'series' },
      },
    })),

  updateSeries: (series) =>
    set((state) => ({
      content: {
        ...state.content,
        [`series_${series.id}`]: { ...series, contentType: 'series' },
      },
    })),

  removeSeries: (seriesId) =>
    set((state) => {
      const updatedContent = { ...state.content };
      delete updatedContent[`series_${seriesId}`];
      return { content: updatedContent };
    }),

  fetchSeriesInfo: async (seriesId) => {
    set({ loading: true, error: null });
    try {
      const response = await api.getSeriesInfo(seriesId);

      // Transform the response data to match our expected format
      const seriesInfo = {
        id: response.id || seriesId,
        name: response.name || '',
        description:
          response.description || response.custom_properties?.plot || '',
        year: response.year || null,
        genre: response.genre || '',
        rating: response.rating || '',
        logo: response.cover || null,
        type: 'series',
        director: response.custom_properties?.director || '',
        cast: response.custom_properties?.cast || '',
        country: response.country || '',
        tmdb_id: response.tmdb_id || '',
        imdb_id: response.imdb_id || '',
        episode_count: response.episode_count || 0,
        // Additional provider fields
        backdrop_path: response.custom_properties?.backdrop_path || [],
        release_date: response.release_date || '',
        series_image: response.series_image || null,
        o_name: response.o_name || '',
        age: response.age || '',
        m3u_account: response.m3u_account || '',
        youtube_trailer: response.custom_properties?.youtube_trailer || '',
      };

      let episodesData = {};

      // Handle episodes - check if they're in the response
      if (response.episodes) {
        Object.entries(response.episodes).forEach(
          ([seasonNumber, seasonEpisodes]) => {
            seasonEpisodes.forEach((episode) => {
              const episodeData = {
                id: episode.id,
                stream_id: episode.id,
                name: episode.title || '',
                description: episode.plot || '',
                season_number: parseInt(seasonNumber) || 0,
                episode_number: episode.episode_number || 0,
                duration_secs: episode.duration_secs || null,
                rating: episode.rating || '',
                container_extension: episode.container_extension || '',
                series: {
                  id: seriesInfo.id,
                  name: seriesInfo.name,
                },
                type: 'episode',
                uuid: episode.id, // Use the stream ID as UUID for playback
                logo: episode.movie_image ? { url: episode.movie_image } : null,
                air_date: episode.air_date || null,
                movie_image: episode.movie_image || null,
                tmdb_id: episode.tmdb_id || '',
                imdb_id: episode.imdb_id || '',
              };
              episodesData[episode.id] = episodeData;
            });
          }
        );

        // Update episodes in the store
        set((state) => ({
          episodes: {
            ...state.episodes,
            ...episodesData,
          },
        }));
      }

      set((state) => ({
        content: {
          ...state.content,
          [`series_${seriesInfo.id}`]: { ...seriesInfo, contentType: 'series' },
        },
        loading: false,
      }));

      // Return series info with episodes array for easy access
      return {
        ...seriesInfo,
        episodesList: Object.values(episodesData),
      };
    } catch (error) {
      console.error('Failed to fetch series info:', error);
      set({ error: 'Failed to load series details.', loading: false });
      throw error;
    }
  },

  // Helper methods for getting filtered content
  getFilteredContent: () => {
    const state = get();
    // Return the current page content directly - backend handles all filtering/pagination
    return state.currentPageContent;
  },

  getMovies: () => {
    const state = get();
    return Object.values(state.content).filter(
      (item) => item.contentType === 'movie'
    );
  },

  getSeries: () => {
    const state = get();
    return Object.values(state.content).filter(
      (item) => item.contentType === 'series'
    );
  },

  clearContent: () => set({ content: {}, totalCount: 0 }),
}));

export default useVODStore;
