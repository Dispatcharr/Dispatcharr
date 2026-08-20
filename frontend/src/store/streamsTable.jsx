import { create } from 'zustand';
import { readStoredJSON, writeStoredJSON } from '../hooks/useBrowserStorage';

const DEFAULT_STREAMS_SORTING = [{ id: 'name', desc: false }];
const STREAMS_SORTING_KEY = 'streams-table-sorting';

const useStreamsTableStore = create((set) => ({
  streams: [],
  pageCount: 0,
  totalCount: 0,
  sorting: readStoredJSON(
    STREAMS_SORTING_KEY,
    DEFAULT_STREAMS_SORTING,
    'session'
  ),
  pagination: {
    pageIndex: 0,
    pageSize: JSON.parse(localStorage.getItem('streams-page-size')) || 50,
  },
  selectedStreamIds: [],
  allQueryIds: [],
  lastQueryParams: null,

  queryStreams: ({ results, count }, params) => {
    set(() => ({
      streams: results,
      totalCount: count,
      pageCount: Math.ceil(count / params.get('page_size')),
    }));
  },

  setAllQueryIds: (allQueryIds) => {
    set(() => ({
      allQueryIds,
    }));
  },

  setSelectedStreamIds: (selectedStreamIds) => {
    set(() => ({
      selectedStreamIds,
    }));
  },

  setPagination: (pagination) => {
    set(() => ({
      pagination,
    }));
  },

  setSorting: (sorting) => {
    writeStoredJSON(STREAMS_SORTING_KEY, sorting, 'session');
    set(() => ({
      sorting,
    }));
  },

  setLastQueryParams: (lastQueryParams) => {
    set(() => ({
      lastQueryParams,
    }));
  },
}));

export default useStreamsTableStore;
