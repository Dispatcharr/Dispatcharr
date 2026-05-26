import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Store mock ─────────────────────────────────────────────────────────────────
vi.mock('../../../store/useVODStore', () => ({ default: vi.fn() }));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  CircleCheck: () => <svg data-testid="icon-circle-check" />,
  CircleX:     () => <svg data-testid="icon-circle-x" />,
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Box:      ({ children }) => <div>{children}</div>,
  Button:   ({ children, onClick, disabled, color, variant }) => (
    <button onClick={onClick} disabled={disabled} data-color={color} data-variant={variant}>
      {children}
    </button>
  ),
  Checkbox: ({ label, checked, onChange, disabled }) => (
    <label>
      <input
        type="checkbox"
        aria-label={label}
        checked={checked}
        onChange={(e) => onChange?.({ currentTarget: { checked: e.target.checked } })}
        disabled={disabled}
      />
      {label}
    </label>
  ),
  Flex:     ({ children }) => <div>{children}</div>,
  Group:    ({ children }) => <div>{children}</div>,
  SimpleGrid: ({ children }) => <div data-testid="simple-grid">{children}</div>,
  Stack:    ({ children }) => <div>{children}</div>,
  Text:     ({ children }) => <span>{children}</span>,
  TextInput: ({ label, value, onChange, placeholder }) => (
    <input
      aria-label={label ?? placeholder}
      value={value}
      onChange={onChange}
      placeholder={placeholder}
    />
  ),
  SegmentedControl: ({ value, onChange, data }) => (
    <div data-testid="segmented-control">
      {data.map((item) => (
        <button
          key={item.value ?? item}
          data-testid={`segment-${item.value ?? item}`}
          onClick={() => onChange(item.value ?? item)}
          data-active={value === (item.value ?? item) ? 'true' : 'false'}
        >
          {item.label ?? item}
        </button>
      ))}
    </div>
  ),
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import useVODStore from '../../../store/useVODStore';
import VODCategoryFilter from '../VODCategoryFilter';

// ── Helpers ────────────────────────────────────────────────────────────────────
const makeCategories = () => [
  {
    id: 1,
    name: 'Action',
    m3u_accounts: [{ m3u_account: 10, enabled: true }],
    category_type: 'movies',
  },
  { id: 2, name: 'Comedy', m3u_accounts: [{ m3u_account: 10, enabled: false }], category_type: 'movies' },
  { id: 3, name: 'Drama', m3u_accounts: [{ m3u_account: 10, enabled: true }], category_type: 'movies' },
  { id: 4, name: 'News', m3u_accounts: [{ m3u_account: 10, enabled: true }], category_type: 'series' },
];

const makePlaylist = (overrides = {}) => ({ id: 10, name: 'My Playlist', ...overrides });

const categoriesToDict = (arr) =>
  arr.reduce((acc, cat) => ({ ...acc, [cat.id]: cat }), {});

const setupMocks = ({ categories = makeCategories() } = {}) => {
  const dict = Array.isArray(categories) ? categoriesToDict(categories) : categories;
  vi.mocked(useVODStore).mockImplementation((sel) => sel({ categories: dict }));
};

const defaultProps = (overrides = {}) => {
  return {
    playlist: makePlaylist(),
    categoryStates: [
      { id: 1, name: 'Action', enabled: true },
      { id: 2, name: 'Comedy', enabled: false },
      { id: 3, name: 'Drama', enabled: true },
    ],
    setCategoryStates: vi.fn(),
    type: 'movies',
    autoEnableNewGroups: true,
    setAutoEnableNewGroups: vi.fn(),
    ...overrides,
  };
};

// ──────────────────────────────────────────────────────────────────────────────

describe('VODCategoryFilter', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupMocks();
  });

  // ── Rendering ─────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders without crashing', () => {
      render(<VODCategoryFilter {...defaultProps()} />);
      expect(screen.getByTestId('simple-grid')).toBeInTheDocument();
    });

    it('renders a button for each category matching the type and playlist', () => {
      render(<VODCategoryFilter {...defaultProps()} />);
      expect(screen.getByRole('button', { name: 'Action' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Comedy' })).toBeInTheDocument();
    });

    it('does not render categories of a different type', () => {
      render(<VODCategoryFilter {...defaultProps()} />);
      expect(screen.queryByRole('checkbox', { name: 'News' })).not.toBeInTheDocument();
    });

    it('renders the text filter input', () => {
      render(<VODCategoryFilter {...defaultProps()} />);
      expect(screen.getByPlaceholderText(/filter/i)).toBeInTheDocument();
    });

    it('renders the segmented status control', () => {
      render(<VODCategoryFilter {...defaultProps()} />);
      expect(screen.getByTestId('segmented-control')).toBeInTheDocument();
    });

    it('renders Enable All and Disable All buttons', () => {
      render(<VODCategoryFilter {...defaultProps()} />);
      expect(screen.getByText('Select Visible')).toBeInTheDocument();
      expect(screen.getByText('Deselect Visible')).toBeInTheDocument();
    });

    it('renders the Auto-enable new groups checkbox', () => {
      render(<VODCategoryFilter {...defaultProps()} />);
      expect(screen.getByLabelText(/automatically enable new/i)).toBeInTheDocument();
    });
  });

  // ── Text filter ───────────────────────────────────────────────────────────

  describe('text filter', () => {
    it('hides categories that do not match the filter', () => {
      render(<VODCategoryFilter {...defaultProps()} />);
      const input = screen.getByPlaceholderText(/filter/i);
      fireEvent.change(input, { target: { value: 'act' } });
      expect(screen.getByRole('button', { name: 'Action' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Comedy' })).not.toBeInTheDocument();
    });

    it('is case-insensitive', () => {
      render(<VODCategoryFilter {...defaultProps()} />);
      fireEvent.change(screen.getByPlaceholderText(/filter/i), { target: { value: 'COMEDY' } });
      expect(screen.getByRole('button', { name: 'Comedy' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Action' })).not.toBeInTheDocument();
    });

    it('shows all categories when filter is cleared', () => {
      render(<VODCategoryFilter {...defaultProps()} />);
      const input = screen.getByPlaceholderText(/filter/i);
      fireEvent.change(input, { target: { value: 'act' } });
      fireEvent.change(input, { target: { value: '' } });
      expect(screen.getByRole('button', { name: 'Action' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Comedy' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Drama' })).toBeInTheDocument();
    });

    it('shows no categories when filter matches nothing', () => {
      render(<VODCategoryFilter {...defaultProps()} />);
      fireEvent.change(screen.getByPlaceholderText(/filter/i), {
        target: { value: 'zzznomatch' },
      });
      expect(screen.queryByRole('button', { name: 'Action' })).not.toBeInTheDocument();
    });
  });

  // ── Status filter ─────────────────────────────────────────────────────────

  describe('status filter', () => {
    it('shows only enabled categories when "Enabled" segment is selected', () => {
      const props = defaultProps({
        categoryStates: [ { id: 1, name: 'Action', enabled: true }, { id: 2, name: 'Comedy', enabled: false }, { id: 3, name: 'Drama', enabled: true } ],
      });
      render(<VODCategoryFilter {...props} />);
      fireEvent.click(screen.getByTestId('segment-enabled'));
      expect(screen.getByRole('button', { name: 'Action' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Comedy' })).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Drama' })).toBeInTheDocument();
    });

    it('shows only disabled categories when "Disabled" segment is selected', () => {
      const props = defaultProps({
        categoryStates: [ { id: 1, name: 'Action', enabled: true }, { id: 2, name: 'Comedy', enabled: false }, { id: 3, name: 'Drama', enabled: true } ],
      });
      render(<VODCategoryFilter {...props} />);
      fireEvent.click(screen.getByTestId('segment-disabled'));
      expect(screen.queryByRole('button', { name: 'Action' })).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Comedy' })).toBeInTheDocument();
    });

    it('shows all categories when "All" segment is active', () => {
      const props = defaultProps({
        categoryStates: [ { id: 1, name: 'Action', enabled: true }, { id: 2, name: 'Comedy', enabled: false }, { id: 3, name: 'Drama', enabled: true } ],
      });
      render(<VODCategoryFilter {...props} />);
      fireEvent.click(screen.getByTestId('segment-disabled'));
      fireEvent.click(screen.getByTestId('segment-all'));
      expect(screen.getByRole('button', { name: 'Action' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Comedy' })).toBeInTheDocument();
    });
  });

  // ── Combined filters ──────────────────────────────────────────────────────

  describe('combined text + status filters', () => {
    it('applies both text and status filters simultaneously', () => {
      const props = defaultProps();
      render(<VODCategoryFilter {...props} />);
      fireEvent.change(screen.getByPlaceholderText(/filter/i), { target: { value: 'o' } });
      fireEvent.click(screen.getByTestId('segment-disabled'));
      // "Comedy" matches "o" AND is disabled; "Action" matches "o" but is enabled
      expect(screen.getByRole('button', { name: 'Comedy' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Action' })).not.toBeInTheDocument();
    });
  });

  // ── Enable All / Disable All ──────────────────────────────────────────────

  describe('Enable All button', () => {
    it('calls setCategoryStates with all visible categories set to true', () => {
      const setCategoryStates = vi.fn();
      render(
        <VODCategoryFilter
          {...defaultProps({
            setCategoryStates,
            categoryStates: [ { id: 1, name: 'Action', enabled: false }, { id: 2, name: 'Comedy', enabled: false }, { id: 3, name: 'Drama', enabled: false } ],
          })}
        />
      );
      fireEvent.click(screen.getByText('Select Visible'));
      const called = setCategoryStates.mock.calls.at(-1)[0];
      expect(called.find((s) => s.id === 1).enabled).toBe(true);
      expect(called.find((s) => s.id === 2).enabled).toBe(true);
      expect(called.find((s) => s.id === 3).enabled).toBe(true);
    });

    it('only enables filtered categories when a text filter is active', () => {
      const setCategoryStates = vi.fn();
      render(
        <VODCategoryFilter
          {...defaultProps({
            setCategoryStates,
            categoryStates: [ { id: 1, name: 'Action', enabled: false }, { id: 2, name: 'Comedy', enabled: false }, { id: 3, name: 'Drama', enabled: false } ],
          })}
        />
      );
      fireEvent.change(screen.getByPlaceholderText(/filter/i), { target: { value: 'act' } });
      fireEvent.click(screen.getByText('Select Visible'));
      const called = setCategoryStates.mock.calls.at(-1)[0];
      expect(called.find((s) => s.id === 1).enabled).toBe(true);
      // Comedy and Drama were filtered out — their state should be unchanged
      expect(called.find((s) => s.id === 2).enabled).toBe(false);
      expect(called.find((s) => s.id === 3).enabled).toBe(false);
    });
  });

  describe('Disable All button', () => {
    it('calls setCategoryStates with all visible categories set to false', () => {
      const setCategoryStates = vi.fn();
      render(<VODCategoryFilter {...defaultProps({ setCategoryStates })} />);
      fireEvent.click(screen.getByText('Deselect Visible'));
      const called = setCategoryStates.mock.calls.at(-1)[0];
      expect(called.find((s) => s.id === 1).enabled).toBe(false);
      expect(called.find((s) => s.id === 2).enabled).toBe(false);
      expect(called.find((s) => s.id === 3).enabled).toBe(false);
    });

    it('only disables filtered categories when a text filter is active', () => {
      const setCategoryStates = vi.fn();
      render(
        <VODCategoryFilter
          {...defaultProps({
            setCategoryStates,
            categoryStates: [ { id: 1, name: 'Action', enabled: true }, { id: 2, name: 'Comedy', enabled: true }, { id: 3, name: 'Drama', enabled: true } ],
          })}
        />
      );
      fireEvent.change(screen.getByPlaceholderText(/filter/i), { target: { value: 'comedy' } });
      fireEvent.click(screen.getByText('Deselect Visible'));
      const called = setCategoryStates.mock.calls.at(-1)[0];
      expect(called.find((s) => s.id === 2).enabled).toBe(false);
      expect(called.find((s) => s.id === 1).enabled).toBe(true);
      expect(called.find((s) => s.id === 3).enabled).toBe(true);
    });
  });

  // ── Auto-enable new groups ────────────────────────────────────────────────

  describe('autoEnableNewGroups checkbox', () => {
    it('calls setAutoEnableNewGroups(true) when checked', () => {
      const setAutoEnableNewGroups = vi.fn();
      render(
        <VODCategoryFilter
          {...defaultProps({ autoEnableNewGroups: false, setAutoEnableNewGroups })}
        />
      );
      fireEvent.click(screen.getByLabelText(/automatically enable new/i));
      expect(setAutoEnableNewGroups).toHaveBeenCalledWith(true);
    });

    it('calls setAutoEnableNewGroups(false) when unchecked', () => {
      const setAutoEnableNewGroups = vi.fn();
      render(
        <VODCategoryFilter
          {...defaultProps({ autoEnableNewGroups: true, setAutoEnableNewGroups })}
        />
      );
      fireEvent.click(screen.getByLabelText(/automatically enable new/i));
      expect(setAutoEnableNewGroups).toHaveBeenCalledWith(false);
    });
  });

  // ── No playlist / empty categories ───────────────────────────────────────

  describe('edge cases', () => {
    it('renders no category buttons when categories list is empty', () => {
      setupMocks({ categories: [] });
      render(<VODCategoryFilter {...defaultProps({ categoryStates: [] })} />);
      expect(screen.queryByRole('button', { name: 'Action' })).not.toBeInTheDocument();
    });

    it('renders no category buttons when categoryStates is empty', () => {
      render(<VODCategoryFilter {...defaultProps({ categoryStates: [] })} />);
      expect(screen.queryByRole('button', { name: 'Action' })).not.toBeInTheDocument();
    });

    it('renders categories only for the matching playlist id', () => {
      setupMocks({
        categories: [
          ...makeCategories(),
          { id: 99, name: 'Foreign', m3u_accounts: [{ m3u_account: 99, enabled: true }], category_type: 'movies' },
        ],
      });
      render(<VODCategoryFilter {...defaultProps()} />);
      expect(screen.queryByRole('button', { name: 'Foreign' })).not.toBeInTheDocument();
    });
  });
});