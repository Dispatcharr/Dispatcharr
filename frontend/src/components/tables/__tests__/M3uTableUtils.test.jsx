import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  makeHeaderCellRenderer,
  makeSortingChangeHandler,
} from '../M3uTableUtils';

vi.mock('@mantine/core', () => ({
  Center: ({ children }) => <div data-testid="center">{children}</div>,
  Group: ({ children }) => <div data-testid="group">{children}</div>,
  Text: ({ children, size, name }) => (
    <span data-testid="text" data-size={size} data-name={name}>
      {children}
    </span>
  ),
}));

vi.mock('lucide-react', () => ({
  ArrowUpDown: (props) => (
    <svg data-testid="icon-arrow-up-down" onClick={props.onClick} />
  ),
  ArrowUpNarrowWide: (props) => (
    <svg data-testid="icon-arrow-up-narrow-wide" onClick={props.onClick} />
  ),
  ArrowDownWideNarrow: (props) => (
    <svg data-testid="icon-arrow-down-wide-narrow" onClick={props.onClick} />
  ),
}));

// ── Helpers ────────────────────────────────────────────────────────────────────

/** Build a minimal header object that matches what TanStack Table provides */
const makeHeader = ({ id = 'name', label = 'Name', sortable = true } = {}) => ({
  id,
  column: {
    columnDef: {
      header: label,
      sortable,
    },
  },
});

// ── makeHeaderCellRenderer ───────────────────────────────────────────────────

describe('makeHeaderCellRenderer', () => {
  describe('with no active sort', () => {
    const sorting = [];
    let onSortingChange;
    let renderHeader;

    beforeEach(() => {
      onSortingChange = vi.fn();
      renderHeader = makeHeaderCellRenderer(sorting, onSortingChange);
    });

    it('renders the column label text', () => {
      render(renderHeader(makeHeader({ label: 'Channel' })));
      expect(screen.getByTestId('text')).toHaveTextContent('Channel');
    });

    it('renders the neutral ArrowUpDown icon when no sort is active', () => {
      render(renderHeader(makeHeader()));
      expect(screen.getByTestId('icon-arrow-up-down')).toBeInTheDocument();
    });

    it('does not render a sort icon when column is not sortable', () => {
      render(renderHeader(makeHeader({ sortable: false })));
      expect(
        screen.queryByTestId('icon-arrow-up-down')
      ).not.toBeInTheDocument();
      expect(
        screen.queryByTestId('icon-arrow-up-narrow-wide')
      ).not.toBeInTheDocument();
      expect(
        screen.queryByTestId('icon-arrow-down-wide-narrow')
      ).not.toBeInTheDocument();
    });

    it('calls onSortingChange with the header id when icon is clicked', () => {
      render(renderHeader(makeHeader({ id: 'title' })));
      fireEvent.click(screen.getByTestId('icon-arrow-up-down'));
      expect(onSortingChange).toHaveBeenCalledTimes(1);
      expect(onSortingChange).toHaveBeenCalledWith('title');
    });

    it('sets the data-name attribute on the Text element to the header id', () => {
      render(renderHeader(makeHeader({ id: 'status' })));
      expect(screen.getByTestId('text')).toHaveAttribute('data-name', 'status');
    });
  });

  describe('when sorting asc on the current column (desc: false)', () => {
    it('renders ArrowUpNarrowWide icon', () => {
      const sorting = [{ id: 'name', desc: false }];
      const renderHeader = makeHeaderCellRenderer(sorting, vi.fn());
      render(renderHeader(makeHeader({ id: 'name' })));
      expect(
        screen.getByTestId('icon-arrow-up-narrow-wide')
      ).toBeInTheDocument();
    });

    it('does not render ArrowDownWideNarrow or ArrowUpDown', () => {
      const sorting = [{ id: 'name', desc: false }];
      const renderHeader = makeHeaderCellRenderer(sorting, vi.fn());
      render(renderHeader(makeHeader({ id: 'name' })));
      expect(
        screen.queryByTestId('icon-arrow-down-wide-narrow')
      ).not.toBeInTheDocument();
      expect(
        screen.queryByTestId('icon-arrow-up-down')
      ).not.toBeInTheDocument();
    });
  });

  describe('when sorting desc on the current column (desc: true)', () => {
    it('renders ArrowDownWideNarrow icon', () => {
      const sorting = [{ id: 'name', desc: true }];
      const renderHeader = makeHeaderCellRenderer(sorting, vi.fn());
      render(renderHeader(makeHeader({ id: 'name' })));
      expect(
        screen.getByTestId('icon-arrow-down-wide-narrow')
      ).toBeInTheDocument();
    });

    it('does not render ArrowUpNarrowWide or ArrowUpDown', () => {
      const sorting = [{ id: 'name', desc: true }];
      const renderHeader = makeHeaderCellRenderer(sorting, vi.fn());
      render(renderHeader(makeHeader({ id: 'name' })));
      expect(
        screen.queryByTestId('icon-arrow-up-narrow-wide')
      ).not.toBeInTheDocument();
      expect(
        screen.queryByTestId('icon-arrow-up-down')
      ).not.toBeInTheDocument();
    });
  });

  describe('when a different column is sorted', () => {
    it('renders the neutral ArrowUpDown icon for the unsorted column', () => {
      const sorting = [{ id: 'status', desc: false }];
      const renderHeader = makeHeaderCellRenderer(sorting, vi.fn());
      render(renderHeader(makeHeader({ id: 'name' })));
      expect(screen.getByTestId('icon-arrow-up-down')).toBeInTheDocument();
    });
  });
});

// ── makeSortingChangeHandler ─────────────────────────────────────────────────

describe('makeSortingChangeHandler', () => {
  let setSorting;
  let onDataSort;

  beforeEach(() => {
    setSorting = vi.fn();
    onDataSort = vi.fn();
  });

  describe('first click on a new column', () => {
    it('sets ascending sort (desc: false)', () => {
      const handler = makeSortingChangeHandler([], setSorting, onDataSort);
      handler('name');
      expect(setSorting).toHaveBeenCalledWith([{ id: 'name', desc: false }]);
    });

    it('calls onDataSort with the column and desc: false', () => {
      const handler = makeSortingChangeHandler([], setSorting, onDataSort);
      handler('name');
      expect(onDataSort).toHaveBeenCalledWith('name', false);
    });
  });

  describe('second click on the same column (currently asc)', () => {
    it('sets descending sort (desc: true)', () => {
      const sorting = [{ id: 'name', desc: false }];
      const handler = makeSortingChangeHandler(sorting, setSorting, onDataSort);
      handler('name');
      expect(setSorting).toHaveBeenCalledWith([{ id: 'name', desc: true }]);
    });

    it('calls onDataSort with the column and desc: true', () => {
      const sorting = [{ id: 'name', desc: false }];
      const handler = makeSortingChangeHandler(sorting, setSorting, onDataSort);
      handler('name');
      expect(onDataSort).toHaveBeenCalledWith('name', true);
    });
  });

  describe('third click on the same column (currently desc) → clears sort', () => {
    it('sets sorting to an empty array', () => {
      const sorting = [{ id: 'name', desc: true }];
      const handler = makeSortingChangeHandler(sorting, setSorting, onDataSort);
      handler('name');
      expect(setSorting).toHaveBeenCalledWith([]);
    });

    it('does NOT call onDataSort when sorting is cleared', () => {
      const sorting = [{ id: 'name', desc: true }];
      const handler = makeSortingChangeHandler(sorting, setSorting, onDataSort);
      handler('name');
      expect(onDataSort).not.toHaveBeenCalled();
    });
  });

  describe('switching to a different column while another is sorted', () => {
    it('resets to ascending sort on the new column', () => {
      const sorting = [{ id: 'status', desc: true }];
      const handler = makeSortingChangeHandler(sorting, setSorting, onDataSort);
      handler('name');
      expect(setSorting).toHaveBeenCalledWith([{ id: 'name', desc: false }]);
    });

    it('calls onDataSort with the new column and desc: false', () => {
      const sorting = [{ id: 'status', desc: true }];
      const handler = makeSortingChangeHandler(sorting, setSorting, onDataSort);
      handler('name');
      expect(onDataSort).toHaveBeenCalledWith('name', false);
    });
  });

  describe('always calls setSorting', () => {
    it('calls setSorting exactly once per handler invocation', () => {
      const handler = makeSortingChangeHandler([], setSorting, onDataSort);
      handler('title');
      expect(setSorting).toHaveBeenCalledTimes(1);
    });
  });
});
