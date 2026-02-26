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
      loading: false,
      error: null,
      filters: {
        type: 'all',
        search: '',
        category: '',
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

    api.getMovies.mockResolvedValue(mockResponse);

    const { result } = renderHook(() => useVODStore());

    act(() => {
      result.current.setFilters({ type: 'movies' });
    });

    await act(async () => {
      await result.current.fetchContent();
    });

    expect(api.getMovies).toHaveBeenCalled();
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

    api.getSeries.mockResolvedValue(mockResponse);

    const { result } = renderHook(() => useVODStore());

    act(() => {
      result.current.setFilters({ type: 'series' });
    });

    await act(async () => {
      await result.current.fetchContent();
    });

    expect(api.getSeries).toHaveBeenCalled();
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
    };

    api.getMovieProviderInfo.mockResolvedValue(mockResponse);

    const { result } = renderHook(() => useVODStore());

    let movieDetails;
    await act(async () => {
      movieDetails = await result.current.fetchMovieDetailsFromProvider(1);
    });

    expect(api.getMovieProviderInfo).toHaveBeenCalledWith(1);
    expect(movieDetails.name).toBe('Provider Movie');
    expect(movieDetails.description).toBe('From provider');
    expect(movieDetails.backdrop_path).toEqual(['path1', 'path2']);
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
      episodes: {
        1: [
          {
            id: 101,
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

    expect(api.getSeriesInfo).toHaveBeenCalledWith(1);
    expect(seriesInfo.id).toBe(1);
    expect(seriesInfo.name).toBe('Test Series');
    expect(seriesInfo.episodesList).toHaveLength(2);
    expect(result.current.content['series_1']).toBeDefined();
    expect(result.current.content['series_1'].contentType).toBe('series');
    expect(result.current.episodes[101]).toBeDefined();
    expect(result.current.episodes[102]).toBeDefined();
    expect(result.current.episodes[101].name).toBe('Episode 1');
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
