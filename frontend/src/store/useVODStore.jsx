import { create } from 'zustand';
import api from '../api';

let accessPolicyFetchSequence = 0;

const ACTIVE_PROFILE_BUILD_STATUSES = new Set(['pending', 'building']);
const TERMINAL_PROFILE_BUILD_STATUSES = new Set([
  'ready',
  'outdated',
  'failed',
]);
const LIST_CONFIRMATION_FIELD = '_awaitingListConfirmation';

const withoutListConfirmation = (profile) => {
  if (!profile?.[LIST_CONFIRMATION_FIELD]) return profile;
  const { [LIST_CONFIRMATION_FIELD]: _discarded, ...confirmed } = profile;
  return confirmed;
};

const lifecycleTimestamp = (profile, statusKind) => {
  const progress = profile?.selection_progress || {};
  const candidates =
    statusKind === 'active'
      ? [progress.updated_at, profile?.selection_started_at, progress.queued_at]
      : [progress.updated_at, profile?.selection_completed_at];
  for (const value of candidates) {
    const timestamp = Date.parse(value || '');
    if (Number.isFinite(timestamp)) return timestamp;
  }
  return null;
};

const keepNewerLocalProfileBuild = (current, incoming) => {
  const currentTaskId = current?.selection_progress?.task_id || '';
  const incomingTaskId = incoming?.selection_progress?.task_id || '';
  const currentBuildGeneration =
    current?.selection_progress?.build_generation || '';
  const incomingBuildGeneration =
    incoming?.selection_progress?.build_generation || '';

  if (
    TERMINAL_PROFILE_BUILD_STATUSES.has(current?.selection_status) &&
    TERMINAL_PROFILE_BUILD_STATUSES.has(incoming?.selection_status)
  ) {
    const currentUpdatedAt = lifecycleTimestamp(current, 'terminal');
    const incomingUpdatedAt = lifecycleTimestamp(incoming, 'terminal');
    if (
      currentUpdatedAt !== null &&
      incomingUpdatedAt !== null &&
      incomingUpdatedAt < currentUpdatedAt
    ) {
      return true;
    }
  }

  if (
    TERMINAL_PROFILE_BUILD_STATUSES.has(current?.selection_status) &&
    ACTIVE_PROFILE_BUILD_STATUSES.has(incoming?.selection_status)
  ) {
    const completedAt = lifecycleTimestamp(current, 'terminal');
    const heartbeatAt = lifecycleTimestamp(incoming, 'active');
    if (
      completedAt !== null &&
      heartbeatAt !== null &&
      heartbeatAt <= completedAt
    ) {
      // A delayed heartbeat from an older task can arrive after a different,
      // newer task activated the catalog. Task identity alone cannot detect
      // this cross-task ordering, but the persisted lifecycle timestamps can.
      return true;
    }
    // WebSocket heartbeats are delivered asynchronously. Once the terminal
    // event for one task/build was accepted, a delayed intermediate heartbeat
    // from that same run must never resurrect its progress bar.
    return Boolean(
      (currentTaskId && currentTaskId === incomingTaskId) ||
      (currentBuildGeneration &&
        currentBuildGeneration === incomingBuildGeneration) ||
      (current?.active_selection_generation &&
        current.active_selection_generation === incomingBuildGeneration)
    );
  }

  if (
    !ACTIVE_PROFILE_BUILD_STATUSES.has(current?.selection_status) ||
    ACTIVE_PROFILE_BUILD_STATUSES.has(incoming?.selection_status)
  ) {
    return false;
  }

  const currentHeartbeatAt = lifecycleTimestamp(current, 'active');
  const incomingCompletedAt = lifecycleTimestamp(incoming, 'terminal');
  if (
    incomingCompletedAt !== null &&
    currentHeartbeatAt !== null &&
    incomingCompletedAt >= currentHeartbeatAt
  ) {
    // The database/API terminal snapshot is newer than the last progress
    // heartbeat. Accept it even when a stale heartbeat already copied the new
    // active catalog generation into the local object.
    return false;
  }

  // A terminal result carrying the same task/build identity is authoritative.
  // This also accepts failures, which do not activate a new catalog generation.
  if (
    (currentTaskId && currentTaskId === incomingTaskId) ||
    (currentBuildGeneration &&
      currentBuildGeneration === incomingBuildGeneration)
  ) {
    return false;
  }

  if (incoming?.selection_status === 'ready') {
    const currentCatalogGeneration = current.active_selection_generation || '';
    const incomingCatalogGeneration =
      incoming.active_selection_generation || '';

    // Every successful full build activates a new immutable snapshot ID. A
    // Ready response that still names the old active snapshot is therefore a
    // delayed pre-save response and must not hide the running update.
    return (
      !incomingCatalogGeneration ||
      incomingCatalogGeneration === currentCatalogGeneration
    );
  }

  // A terminal response without either the current task identity or a newly
  // activated snapshot cannot prove that it belongs to this local save.
  return true;
};

const mergeAccessPolicyState = (current, incoming) => {
  if (!current) return incoming;
  if (keepNewerLocalProfileBuild(current, incoming)) return current;

  if (
    ACTIVE_PROFILE_BUILD_STATUSES.has(current?.selection_status) &&
    ACTIVE_PROFILE_BUILD_STATUSES.has(incoming?.selection_status)
  ) {
    const currentProgress = current.selection_progress || {};
    const incomingProgress = incoming.selection_progress || {};
    const currentTaskId = currentProgress.task_id || '';
    const incomingTaskId = incomingProgress.task_id || '';
    const currentBuildGeneration = currentProgress.build_generation || '';
    const incomingBuildGeneration = incomingProgress.build_generation || '';
    const sameBuild =
      (currentBuildGeneration &&
        currentBuildGeneration === incomingBuildGeneration) ||
      (currentTaskId && currentTaskId === incomingTaskId);
    const currentPercent = Number(currentProgress.percent);
    const incomingPercent = Number(incomingProgress.percent);

    // A profile list poll is a status snapshot, not an event stream. Preserve
    // the newest heartbeat when an older response for the same task/build is
    // delivered later by the browser or reverse proxy.
    if (
      sameBuild &&
      Number.isFinite(currentPercent) &&
      Number.isFinite(incomingPercent) &&
      incomingPercent < currentPercent
    ) {
      return {
        ...incoming,
        selection_status: current.selection_status,
        selection_started_at:
          current.selection_started_at || incoming.selection_started_at,
        selection_progress: currentProgress,
      };
    }
  }

  return incoming;
};

const getFetchContentParams = (state) => {
  const params = new URLSearchParams();
  params.append('page', state.currentPage);
  params.append('page_size', state.pageSize);
  params.append('type', state.filters.type);
  params.append('representation', state.filters.representation);

  if (state.filters.search) {
    params.append('search', state.filters.search);
  }

  if (state.filters.category) {
    params.append('category', state.filters.category);
  }
  if (state.filters.m3u_account) {
    params.append('m3u_account', state.filters.m3u_account);
  }
  for (const key of [
    'audio_language',
    'subtitle_language',
    'resolution',
    'container_extension',
    'video_feature',
    'metadata_status',
    'genre',
    'anime_mode',
    'adult_mode',
    'library_added_after',
  ]) {
    if (state.filters[key]) params.append(key, state.filters[key]);
  }
  return params;
};

const getMovieDetails = (response, movieId) => {
  return {
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
    tmdb: response.tmdb || null,
    m3u_account: response.m3u_account || '',
  };
};

const getMovieDetailsWithProvider = (response, movieId) => {
  return {
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
    imdb_id: response.imdb_id || '',
    tmdb: response.tmdb || null,
    canonical: response.canonical || null,
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
    source_metadata: response.source_metadata || null,
  };
};

const getSeriesDetails = (response, seriesId) => {
  return {
    id: response.id || seriesId,
    name: response.name || '',
    description: response.description || response.custom_properties?.plot || '',
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
    tmdb: response.tmdb || null,
    canonical: response.canonical || null,
    episode_count: response.episode_count || 0,
    // Additional provider fields
    backdrop_path: response.backdrop_path || [],
    release_date: response.release_date || '',
    series_image: response.series_image || null,
    o_name: response.o_name || '',
    age: response.age || '',
    m3u_account: response.m3u_account || '',
    youtube_trailer: response.custom_properties?.youtube_trailer || '',
    source_metadata: response.source_metadata || null,
  };
};

const getEpisodeDetails = (episode, seasonNumber, seriesInfo) => {
  return {
    id: episode.id,
    // `id` is the canonical Episode primary key. Playback must use the
    // provider's concrete stream ID returned by provider-info; otherwise a
    // perfectly valid canonical ID is sent as an XC stream ID and silently
    // falls through to an unrelated source.
    stream_id: episode.stream_id || '',
    relation_id: episode.relation_id || null,
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
    uuid: episode.uuid,
    logo: episode.movie_image
      ? { url: episode.movie_image, cache_url: episode.movie_image }
      : null,
    air_date: episode.air_date || null,
    movie_image: episode.movie_image || null,
    tmdb_id: episode.tmdb_id || '',
    imdb_id: episode.imdb_id || '',
  };
};

const useVODStore = create((set, get) => ({
  content: {}, // Store for individual content details (when fetching movie/series details)
  currentPageContent: [], // Store the current page's results
  episodes: {},
  categories: {},
  accessPolicies: [],
  loading: false,
  error: null,
  filters: {
    type: 'all', // 'all', 'movies', 'series'
    representation: 'canonical', // 'canonical', 'variants'
    search: '',
    category: '',
    m3u_account: '',
    audio_language: '',
    subtitle_language: '',
    resolution: '',
    container_extension: '',
    video_feature: '',
    metadata_status: '',
    genre: '',
    anime_mode: '',
    adult_mode: '',
    library_added_after: '',
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

      const params = getFetchContentParams(state);

      // One database-level endpoint keeps pagination, technical filters, and
      // select-all semantics identical for All, Movies, and Series.
      const response = await api.getAllContent(params);
      const results = response.results || response;
      if (!Array.isArray(results)) {
        throw new Error('Invalid response format - results is not an array');
      }
      const allResults = results.map((item) => ({
        ...item,
        contentType:
          item.content_type ||
          (state.filters.type === 'series' ? 'series' : 'movie'),
      }));
      const totalCount = response.count || results.length;

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

  fetchMovieDetails: async (movieId) => {
    set({ loading: true, error: null });
    try {
      const response = await api.getMovieDetails(movieId);

      // Transform the response data to match our expected format
      const movieDetails = getMovieDetails(response, movieId);
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

  fetchMovieDetailsFromProvider: async (movieId, relationId = null) => {
    set({ loading: true, error: null });
    try {
      const response = await api.getMovieProviderInfo(movieId, relationId);

      // Transform the response data to match our expected format
      const movieDetails = getMovieDetailsWithProvider(response, movieId);

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

  fetchAccessPolicies: async () => {
    const requestSequence = ++accessPolicyFetchSequence;
    try {
      const response = await api.getVODAccessPolicies();
      const results = response.results || response;
      if (requestSequence === accessPolicyFetchSequence) {
        set((state) => ({
          accessPolicies: Array.isArray(results)
            ? [
                ...results.map((incoming) => {
                  const current = state.accessPolicies.find(
                    (profile) => String(profile.id) === String(incoming.id)
                  );
                  return withoutListConfirmation(
                    mergeAccessPolicyState(current, incoming)
                  );
                }),
                ...state.accessPolicies.filter(
                  (current) =>
                    current[LIST_CONFIRMATION_FIELD] &&
                    !results.some(
                      (incoming) => String(incoming.id) === String(current.id)
                    )
                ),
              ].sort((left, right) => left.name.localeCompare(right.name))
            : [],
        }));
      }
      return results;
    } catch (error) {
      console.error('Failed to fetch VOD output profiles:', error);
      if (requestSequence === accessPolicyFetchSequence) {
        set({ error: 'Failed to load VOD output profiles.' });
      }
      return [];
    }
  },

  applyAccessPolicyProgress: (update) => {
    if (!update?.profile_id) return;
    set((state) => ({
      accessPolicies: state.accessPolicies.map((current) => {
        if (String(current.id) !== String(update.profile_id)) return current;
        const nextStatus = update.selection_status || current.selection_status;
        const incoming = {
          ...current,
          selection_status: nextStatus,
          selection_current:
            nextStatus === 'ready'
              ? true
              : nextStatus === 'outdated'
                ? false
                : current.selection_current,
          selection_available:
            nextStatus === 'ready' ? true : current.selection_available,
          selection_progress:
            update.selection_progress || current.selection_progress,
          active_selection_generation:
            update.active_selection_generation ||
            current.active_selection_generation,
          selection_completed_at:
            update.selection_completed_at || current.selection_completed_at,
        };
        return mergeAccessPolicyState(current, incoming);
      }),
    }));
  },

  upsertAccessPolicy: (
    policy,
    { force = false, preserveIfMissing = false } = {}
  ) => {
    if (!policy?.id) return;
    // A response requested before this mutation must not restore stale status
    // or category rules after the mutation response has been applied.
    accessPolicyFetchSequence += 1;
    set((state) => {
      const exists = state.accessPolicies.some(
        (current) => String(current.id) === String(policy.id)
      );
      const incoming = preserveIfMissing
        ? { ...policy, [LIST_CONFIRMATION_FIELD]: true }
        : policy;
      const accessPolicies = exists
        ? state.accessPolicies.map((current) =>
            String(current.id) === String(policy.id)
              ? !force
                ? mergeAccessPolicyState(current, incoming)
                : incoming
              : current
          )
        : [...state.accessPolicies, incoming];
      return {
        accessPolicies: accessPolicies.sort((left, right) =>
          left.name.localeCompare(right.name)
        ),
      };
    });
  },

  removeAccessPolicy: (policyId) => {
    // A polling response that started before deletion must not restore the
    // deleted profile when it arrives later.
    accessPolicyFetchSequence += 1;
    set((state) => ({
      accessPolicies: state.accessPolicies.filter(
        (policy) => String(policy.id) !== String(policyId)
      ),
    }));
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

  fetchSeriesInfo: async (seriesId, relationId = null) => {
    set({ loading: true, error: null });
    try {
      const response = await api.getSeriesInfo(seriesId, relationId);

      // Transform the response data to match our expected format
      const seriesInfo = getSeriesDetails(response, seriesId);

      let episodesData = {};

      // Handle episodes - check if they're in the response
      if (response.episodes) {
        Object.entries(response.episodes).forEach(
          ([seasonNumber, seasonEpisodes]) => {
            seasonEpisodes.forEach((episode) => {
              episodesData[episode.id] = getEpisodeDetails(
                episode,
                seasonNumber,
                seriesInfo
              );
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
