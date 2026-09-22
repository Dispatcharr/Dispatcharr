import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import useVODStore from '../useVODStore';
import api from '../../api';

vi.mock('../../api');

describe('useVODStore', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useVODStore.setState({
      content: {},
      currentPageContent: [],
      episodes: {},
      categories: {},
      accessPolicies: [],
      loading: false,
      error: null,
      filters: {
        type: 'all',
        search: '',
        category: '',
        m3u_account: '',
        audio_language: '',
        subtitle_language: '',
        resolution: '',
        container_extension: '',
      },
      currentPage: 1,
      totalCount: 0,
      pageSize: 24,
    });
  });

  it('should initialize with default state', () => {
    const { result } = renderHook(() => useVODStore());

    expect(result.current.content).toEqual({});
    expect(result.current.currentPageContent).toEqual([]);
    expect(result.current.episodes).toEqual({});
    expect(result.current.categories).toEqual({});
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBe(null);
    expect(result.current.filters).toEqual({
      type: 'all',
      search: '',
      category: '',
      m3u_account: '',
      audio_language: '',
      subtitle_language: '',
      resolution: '',
      container_extension: '',
    });
    expect(result.current.currentPage).toBe(1);
    expect(result.current.totalCount).toBe(0);
    expect(result.current.pageSize).toBe(24);
  });

  it('should set filters and reset to first page', () => {
    useVODStore.setState({ currentPage: 5 });
    const { result } = renderHook(() => useVODStore());

    act(() => {
      result.current.setFilters({ search: 'test', category: 'action' });
    });

    expect(result.current.filters).toEqual({
      type: 'all',
      search: 'test',
      category: 'action',
      m3u_account: '',
      audio_language: '',
      subtitle_language: '',
      resolution: '',
      container_extension: '',
    });
    expect(result.current.currentPage).toBe(1);
  });

  it('should set page', () => {
    const { result } = renderHook(() => useVODStore());

    act(() => {
      result.current.setPage(3);
    });

    expect(result.current.currentPage).toBe(3);
  });

  it('should set page size and reset to first page', () => {
    useVODStore.setState({ currentPage: 3 });
    const { result } = renderHook(() => useVODStore());

    act(() => {
      result.current.setPageSize(50);
    });

    expect(result.current.pageSize).toBe(50);
    expect(result.current.currentPage).toBe(1);
  });

  it('does not restore a deleted profile from an older polling response', async () => {
    let resolveRequest;
    api.getVODAccessPolicies.mockReturnValue(
      new Promise((resolve) => {
        resolveRequest = resolve;
      })
    );
    useVODStore.setState({
      accessPolicies: [
        { id: 1, name: 'Default' },
        { id: 2, name: 'Delete me' },
      ],
    });
    const { result } = renderHook(() => useVODStore());

    let pendingFetch;
    act(() => {
      pendingFetch = result.current.fetchAccessPolicies();
    });
    act(() => {
      result.current.removeAccessPolicy(2);
    });
    await act(async () => {
      resolveRequest([
        { id: 1, name: 'Default' },
        { id: 2, name: 'Delete me' },
      ]);
      await pendingFetch;
    });

    expect(result.current.accessPolicies).toEqual([{ id: 1, name: 'Default' }]);
  });

  it('does not overwrite a saved profile with an older polling response', async () => {
    let resolveRequest;
    api.getVODAccessPolicies.mockReturnValue(
      new Promise((resolve) => {
        resolveRequest = resolve;
      })
    );
    useVODStore.setState({
      accessPolicies: [{ id: 1, name: 'German', category_rules: [] }],
    });
    const { result } = renderHook(() => useVODStore());

    let pendingFetch;
    act(() => {
      pendingFetch = result.current.fetchAccessPolicies();
    });
    act(() => {
      result.current.upsertAccessPolicy({
        id: 1,
        name: 'German',
        selection_status: 'pending',
        category_rules: [{ category_relation: 12, enabled: true }],
      });
    });
    await act(async () => {
      resolveRequest([{ id: 1, name: 'German', category_rules: [] }]);
      await pendingFetch;
    });

    expect(result.current.accessPolicies[0]).toEqual(
      expect.objectContaining({
        selection_status: 'pending',
        category_rules: [{ category_relation: 12, enabled: true }],
      })
    );
  });

  it('keeps a newly created profile until the list endpoint confirms it', async () => {
    const existing = { id: 1, name: 'German', selection_status: 'ready' };
    const created = {
      id: 2,
      name: 'English',
      selection_status: 'pending',
      selection_progress: { phase: 'Publishing background task', percent: 0 },
    };
    useVODStore.setState({ accessPolicies: [existing] });
    api.getVODAccessPolicies
      .mockResolvedValueOnce([existing])
      .mockResolvedValueOnce([
        existing,
        {
          ...created,
          selection_status: 'building',
          selection_progress: { phase: 'Selecting movies', percent: 20 },
        },
      ]);
    const { result } = renderHook(() => useVODStore());

    act(() => {
      result.current.upsertAccessPolicy(created, {
        preserveIfMissing: true,
      });
    });
    await act(async () => {
      await result.current.fetchAccessPolicies();
    });

    expect(result.current.accessPolicies).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: 2,
          selection_status: 'pending',
        }),
      ])
    );

    await act(async () => {
      await result.current.fetchAccessPolicies();
    });

    const confirmed = result.current.accessPolicies.find(
      (profile) => profile.id === 2
    );
    expect(confirmed).toEqual(
      expect.objectContaining({
        selection_status: 'building',
        selection_progress: expect.objectContaining({ percent: 20 }),
      })
    );
    expect(confirmed).not.toHaveProperty('_awaitingListConfirmation');
  });

  it('accepts a completed build with a new catalog generation despite clock skew', async () => {
    useVODStore.setState({
      accessPolicies: [
        {
          id: 1,
          name: 'English',
          selection_status: 'building',
          selection_started_at: '2026-09-11T09:00:00Z',
          selection_completed_at: '2026-09-11T08:00:00Z',
          active_selection_generation: 'old-catalog',
          selection_progress: { task_id: 'current-task' },
        },
      ],
    });
    api.getVODAccessPolicies.mockResolvedValueOnce([
      {
        id: 1,
        name: 'English',
        selection_status: 'ready',
        selection_completed_at: '2026-09-11T08:00:00Z',
        active_selection_generation: 'new-catalog',
        selection_progress: { task_id: 'current-task' },
      },
    ]);
    const { result } = renderHook(() => useVODStore());

    await act(async () => {
      await result.current.fetchAccessPolicies();
    });

    expect(result.current.accessPolicies[0]).toEqual(
      expect.objectContaining({
        selection_status: 'ready',
        selection_completed_at: '2026-09-11T08:00:00Z',
        active_selection_generation: 'new-catalog',
      })
    );
  });

  it('keeps showing a running save when a poll returns the old ready snapshot', async () => {
    useVODStore.setState({
      accessPolicies: [
        {
          id: 1,
          name: 'English',
          selection_status: 'building',
          active_selection_generation: 'old-catalog',
          selection_progress: {
            task_id: 'new-task',
            build_generation: 'new-build',
            percent: 36,
          },
        },
      ],
    });
    api.getVODAccessPolicies.mockResolvedValueOnce([
      {
        id: 1,
        name: 'English',
        selection_status: 'ready',
        selection_current: true,
        active_selection_generation: 'old-catalog',
        selection_progress: {
          task_id: 'old-task',
          build_generation: 'old-catalog',
          percent: 100,
        },
      },
    ]);
    const { result } = renderHook(() => useVODStore());

    await act(async () => {
      await result.current.fetchAccessPolicies();
    });

    expect(result.current.accessPolicies[0]).toEqual(
      expect.objectContaining({
        selection_status: 'building',
        active_selection_generation: 'old-catalog',
        selection_progress: expect.objectContaining({
          task_id: 'new-task',
          percent: 36,
        }),
      })
    );
  });

  it('does not let progress move backwards within the same catalog task', async () => {
    useVODStore.setState({
      accessPolicies: [
        {
          id: 1,
          name: 'English',
          selection_status: 'building',
          selection_progress: {
            task_id: 'catalog-task',
            build_generation: 'catalog-build',
            percent: 28,
            phase: 'Selecting movies sources',
          },
        },
      ],
    });
    api.getVODAccessPolicies.mockResolvedValueOnce([
      {
        id: 1,
        name: 'English',
        selection_status: 'building',
        selection_progress: {
          task_id: 'catalog-task',
          build_generation: 'catalog-build',
          percent: 2,
          phase: 'Selecting movies sources',
        },
      },
    ]);
    const { result } = renderHook(() => useVODStore());

    await act(async () => {
      await result.current.fetchAccessPolicies();
    });

    expect(result.current.accessPolicies[0].selection_progress).toEqual(
      expect.objectContaining({
        task_id: 'catalog-task',
        build_generation: 'catalog-build',
        percent: 28,
      })
    );
  });

  it('accepts ready when the API reports a newly activated snapshot', async () => {
    useVODStore.setState({
      accessPolicies: [
        {
          id: 1,
          name: 'English',
          selection_status: 'building',
          active_selection_generation: 'old-catalog',
          selection_progress: {
            task_id: 'catalog-task',
            build_generation: 'catalog-build',
            percent: 28,
          },
        },
      ],
    });
    api.getVODAccessPolicies.mockResolvedValueOnce([
      {
        id: 1,
        name: 'English',
        selection_status: 'ready',
        selection_current: true,
        active_selection_generation: 'new-catalog',
        selection_progress: { phase: 'Ready', percent: 100 },
      },
    ]);
    const { result } = renderHook(() => useVODStore());

    await act(async () => {
      await result.current.fetchAccessPolicies();
    });

    expect(result.current.accessPolicies[0]).toEqual(
      expect.objectContaining({
        selection_status: 'ready',
        active_selection_generation: 'new-catalog',
        selection_progress: expect.objectContaining({ percent: 100 }),
      })
    );
  });

  it('applies pushed catalog progress and completion to the known profile', () => {
    useVODStore.setState({
      accessPolicies: [
        {
          id: 1,
          name: 'English',
          selection_status: 'building',
          active_selection_generation: 'old-catalog',
          selection_progress: {
            task_id: 'catalog-task',
            build_generation: 'catalog-build',
            percent: 36,
          },
        },
      ],
    });
    const { result } = renderHook(() => useVODStore());

    act(() => {
      result.current.applyAccessPolicyProgress({
        profile_id: 1,
        selection_status: 'building',
        selection_progress: {
          task_id: 'catalog-task',
          build_generation: 'catalog-build',
          percent: 44,
        },
      });
    });
    expect(result.current.accessPolicies[0].selection_progress.percent).toBe(
      44
    );

    act(() => {
      result.current.applyAccessPolicyProgress({
        profile_id: 1,
        selection_status: 'ready',
        active_selection_generation: 'new-catalog',
        selection_completed_at: '2026-09-11T13:00:00Z',
        selection_progress: { phase: 'Ready', percent: 100 },
      });
    });
    expect(result.current.accessPolicies[0]).toEqual(
      expect.objectContaining({
        selection_status: 'ready',
        selection_current: true,
        selection_available: true,
        active_selection_generation: 'new-catalog',
        selection_completed_at: '2026-09-11T13:00:00Z',
        selection_progress: expect.objectContaining({ percent: 100 }),
      })
    );
  });

  it('does not let an older outdated poll replace a pushed ready result', async () => {
    useVODStore.setState({
      accessPolicies: [
        {
          id: 1,
          name: 'English',
          selection_status: 'ready',
          selection_current: true,
          active_selection_generation: 'new-catalog',
          selection_completed_at: '2026-09-11T16:12:08Z',
          selection_progress: {
            phase: 'Ready',
            percent: 100,
            updated_at: '2026-09-11T16:12:08Z',
          },
        },
      ],
    });
    api.getVODAccessPolicies.mockResolvedValueOnce([
      {
        id: 1,
        name: 'English',
        selection_status: 'outdated',
        selection_current: false,
        active_selection_generation: 'old-catalog',
        selection_progress: {
          phase: 'Catalog rebuild required',
          percent: 0,
          updated_at: '2026-09-11T16:11:30Z',
        },
      },
    ]);
    const { result } = renderHook(() => useVODStore());

    await act(async () => {
      await result.current.fetchAccessPolicies();
    });

    expect(result.current.accessPolicies[0]).toEqual(
      expect.objectContaining({
        selection_status: 'ready',
        selection_current: true,
        active_selection_generation: 'new-catalog',
      })
    );
  });

  it('accepts a newer outdated result after a completed build', async () => {
    useVODStore.setState({
      accessPolicies: [
        {
          id: 1,
          name: 'English',
          selection_status: 'ready',
          selection_current: true,
          selection_completed_at: '2026-09-11T16:12:08Z',
          selection_progress: {
            phase: 'Ready',
            percent: 100,
            updated_at: '2026-09-11T16:12:08Z',
          },
        },
      ],
    });
    api.getVODAccessPolicies.mockResolvedValueOnce([
      {
        id: 1,
        name: 'English',
        selection_status: 'outdated',
        selection_current: false,
        selection_progress: {
          phase: 'Catalog rebuild required',
          percent: 0,
          updated_at: '2026-09-11T16:13:00Z',
        },
      },
    ]);
    const { result } = renderHook(() => useVODStore());

    await act(async () => {
      await result.current.fetchAccessPolicies();
    });

    expect(result.current.accessPolicies[0]).toEqual(
      expect.objectContaining({
        selection_status: 'outdated',
        selection_current: false,
      })
    );
  });

  it('ignores a delayed heartbeat after the same task is already ready', () => {
    useVODStore.setState({
      accessPolicies: [
        {
          id: 1,
          name: 'English',
          selection_status: 'ready',
          active_selection_generation: 'catalog-build',
          selection_progress: {
            task_id: 'catalog-task',
            build_generation: 'catalog-build',
            phase: 'Ready',
            percent: 100,
          },
        },
      ],
    });
    const { result } = renderHook(() => useVODStore());

    act(() => {
      result.current.applyAccessPolicyProgress({
        profile_id: 1,
        selection_status: 'building',
        selection_progress: {
          task_id: 'catalog-task',
          build_generation: 'catalog-build',
          phase: 'Selecting movies sources',
          percent: 20,
        },
      });
    });

    expect(result.current.accessPolicies[0]).toEqual(
      expect.objectContaining({
        selection_status: 'ready',
        active_selection_generation: 'catalog-build',
        selection_progress: expect.objectContaining({
          phase: 'Ready',
          percent: 100,
        }),
      })
    );
  });

  it('does not let an old build heartbeat hide an outdated profile', () => {
    useVODStore.setState({
      accessPolicies: [
        {
          id: 1,
          name: 'English',
          selection_status: 'outdated',
          active_selection_generation: 'last-ready-catalog',
          selection_completed_at: '2026-09-11T16:00:00Z',
          selection_progress: {
            phase: 'Catalog rebuild required',
            percent: 0,
            updated_at: '2026-09-11T16:15:00Z',
          },
        },
      ],
    });
    const { result } = renderHook(() => useVODStore());

    act(() => {
      result.current.applyAccessPolicyProgress({
        profile_id: 1,
        selection_status: 'building',
        selection_progress: {
          task_id: 'old-task',
          build_generation: 'old-build',
          phase: 'Selecting movies sources',
          percent: 40,
          updated_at: '2026-09-11T16:10:00Z',
        },
      });
    });

    expect(result.current.accessPolicies[0]).toEqual(
      expect.objectContaining({
        selection_status: 'outdated',
        selection_progress: expect.objectContaining({
          phase: 'Catalog rebuild required',
        }),
      })
    );
  });

  it('ignores a delayed heartbeat from an older task after a newer task is ready', () => {
    useVODStore.setState({
      accessPolicies: [
        {
          id: 1,
          name: 'English',
          selection_status: 'ready',
          active_selection_generation: 'new-catalog',
          selection_completed_at: '2026-09-11T16:12:08Z',
          selection_progress: {
            task_id: 'new-task',
            build_generation: 'new-catalog',
            phase: 'Ready',
            percent: 100,
            updated_at: '2026-09-11T16:12:08Z',
          },
        },
      ],
    });
    const { result } = renderHook(() => useVODStore());

    act(() => {
      result.current.applyAccessPolicyProgress({
        profile_id: 1,
        selection_status: 'building',
        selection_started_at: '2026-09-11T16:00:00Z',
        selection_progress: {
          task_id: 'old-task',
          build_generation: 'old-build',
          phase: 'Selecting movies sources',
          percent: 24,
          updated_at: '2026-09-11T16:11:51Z',
        },
      });
    });

    expect(result.current.accessPolicies[0]).toEqual(
      expect.objectContaining({
        selection_status: 'ready',
        active_selection_generation: 'new-catalog',
        selection_progress: expect.objectContaining({
          task_id: 'new-task',
          percent: 100,
        }),
      })
    );
  });

  it('replaces a resurrected stale heartbeat with the newer API ready state', async () => {
    useVODStore.setState({
      accessPolicies: [
        {
          id: 1,
          name: 'English',
          selection_status: 'building',
          // A delayed event may have inherited the already activated catalog.
          active_selection_generation: 'new-catalog',
          selection_started_at: '2026-09-11T16:00:00Z',
          selection_progress: {
            task_id: 'old-task',
            build_generation: 'old-build',
            phase: 'Selecting movies sources',
            percent: 24,
            updated_at: '2026-09-11T16:11:51Z',
          },
        },
      ],
    });
    api.getVODAccessPolicies.mockResolvedValueOnce([
      {
        id: 1,
        name: 'English',
        selection_status: 'ready',
        selection_current: true,
        active_selection_generation: 'new-catalog',
        selection_completed_at: '2026-09-11T16:12:08Z',
        selection_progress: {
          task_id: 'new-task',
          build_generation: 'new-catalog',
          phase: 'Ready',
          percent: 100,
          updated_at: '2026-09-11T16:12:08Z',
        },
      },
    ]);
    const { result } = renderHook(() => useVODStore());

    await act(async () => {
      await result.current.fetchAccessPolicies();
    });

    expect(result.current.accessPolicies[0]).toEqual(
      expect.objectContaining({
        selection_status: 'ready',
        active_selection_generation: 'new-catalog',
        selection_progress: expect.objectContaining({
          task_id: 'new-task',
          percent: 100,
        }),
      })
    );
  });

  it('does not let a stale save response replace its optimistic build status', () => {
    useVODStore.setState({
      accessPolicies: [
        {
          id: 1,
          name: 'English updated',
          selection_status: 'pending',
          selection_started_at: '2026-09-11T09:00:00Z',
          selection_completed_at: '2026-09-11T08:00:00Z',
        },
      ],
    });
    const { result } = renderHook(() => useVODStore());

    act(() => {
      result.current.upsertAccessPolicy({
        id: 1,
        name: 'English updated',
        selection_status: 'ready',
        selection_completed_at: '2026-09-11T08:00:00Z',
      });
    });

    expect(result.current.accessPolicies[0].selection_status).toBe('pending');

    act(() => {
      result.current.upsertAccessPolicy(
        {
          id: 1,
          name: 'English',
          selection_status: 'ready',
          selection_completed_at: '2026-09-11T08:00:00Z',
        },
        { force: true }
      );
    });

    expect(result.current.accessPolicies[0]).toEqual(
      expect.objectContaining({ name: 'English', selection_status: 'ready' })
    );
  });

  it('should fetch all content successfully', async () => {
    const mockResponse = {
      results: [
        { id: 1, name: 'Movie 1', content_type: 'movie' },
        { id: 2, name: 'Series 1', content_type: 'series' },
      ],
      count: 2,
    };

    api.getAllContent.mockResolvedValue(mockResponse);

    const { result } = renderHook(() => useVODStore());

    await act(async () => {
      await result.current.fetchContent();
    });

    expect(api.getAllContent).toHaveBeenCalled();
    expect(result.current.currentPageContent).toEqual([
      { id: 1, name: 'Movie 1', content_type: 'movie', contentType: 'movie' },
      {
        id: 2,
        name: 'Series 1',
        content_type: 'series',
        contentType: 'series',
      },
    ]);
    expect(result.current.totalCount).toBe(2);
    expect(result.current.loading).toBe(false);
  });

  it('should fetch only movies when filter type is movies', async () => {
    const mockResponse = {
      results: [
        { id: 1, name: 'Movie 1' },
        { id: 2, name: 'Movie 2' },
      ],
      count: 2,
    };

    api.getAllContent.mockResolvedValue(mockResponse);

    const { result } = renderHook(() => useVODStore());

    act(() => {
      result.current.setFilters({ type: 'movies' });
    });

    await act(async () => {
      await result.current.fetchContent();
    });

    expect(api.getAllContent).toHaveBeenCalled();
    expect(api.getAllContent.mock.calls[0][0].get('type')).toBe('movies');
    expect(result.current.currentPageContent).toEqual([
      { id: 1, name: 'Movie 1', contentType: 'movie' },
      { id: 2, name: 'Movie 2', contentType: 'movie' },
    ]);
    expect(result.current.totalCount).toBe(2);
  });

  it('should fetch only series when filter type is series', async () => {
    const mockResponse = {
      results: [
        { id: 1, name: 'Series 1' },
        { id: 2, name: 'Series 2' },
      ],
      count: 2,
    };

    api.getAllContent.mockResolvedValue(mockResponse);

    const { result } = renderHook(() => useVODStore());

    act(() => {
      result.current.setFilters({ type: 'series' });
    });

    await act(async () => {
      await result.current.fetchContent();
    });

    expect(api.getAllContent).toHaveBeenCalled();
    expect(api.getAllContent.mock.calls[0][0].get('type')).toBe('series');
    expect(result.current.currentPageContent).toEqual([
      { id: 1, name: 'Series 1', contentType: 'series' },
      { id: 2, name: 'Series 2', contentType: 'series' },
    ]);
    expect(result.current.totalCount).toBe(2);
  });

  it('should handle fetch content error', async () => {
    const mockError = new Error('Network error');
    api.getAllContent.mockRejectedValue(mockError);

    const consoleErrorSpy = vi
      .spyOn(console, 'error')
      .mockImplementation(() => {});

    const { result } = renderHook(() => useVODStore());

    await act(async () => {
      await result.current.fetchContent();
    });

    expect(result.current.error).toBe('Failed to load content.');
    expect(result.current.loading).toBe(false);
    expect(consoleErrorSpy).toHaveBeenCalledWith(
      'Failed to fetch content:',
      mockError
    );

    consoleErrorSpy.mockRestore();
  });

  it('should handle invalid response format', async () => {
    api.getAllContent.mockResolvedValue({ results: 'not-an-array' });

    const consoleErrorSpy = vi
      .spyOn(console, 'error')
      .mockImplementation(() => {});

    const { result } = renderHook(() => useVODStore());

    await act(async () => {
      await result.current.fetchContent();
    });

    expect(result.current.error).toBe('Failed to load content.');
    expect(consoleErrorSpy).toHaveBeenCalled();

    consoleErrorSpy.mockRestore();
  });

  it('should fetch movie details successfully', async () => {
    const mockResponse = {
      id: 1,
      name: 'Test Movie',
      description: 'A test movie',
      year: 2023,
      url: 'http://example.com/movie.mp4',
    };

    api.getMovieDetails.mockResolvedValue(mockResponse);

    const { result } = renderHook(() => useVODStore());

    let movieDetails;
    await act(async () => {
      movieDetails = await result.current.fetchMovieDetails(1);
    });

    expect(api.getMovieDetails).toHaveBeenCalledWith(1);
    expect(movieDetails.id).toBe(1);
    expect(movieDetails.name).toBe('Test Movie');
    expect(movieDetails.stream_url).toBe('http://example.com/movie.mp4');
    expect(result.current.content['movie_1']).toBeDefined();
    expect(result.current.content['movie_1'].contentType).toBe('movie');
    expect(result.current.loading).toBe(false);
  });

  it('should handle fetch movie details error', async () => {
    const mockError = new Error('Not found');
    api.getMovieDetails.mockRejectedValue(mockError);

    const consoleErrorSpy = vi
      .spyOn(console, 'error')
      .mockImplementation(() => {});

    const { result } = renderHook(() => useVODStore());

    await act(async () => {
      try {
        await result.current.fetchMovieDetails(999);
      } catch (error) {
        expect(error).toBe(mockError);
      }
    });

    expect(result.current.error).toBe('Failed to load movie details.');
    expect(result.current.loading).toBe(false);
    expect(consoleErrorSpy).toHaveBeenCalledWith(
      'Failed to fetch movie details:',
      mockError
    );

    consoleErrorSpy.mockRestore();
  });

  it('should fetch movie details from provider without merging to store', async () => {
    const mockResponse = {
      id: 1,
      name: 'Provider Movie',
      plot: 'From provider',
      stream_url: 'http://provider.com/movie.mp4',
      backdrop_path: ['path1', 'path2'],
      source_metadata: { values: { bitrate_kbps: 4200 } },
    };

    api.getMovieProviderInfo.mockResolvedValue(mockResponse);

    const { result } = renderHook(() => useVODStore());

    let movieDetails;
    await act(async () => {
      movieDetails = await result.current.fetchMovieDetailsFromProvider(1);
    });

    expect(api.getMovieProviderInfo).toHaveBeenCalledWith(1, null);
    expect(movieDetails.name).toBe('Provider Movie');
    expect(movieDetails.description).toBe('From provider');
    expect(movieDetails.backdrop_path).toEqual(['path1', 'path2']);
    expect(movieDetails.source_metadata).toEqual({
      values: { bitrate_kbps: 4200 },
    });
    expect(result.current.content['movie_1']).toBeUndefined();
    expect(result.current.loading).toBe(false);
  });

  it('should handle fetch movie provider error', async () => {
    const mockError = new Error('Provider error');
    api.getMovieProviderInfo.mockRejectedValue(mockError);

    const consoleErrorSpy = vi
      .spyOn(console, 'error')
      .mockImplementation(() => {});

    const { result } = renderHook(() => useVODStore());

    await act(async () => {
      try {
        await result.current.fetchMovieDetailsFromProvider(1);
      } catch (error) {
        expect(error).toBe(mockError);
      }
    });

    expect(result.current.error).toBe(
      'Failed to load movie details from provider.'
    );
    expect(consoleErrorSpy).toHaveBeenCalledWith(
      'Failed to fetch movie details from provider:',
      mockError
    );

    consoleErrorSpy.mockRestore();
  });

  it('should fetch movie providers successfully', async () => {
    const mockProviders = [
      { id: 1, name: 'Provider 1' },
      { id: 2, name: 'Provider 2' },
    ];

    api.getMovieProviders.mockResolvedValue(mockProviders);

    const { result } = renderHook(() => useVODStore());

    let providers;
    await act(async () => {
      providers = await result.current.fetchMovieProviders(1);
    });

    expect(api.getMovieProviders).toHaveBeenCalledWith(1);
    expect(providers).toEqual(mockProviders);
  });

  it('should handle fetch movie providers error', async () => {
    const mockError = new Error('Providers error');
    api.getMovieProviders.mockRejectedValue(mockError);

    const consoleErrorSpy = vi
      .spyOn(console, 'error')
      .mockImplementation(() => {});

    const { result } = renderHook(() => useVODStore());

    await act(async () => {
      try {
        await result.current.fetchMovieProviders(1);
      } catch (error) {
        expect(error).toBe(mockError);
      }
    });

    expect(consoleErrorSpy).toHaveBeenCalledWith(
      'Failed to fetch movie providers:',
      mockError
    );

    consoleErrorSpy.mockRestore();
  });

  it('should fetch series providers successfully', async () => {
    const mockProviders = [{ id: 1, name: 'Series Provider 1' }];

    api.getSeriesProviders.mockResolvedValue(mockProviders);

    const { result } = renderHook(() => useVODStore());

    let providers;
    await act(async () => {
      providers = await result.current.fetchSeriesProviders(1);
    });

    expect(api.getSeriesProviders).toHaveBeenCalledWith(1);
    expect(providers).toEqual(mockProviders);
  });

  it('should handle fetch series providers error', async () => {
    const mockError = new Error('Series providers error');
    api.getSeriesProviders.mockRejectedValue(mockError);

    const consoleErrorSpy = vi
      .spyOn(console, 'error')
      .mockImplementation(() => {});

    const { result } = renderHook(() => useVODStore());

    await act(async () => {
      try {
        await result.current.fetchSeriesProviders(1);
      } catch (error) {
        expect(error).toBe(mockError);
      }
    });

    expect(consoleErrorSpy).toHaveBeenCalledWith(
      'Failed to fetch series providers:',
      mockError
    );

    consoleErrorSpy.mockRestore();
  });

  it('should fetch series info successfully', async () => {
    const mockResponse = {
      id: 1,
      name: 'Test Series',
      description: 'A test series',
      year: 2023,
      cover: 'http://example.com/cover.jpg',
      source_metadata: { values: { video_codec: 'hevc' } },
      episodes: {
        1: [
          {
            id: 101,
            relation_id: 9001,
            stream_id: 'provider-episode-101',
            title: 'Episode 1',
            episode_number: 1,
            plot: 'First episode',
          },
          {
            id: 102,
            title: 'Episode 2',
            episode_number: 2,
            plot: 'Second episode',
          },
        ],
      },
    };

    api.getSeriesInfo.mockResolvedValue(mockResponse);

    const { result } = renderHook(() => useVODStore());

    let seriesInfo;
    await act(async () => {
      seriesInfo = await result.current.fetchSeriesInfo(1);
    });

    expect(api.getSeriesInfo).toHaveBeenCalledWith(1, null);
    expect(seriesInfo.id).toBe(1);
    expect(seriesInfo.name).toBe('Test Series');
    expect(seriesInfo.episodesList).toHaveLength(2);
    expect(seriesInfo.source_metadata).toEqual({
      values: { video_codec: 'hevc' },
    });
    expect(result.current.content['series_1']).toBeDefined();
    expect(result.current.content['series_1'].contentType).toBe('series');
    expect(result.current.episodes[101]).toBeDefined();
    expect(result.current.episodes[102]).toBeDefined();
    expect(result.current.episodes[101].name).toBe('Episode 1');
    expect(result.current.episodes[101].stream_id).toBe('provider-episode-101');
    expect(result.current.episodes[101].relation_id).toBe(9001);
    expect(result.current.episodes[102].stream_id).toBe('');
    expect(result.current.loading).toBe(false);
  });

  it('should handle fetch series info error', async () => {
    const mockError = new Error('Series not found');
    api.getSeriesInfo.mockRejectedValue(mockError);

    const consoleErrorSpy = vi
      .spyOn(console, 'error')
      .mockImplementation(() => {});

    const { result } = renderHook(() => useVODStore());

    await act(async () => {
      try {
        await result.current.fetchSeriesInfo(999);
      } catch (error) {
        expect(error).toBe(mockError);
      }
    });

    expect(result.current.error).toBe('Failed to load series details.');
    expect(result.current.loading).toBe(false);
    expect(consoleErrorSpy).toHaveBeenCalledWith(
      'Failed to fetch series info:',
      mockError
    );

    consoleErrorSpy.mockRestore();
  });

  it('should fetch categories successfully with array response', async () => {
    const mockCategories = [
      { id: 1, name: 'Action' },
      { id: 2, name: 'Comedy' },
    ];

    api.getVODCategories.mockResolvedValue(mockCategories);

    const { result } = renderHook(() => useVODStore());

    await act(async () => {
      await result.current.fetchCategories();
    });

    expect(api.getVODCategories).toHaveBeenCalled();
    expect(result.current.categories).toEqual({
      1: { id: 1, name: 'Action' },
      2: { id: 2, name: 'Comedy' },
    });
  });

  it('should fetch categories successfully with paginated response', async () => {
    const mockResponse = {
      results: [
        { id: 1, name: 'Drama' },
        { id: 2, name: 'Thriller' },
      ],
    };

    api.getVODCategories.mockResolvedValue(mockResponse);

    const { result } = renderHook(() => useVODStore());

    await act(async () => {
      await result.current.fetchCategories();
    });

    expect(result.current.categories).toEqual({
      1: { id: 1, name: 'Drama' },
      2: { id: 2, name: 'Thriller' },
    });
  });

  it('should handle fetch categories error', async () => {
    const mockError = new Error('Categories error');
    api.getVODCategories.mockRejectedValue(mockError);

    const consoleErrorSpy = vi
      .spyOn(console, 'error')
      .mockImplementation(() => {});

    const { result } = renderHook(() => useVODStore());

    await act(async () => {
      await result.current.fetchCategories();
    });

    expect(result.current.error).toBe('Failed to load categories.');
    expect(consoleErrorSpy).toHaveBeenCalledWith(
      'Failed to fetch VOD categories:',
      mockError
    );

    consoleErrorSpy.mockRestore();
  });

  it('should add movie to content', () => {
    const { result } = renderHook(() => useVODStore());
    const movie = { id: 1, name: 'New Movie' };

    act(() => {
      result.current.addMovie(movie);
    });

    expect(result.current.content['movie_1']).toEqual({
      id: 1,
      name: 'New Movie',
      contentType: 'movie',
    });
  });

  it('should update movie in content', () => {
    useVODStore.setState({
      content: {
        movie_1: { id: 1, name: 'Old Movie', contentType: 'movie' },
      },
    });

    const { result } = renderHook(() => useVODStore());
    const updatedMovie = { id: 1, name: 'Updated Movie' };

    act(() => {
      result.current.updateMovie(updatedMovie);
    });

    expect(result.current.content['movie_1']).toEqual({
      id: 1,
      name: 'Updated Movie',
      contentType: 'movie',
    });
  });

  it('should remove movie from content', () => {
    useVODStore.setState({
      content: {
        movie_1: { id: 1, name: 'Movie to Remove', contentType: 'movie' },
        movie_2: { id: 2, name: 'Movie to Keep', contentType: 'movie' },
      },
    });

    const { result } = renderHook(() => useVODStore());

    act(() => {
      result.current.removeMovie(1);
    });

    expect(result.current.content['movie_1']).toBeUndefined();
    expect(result.current.content['movie_2']).toBeDefined();
  });

  it('should add series to content', () => {
    const { result } = renderHook(() => useVODStore());
    const series = { id: 1, name: 'New Series' };

    act(() => {
      result.current.addSeries(series);
    });

    expect(result.current.content['series_1']).toEqual({
      id: 1,
      name: 'New Series',
      contentType: 'series',
    });
  });

  it('should update series in content', () => {
    useVODStore.setState({
      content: {
        series_1: { id: 1, name: 'Old Series', contentType: 'series' },
      },
    });

    const { result } = renderHook(() => useVODStore());
    const updatedSeries = { id: 1, name: 'Updated Series' };

    act(() => {
      result.current.updateSeries(updatedSeries);
    });

    expect(result.current.content['series_1']).toEqual({
      id: 1,
      name: 'Updated Series',
      contentType: 'series',
    });
  });

  it('should remove series from content', () => {
    useVODStore.setState({
      content: {
        series_1: { id: 1, name: 'Series to Remove', contentType: 'series' },
        series_2: { id: 2, name: 'Series to Keep', contentType: 'series' },
      },
    });

    const { result } = renderHook(() => useVODStore());

    act(() => {
      result.current.removeSeries(1);
    });

    expect(result.current.content['series_1']).toBeUndefined();
    expect(result.current.content['series_2']).toBeDefined();
  });

  it('should get filtered content from current page', () => {
    const mockContent = [
      { id: 1, name: 'Movie 1', contentType: 'movie' },
      { id: 2, name: 'Series 1', contentType: 'series' },
    ];

    useVODStore.setState({
      currentPageContent: mockContent,
    });

    const { result } = renderHook(() => useVODStore());
    const filtered = result.current.getFilteredContent();

    expect(filtered).toEqual(mockContent);
  });

  it('should get only movies from content', () => {
    useVODStore.setState({
      content: {
        movie_1: { id: 1, name: 'Movie 1', contentType: 'movie' },
        series_1: { id: 2, name: 'Series 1', contentType: 'series' },
        movie_2: { id: 3, name: 'Movie 2', contentType: 'movie' },
      },
    });

    const { result } = renderHook(() => useVODStore());
    const movies = result.current.getMovies();

    expect(movies).toHaveLength(2);
    expect(movies.every((item) => item.contentType === 'movie')).toBe(true);
  });

  it('should get only series from content', () => {
    useVODStore.setState({
      content: {
        movie_1: { id: 1, name: 'Movie 1', contentType: 'movie' },
        series_1: { id: 2, name: 'Series 1', contentType: 'series' },
        series_2: { id: 3, name: 'Series 2', contentType: 'series' },
      },
    });

    const { result } = renderHook(() => useVODStore());
    const series = result.current.getSeries();

    expect(series).toHaveLength(2);
    expect(series.every((item) => item.contentType === 'series')).toBe(true);
  });

  it('should clear all content', () => {
    useVODStore.setState({
      content: {
        movie_1: { id: 1, name: 'Movie 1', contentType: 'movie' },
        series_1: { id: 2, name: 'Series 1', contentType: 'series' },
      },
      totalCount: 2,
    });

    const { result } = renderHook(() => useVODStore());

    act(() => {
      result.current.clearContent();
    });

    expect(result.current.content).toEqual({});
    expect(result.current.totalCount).toBe(0);
  });

  it('should handle fetch content with search filter', async () => {
    const mockResponse = {
      results: [{ id: 1, name: 'Searched Movie', content_type: 'movie' }],
      count: 1,
    };

    api.getAllContent.mockResolvedValue(mockResponse);

    const { result } = renderHook(() => useVODStore());

    act(() => {
      result.current.setFilters({ search: 'Searched' });
    });

    await act(async () => {
      await result.current.fetchContent();
    });

    expect(api.getAllContent).toHaveBeenCalled();
    const callArgs = api.getAllContent.mock.calls[0][0];
    expect(callArgs.get('search')).toBe('Searched');
  });

  it('should handle fetch content with category filter', async () => {
    const mockResponse = {
      results: [{ id: 1, name: 'Action Movie', content_type: 'movie' }],
      count: 1,
    };

    api.getAllContent.mockResolvedValue(mockResponse);

    const { result } = renderHook(() => useVODStore());

    act(() => {
      result.current.setFilters({ category: 'action' });
    });

    await act(async () => {
      await result.current.fetchContent();
    });

    const callArgs = api.getAllContent.mock.calls[0][0];
    expect(callArgs.get('category')).toBe('action');
  });

  it('should set loading state during fetch', async () => {
    let resolvePromise;
    const promise = new Promise((resolve) => {
      resolvePromise = resolve;
    });

    api.getAllContent.mockReturnValue(promise);

    const { result } = renderHook(() => useVODStore());

    act(() => {
      result.current.fetchContent();
    });

    expect(result.current.loading).toBe(true);
    expect(result.current.error).toBe(null);

    await act(async () => {
      resolvePromise({ results: [], count: 0 });
      await promise;
    });

    expect(result.current.loading).toBe(false);
  });
});
