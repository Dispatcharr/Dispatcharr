import { create } from 'zustand';
import api from '../api';
import { formatApiError } from '../utils';

let contentRequest = 0;
let optionsRequest = 0;
let jobRequest = 0;

const useLibraryStore = create((set, get) => ({
  filters: {
    type: 'all',
    view: 'titles',
    search: '',
    account: '',
    category: '',
    locked: '',
    blocked: '',
    metadata_status: '',
    audio_language: '',
    subtitle_language: '',
    resolution: '',
    video_feature: '',
    container_extension: '',
    genre: '',
    anime_mode: '',
    adult_mode: '',
    added_since: '',
    added_until: '',
    released_since: '',
    released_until: '',
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
  trackJob: (job) => {
    jobRequest += 1;
    set({ job, trackedJobId: job.task_id });
  },
  setFilters: (patch) =>
    set((state) => ({
      filters: { ...state.filters, ...patch },
      page: 1,
      ...(patch.view && patch.view !== state.filters.view
        ? { rows: [], count: 0 }
        : {}),
    })),
  setPage: (page) => set({ page }),
  setPageSize: (pageSize) => set({ pageSize, page: 1 }),
  fetchContent: async () => {
    const requestId = ++contentRequest;
    const state = get();
    const params = new URLSearchParams({
      page: state.page,
      page_size: state.pageSize,
    });
    for (const [name, value] of Object.entries(state.filters)) {
      if (value !== '' && value != null) params.set(name, String(value));
    }
    set({ loading: true, error: null });
    try {
      const response = await api.getVODLibrary(params);
      if (requestId !== contentRequest) return;
      set({ rows: response.results, count: response.count, loading: false });
    } catch (error) {
      if (requestId !== contentRequest) return;
      if (
        state.page > 1 &&
        error.status === 404 &&
        String(error.body?.detail || '').includes('Invalid page')
      ) {
        set({ page: 1 });
        await get().fetchContent();
        return;
      }
      set({ error: formatApiError(error), loading: false });
    }
  },
  fetchOptions: async () => {
    const requestId = ++optionsRequest;
    const params = new URLSearchParams();
    for (const field of ['type', 'account', 'category']) {
      const value = get().filters[field];
      if (value !== '' && value != null) params.set(field, String(value));
    }
    try {
      const options = await api.getVODLibraryOptions(params);
      if (requestId === optionsRequest) set({ options, optionsError: null });
    } catch (error) {
      if (requestId === optionsRequest)
        set({ optionsError: formatApiError(error) });
    }
  },
  fetchJob: async () => {
    const requestId = ++jobRequest;
    try {
      const job = await api.getVODLibraryState();
      if (requestId !== jobRequest) return null;
      set({ job });
      return job;
    } catch {
      return null;
    }
  },
}));

export default useLibraryStore;
