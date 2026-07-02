import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../../store/channelsTable', () => ({ default: vi.fn() }));

// ── @tanstack/react-table ─────────────────────────────────────────────────────
vi.mock('@tanstack/react-table', () => ({
  flexRender: vi.fn((content) =>
    typeof content === 'string' ? content : content?.()
  ),
}));

// ── MultiSelectHeaderWrapper ──────────────────────────────────────────────────
vi.mock('../MultiSelectHeaderWrapper', () => ({
  default: ({ children }) => (
    <div data-testid="multi-select-wrapper">{children}</div>
  ),
}));

// ── @mantine/core ─────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Box: ({ children, className, style, 'data-header-pinned': pinned }) => (
    <div
      className={className}
      style={style}
      data-header-pinned={pinned}
      data-testid={className?.includes('thead') ? 'thead' : undefined}
    >
      {children}
    </div>
  ),
  Center: ({ children, style }) => <div style={style}>{children}</div>,
  Checkbox: ({ checked, indeterminate, onChange, size }) => (
    <input
      type="checkbox"
      data-testid="select-all-checkbox"
      checked={checked}
      ref={(el) => {
        if (el) el.indeterminate = !!indeterminate;
      }}
      onChange={onChange}
      data-size={size}
    />
  ),
  Flex: ({ children, align, style }) => (
    <div style={style} data-align={align}>
      {children}
    </div>
  ),
}));

// ── Imports after mocks ───────────────────────────────────────────────────────
import useChannelsTableStore from '../../../../store/channelsTable';
import CustomTableHeader from '../CustomTableHeader';

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Build a minimal header group structure that CustomTableHeader expects.
 * Each header entry maps an id to a column definition.
 */
const makeHeader = (
  id,
  { grow = false, maxSize, canResize = false, isResizing = false, style } = {}
) => ({
  id,
  column: {
    id,
    columnDef: { id, header: id.toUpperCase(), grow, maxSize, style },
    getCanResize: () => canResize,
    getIsResizing: () => isResizing,
  },
  getContext: () => ({}),
  getResizeHandler: () => vi.fn(),
  getSize: () => 100,
});

const makeHeaderGroups = (headers) => [{ id: 'hg-0', headers }];

const defaultProps = (overrides = {}) => ({
  getHeaderGroups: () =>
    makeHeaderGroups([makeHeader('name'), makeHeader('status')]),
  allRowIds: ['1', '2', '3'],
  selectedTableIds: [],
  headerCellRenderFns: {},
  onSelectAllChange: vi.fn(),
  tableCellProps: vi.fn(() => ({})),
  headerPinned: true,
  enableDragDrop: false,
  ...overrides,
});

const setupStore = ({ isUnlocked = false } = {}) => {
  vi.mocked(useChannelsTableStore).mockImplementation((sel) =>
    sel({ isUnlocked })
  );
};

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('CustomTableHeader', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupStore();
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders a thead element', () => {
      render(<CustomTableHeader {...defaultProps()} />);
      expect(screen.getByTestId('thead')).toBeInTheDocument();
    });

    it('renders header cells for each header in the group', () => {
      render(
        <CustomTableHeader
          {...defaultProps({
            getHeaderGroups: () =>
              makeHeaderGroups([makeHeader('name'), makeHeader('status')]),
          })}
        />
      );
      // flexRender returns the header string (id.toUpperCase()) for unknown headers
      expect(screen.getByText('NAME')).toBeInTheDocument();
      expect(screen.getByText('STATUS')).toBeInTheDocument();
    });

    it('wraps each cell in MultiSelectHeaderWrapper', () => {
      render(<CustomTableHeader {...defaultProps()} />);
      expect(
        screen.getAllByTestId('multi-select-wrapper').length
      ).toBeGreaterThan(0);
    });
  });

  // ── headerPinned ──────────────────────────────────────────────────────────

  describe('headerPinned', () => {
    it('sets data-header-pinned="true" when headerPinned is true', () => {
      render(<CustomTableHeader {...defaultProps({ headerPinned: true })} />);
      expect(screen.getByTestId('thead')).toHaveAttribute(
        'data-header-pinned',
        'true'
      );
    });

    it('sets data-header-pinned="false" when headerPinned is false', () => {
      render(<CustomTableHeader {...defaultProps({ headerPinned: false })} />);
      expect(screen.getByTestId('thead')).toHaveAttribute(
        'data-header-pinned',
        'false'
      );
    });
  });

  // ── select column ─────────────────────────────────────────────────────────

  describe('select column checkbox', () => {
    const selectHeaderGroups = () => makeHeaderGroups([makeHeader('select')]);

    it('renders checkbox for the select column', () => {
      render(
        <CustomTableHeader
          {...defaultProps({
            getHeaderGroups: () => selectHeaderGroups(),
          })}
        />
      );
      expect(screen.getByTestId('select-all-checkbox')).toBeInTheDocument();
    });

    it('checkbox is unchecked when no rows are selected', () => {
      render(
        <CustomTableHeader
          {...defaultProps({
            getHeaderGroups: () => selectHeaderGroups(),
            allRowIds: ['1', '2'],
            selectedTableIds: [],
          })}
        />
      );
      expect(screen.getByTestId('select-all-checkbox')).not.toBeChecked();
    });

    it('checkbox is unchecked when allRowIds is empty', () => {
      render(
        <CustomTableHeader
          {...defaultProps({
            getHeaderGroups: () => selectHeaderGroups(),
            allRowIds: [],
            selectedTableIds: [],
          })}
        />
      );
      expect(screen.getByTestId('select-all-checkbox')).not.toBeChecked();
    });

    it('checkbox is checked when all rows are selected', () => {
      render(
        <CustomTableHeader
          {...defaultProps({
            getHeaderGroups: () => selectHeaderGroups(),
            allRowIds: ['1', '2'],
            selectedTableIds: ['1', '2'],
          })}
        />
      );
      expect(screen.getByTestId('select-all-checkbox')).toBeChecked();
    });

    it('calls onSelectAllChange when checkbox is changed', () => {
      const onSelectAllChange = vi.fn();
      render(
        <CustomTableHeader
          {...defaultProps({
            getHeaderGroups: () => selectHeaderGroups(),
            onSelectAllChange,
          })}
        />
      );
      fireEvent.click(screen.getByTestId('select-all-checkbox'));
      expect(onSelectAllChange).toHaveBeenCalled();
    });
  });

  // ── custom headerCellRenderFns ─────────────────────────────────────────────

  describe('headerCellRenderFns', () => {
    it('uses custom render function when provided for a column id', () => {
      const customRender = vi.fn(() => (
        <span data-testid="custom-header">Custom Name</span>
      ));
      render(
        <CustomTableHeader
          {...defaultProps({
            getHeaderGroups: () => makeHeaderGroups([makeHeader('name')]),
            headerCellRenderFns: { name: customRender },
          })}
        />
      );
      expect(customRender).toHaveBeenCalled();
      expect(screen.getByTestId('custom-header')).toBeInTheDocument();
    });

    it('falls back to flexRender when no custom render fn provided', () => {
      render(
        <CustomTableHeader
          {...defaultProps({
            getHeaderGroups: () => makeHeaderGroups([makeHeader('name')]),
            headerCellRenderFns: {},
          })}
        />
      );
      expect(screen.getByText('NAME')).toBeInTheDocument();
    });
  });

  // ── resize handle ─────────────────────────────────────────────────────────

  describe('resize handle', () => {
    it('renders resize handle when column canResize is true', () => {
      render(
        <CustomTableHeader
          {...defaultProps({
            getHeaderGroups: () =>
              makeHeaderGroups([makeHeader('name', { canResize: true })]),
          })}
        />
      );
      // The resizer div is rendered — check for the class
      const resizers = document.querySelectorAll('.resizer');
      expect(resizers.length).toBeGreaterThan(0);
    });

    it('does not render resize handle when column canResize is false', () => {
      render(
        <CustomTableHeader
          {...defaultProps({
            getHeaderGroups: () =>
              makeHeaderGroups([makeHeader('name', { canResize: false })]),
          })}
        />
      );
      const resizers = document.querySelectorAll('.resizer');
      expect(resizers.length).toBe(0);
    });

    it('applies isResizing class when column is being resized', () => {
      render(
        <CustomTableHeader
          {...defaultProps({
            getHeaderGroups: () =>
              makeHeaderGroups([
                makeHeader('name', { canResize: true, isResizing: true }),
              ]),
          })}
        />
      );
      expect(document.querySelector('.resizer.isResizing')).toBeTruthy();
    });
  });
});
