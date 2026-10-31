import { beforeEach, describe, expect, it, vi } from 'vitest';
import api from '../../api';
import useLibraryStore from '../useLibraryStore';

vi.mock('../../api', () => ({
  default: {
    getVODLibrary: vi.fn(),
    getVODLibraryOptions: vi.fn(),
    getVODLibraryState: vi.fn(),
  },
}));

describe('Library state', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useLibraryStore.setState({
      filters: {
        type: 'all',
        view: 'titles',
        search: '',
        account: '',
        category: '',
        locked: '',
        metadata_status: '',
      },
      page: 1,
      pageSize: 24,
      rows: [],
      count: 0,
      loading: false,
      error: null,
      options: { accounts: [], categories: [] },
      optionsError: null,
      job: { status: 'idle', progress: {} },
      trackedJobId: '',
    });
  });
  it('resets the page when filters or page size change', () => {
    useLibraryStore.getState().setPage(5);
    useLibraryStore.getState().setFilters({ view: 'sources', account: 4 });
    expect(useLibraryStore.getState().page).toBe(1);
    useLibraryStore.getState().setPage(5);
    useLibraryStore.getState().setPageSize(48);
    expect(useLibraryStore.getState().page).toBe(1);
  });
  it('sends paginated source filters without empty values', async () => {
    api.getVODLibrary.mockResolvedValue({
      results: [{ key: 'movie:1' }],
      count: 10,
    });
    useLibraryStore.getState().setFilters({ view: 'sources', account: 4 });
    await useLibraryStore.getState().fetchContent();
    const params = api.getVODLibrary.mock.calls[0][0];
    expect(params.get('view')).toBe('sources');
    expect(params.get('account')).toBe('4');
    expect(params.has('search')).toBe(false);
    expect(useLibraryStore.getState().count).toBe(10);
  });
  it('keeps both inclusive date ranges and global availability in the paginated request', async () => {
    api.getVODLibrary.mockResolvedValue({ results: [], count: 0 });
    const filters = {
      blocked: 'true',
      added_since: '2026-10-01',
      added_until: '2026-10-31',
      released_since: '2020-01-01',
      released_until: '2020-12-31',
    };
    useLibraryStore.getState().setFilters(filters);
    await useLibraryStore.getState().fetchContent();
    const params = api.getVODLibrary.mock.calls[0][0];
    for (const [key, value] of Object.entries(filters))
      expect(params.get(key)).toBe(value);
  });
  it('ignores stale responses after a filter change', async () => {
    let first;
    api.getVODLibrary
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            first = resolve;
          })
      )
      .mockResolvedValueOnce({ results: [{ key: 'series:2' }], count: 1 });
    const pending = useLibraryStore.getState().fetchContent();
    useLibraryStore.getState().setFilters({ type: 'series' });
    await useLibraryStore.getState().fetchContent();
    first({ results: [{ key: 'movie:1' }], count: 9 });
    await pending;
    expect(useLibraryStore.getState().rows).toEqual([{ key: 'series:2' }]);
  });
  it('preserves visible data when loading fails', async () => {
    useLibraryStore.setState({ rows: [{ key: 'movie:1' }] });
    api.getVODLibrary.mockRejectedValue(new Error('Unavailable'));
    await useLibraryStore.getState().fetchContent();
    expect(useLibraryStore.getState().rows).toHaveLength(1);
    expect(useLibraryStore.getState().error).toBeTruthy();
    expect(useLibraryStore.getState().loading).toBe(false);
  });
  it('returns to the first page when a merge removes the current final page', async () => {
    useLibraryStore.setState({ page: 10 });
    api.getVODLibrary
      .mockRejectedValueOnce({ status: 404, body: { detail: 'Invalid page.' } })
      .mockResolvedValueOnce({ results: [{ key: 'movie:1' }], count: 1 });
    await useLibraryStore.getState().fetchContent();
    expect(useLibraryStore.getState().page).toBe(1);
    expect(useLibraryStore.getState().error).toBeNull();
    expect(api.getVODLibrary.mock.calls[1][0].get('page')).toBe('1');
  });
  it('loads options and persistent job state', async () => {
    api.getVODLibraryOptions.mockResolvedValue({
      accounts: [{ id: 1 }],
      categories: [],
    });
    api.getVODLibraryState.mockResolvedValue({
      status: 'running',
      progress: { processed: 2, total: 5 },
    });
    await useLibraryStore.getState().fetchOptions();
    await useLibraryStore.getState().fetchJob();
    expect(useLibraryStore.getState().options.accounts).toHaveLength(1);
    expect(useLibraryStore.getState().job.progress.processed).toBe(2);
  });
  it('does not let an older job response replace a newly queued job', async () => {
    let resolve;
    api.getVODLibraryState.mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        })
    );
    const pending = useLibraryStore.getState().fetchJob();
    const job = { task_id: 'new', status: 'queued', progress: {} };
    useLibraryStore.getState().trackJob(job);
    resolve({ task_id: 'old', status: 'completed' });
    expect(await pending).toBeNull();
    expect(useLibraryStore.getState().job).toEqual(job);
    expect(useLibraryStore.getState().trackedJobId).toBe('new');
  });
  it('ignores out-of-order polling responses and retains the job on a transient failure', async () => {
    let resolve;
    api.getVODLibraryState
      .mockImplementationOnce(
        () =>
          new Promise((done) => {
            resolve = done;
          })
      )
      .mockResolvedValueOnce({ task_id: 'new', status: 'completed' });
    const pending = useLibraryStore.getState().fetchJob();
    await useLibraryStore.getState().fetchJob();
    resolve({ task_id: 'old', status: 'running' });
    await pending;
    api.getVODLibraryState.mockRejectedValueOnce(new Error('Unavailable'));
    expect(await useLibraryStore.getState().fetchJob()).toBeNull();
    expect(useLibraryStore.getState().job.task_id).toBe('new');
  });
  it('reports option failure without discarding previous options', async () => {
    useLibraryStore.setState({
      options: { accounts: [{ id: 1 }], categories: [] },
    });
    api.getVODLibraryOptions.mockRejectedValue(new Error('Unavailable'));
    await useLibraryStore.getState().fetchOptions();
    expect(useLibraryStore.getState().options.accounts).toHaveLength(1);
    expect(useLibraryStore.getState().optionsError).toBeTruthy();
  });
  it('scopes available metadata to content type, provider and category only', async () => {
    api.getVODLibraryOptions.mockResolvedValue({
      accounts: [],
      categories: [],
    });
    useLibraryStore.getState().setFilters({
      type: 'movie',
      account: 3,
      category: 4,
      search: 'Film',
      audio_language: 'eng',
    });
    await useLibraryStore.getState().fetchOptions();
    expect(
      Object.fromEntries(api.getVODLibraryOptions.mock.calls[0][0])
    ).toEqual({
      type: 'movie',
      account: '3',
      category: '4',
    });
  });
  it('ignores stale options and stale failures after the scope changes', async () => {
    let resolveFirst;
    let rejectSecond;
    api.getVODLibraryOptions
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveFirst = resolve;
          })
      )
      .mockImplementationOnce(
        () =>
          new Promise((_resolve, reject) => {
            rejectSecond = reject;
          })
      )
      .mockResolvedValueOnce({ accounts: [], audio_languages: ['ger'] });
    const first = useLibraryStore.getState().fetchOptions();
    useLibraryStore.getState().setFilters({ account: 2 });
    const second = useLibraryStore.getState().fetchOptions();
    useLibraryStore.getState().setFilters({ account: 3 });
    await useLibraryStore.getState().fetchOptions();
    resolveFirst({ accounts: [], audio_languages: ['eng'] });
    rejectSecond(new Error('Outdated request'));
    await Promise.all([first, second]);
    expect(useLibraryStore.getState().options.audio_languages).toEqual(['ger']);
    expect(useLibraryStore.getState().optionsError).toBeNull();
  });
});
