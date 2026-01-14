import { create } from 'zustand';

const useStreamsTableStore = create((set) => ({
  streams: [],
  pageCount: 0,
  totalCount: 0,
  sorting: [{ id: 'name', desc: false }],
  pagination: {
    pageIndex: 0,
    pageSize:
      JSON.parse(localStorage.getItem('streams-page-size')) || 50,
  },
  selectedStreamIds: [],
  allQueryIds: [],

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
    set(() => ({
      sorting,
    }));
  },
}));

export default useStreamsTableStore;
