import { render, screen, fireEvent, within } from '@testing-library/react';
import { useState } from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Store mock ─────────────────────────────────────────────────────────────────
vi.mock('../M3UGroupContentPreview.jsx', () => ({ default: () => null }));
vi.mock('../../StackedModal.jsx', () => ({
  default: ({ opened, title, onClose, closeButtonProps, children }) =>
    opened ? (
      <div role="dialog" aria-label={title}>
        <button aria-label={closeButtonProps?.['aria-label']} onClick={onClose}>
          Close
        </button>
        {children}
      </div>
    ) : null,
}));
vi.mock('../../CategoryCleanupFields.jsx', () => ({
  default: ({ value, onChange }) => (
    <input
      aria-label="Remove from titles (regex)"
      value={value.pattern || ''}
      onChange={(event) => onChange({ ...value, pattern: event.target.value })}
    />
  ),
}));
vi.mock('../../ListPagination.jsx', () => ({ default: () => null }));
vi.mock('../../../store/useVODStore', () => ({ default: vi.fn() }));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  Filter: () => <svg />,
  Plus: () => <svg />,
  Eye: () => <svg />,
  Settings: () => <svg />,
  Eraser: () => <svg />,
  Undo2: () => <svg />,
  CircleCheck: () => <svg data-testid="icon-circle-check" />,
  CircleX: () => <svg data-testid="icon-circle-x" />,
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Indicator: ({ children }) => <>{children}</>,
  Anchor: ({ children, onClick }) => (
    <button onClick={onClick}>{children}</button>
  ),
  UnstyledButton: ({ children, onClick, disabled, ...props }) => (
    <button
      aria-label={props['aria-label']}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  ),
  Badge: ({ children, color, variant }) => (
    <span data-color={color} data-variant={variant}>
      {children}
    </span>
  ),
  Modal: ({ children, opened, title, onClose, closeButtonProps }) =>
    opened ? (
      <div role="dialog" aria-label={title}>
        <button
          aria-label={closeButtonProps?.['aria-label'] || 'Close modal'}
          onClick={onClose}
        >
          Close
        </button>
        {children}
      </div>
    ) : null,
  Table: ({ children }) => <table>{children}</table>,
  TableThead: ({ children }) => <thead>{children}</thead>,
  TableTbody: ({ children }) => <tbody>{children}</tbody>,
  TableTr: ({ children }) => <tr>{children}</tr>,
  TableTh: ({ children, w }) => <th style={{ width: w }}>{children}</th>,
  TableTd: ({ children }) => <td>{children}</td>,
  ScrollArea: Object.assign(({ children }) => <div>{children}</div>, {
    Autosize: ({ children }) => <div>{children}</div>,
  }),
  Tooltip: ({ children }) => <>{children}</>,
  Popover: Object.assign(({ children }) => <div>{children}</div>, {
    Target: ({ children }) => <>{children}</>,
    Dropdown: ({ children }) => <div>{children}</div>,
  }),
  ActionIcon: ({ children, onClick, disabled, ...props }) => (
    <button
      aria-label={props['aria-label']}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  ),
  Box: ({ children }) => <div>{children}</div>,
  Paper: ({ children }) => <div>{children}</div>,
  Button: ({
    children,
    onClick,
    disabled,
    color,
    variant,
    'aria-label': ariaLabel,
  }) => (
    <button
      onClick={onClick}
      disabled={disabled}
      data-color={color}
      data-variant={variant}
      aria-label={ariaLabel}
    >
      {children}
    </button>
  ),
  Checkbox: ({
    label,
    checked,
    onChange,
    disabled,
    'aria-label': ariaLabel,
  }) => (
    <label>
      <input
        type="checkbox"
        aria-label={ariaLabel || label}
        checked={checked}
        onChange={(e) =>
          onChange?.({ currentTarget: { checked: e.target.checked } })
        }
        disabled={disabled}
      />
      {label}
    </label>
  ),
  Flex: ({ children }) => <div>{children}</div>,
  Group: ({ children }) => <div>{children}</div>,
  SimpleGrid: ({ children }) => <div data-testid="simple-grid">{children}</div>,
  Stack: ({ children }) => <div>{children}</div>,
  Text: ({ children }) => <span>{children}</span>,
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
  Select: ({
    label,
    value,
    onChange,
    data = [],
    placeholder,
    'aria-label': ariaLabel,
  }) => (
    <label>
      {label}
      <select
        aria-label={ariaLabel ?? label}
        value={value ?? ''}
        onChange={(e) => {
          const next = e.target.value;
          onChange?.(next === '' ? null : next);
        }}
      >
        <option value="">{placeholder}</option>
        {data.map((item) => (
          <option key={item.value ?? item} value={item.value ?? item}>
            {item.label ?? item}
          </option>
        ))}
      </select>
    </label>
  ),
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import useVODStore from '../../../store/useVODStore';
import VODCategoryFilter from '../VODCategoryFilter';

const filterStatus = (status) => {
  for (const key of ['enabled', 'disabled', 'ignored']) {
    const checkbox = screen.getByRole('checkbox', {
      name: key[0].toUpperCase() + key.slice(1),
      exact: true,
    });
    const checked = status === 'all' ? key !== 'ignored' : key === status;
    if (checkbox.checked !== checked) fireEvent.click(checkbox);
  }
};
const applyStatus = (status) => {
  fireEvent.click(screen.getByRole('button', { name: /^Edit settings/ }));
  fireEvent.change(screen.getByLabelText('Status'), {
    target: { value: status },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Apply to selected' }));
};

// ── Helpers ────────────────────────────────────────────────────────────────────
const makeCategories = () => [
  {
    id: 1,
    name: 'Action',
    m3u_accounts: [
      {
        m3u_account: 10,
        enabled: true,
        custom_properties: { language: 'en', quality: '1080p' },
      },
    ],
    category_type: 'movie',
  },
  {
    id: 2,
    name: 'Comedy',
    m3u_accounts: [{ m3u_account: 10, enabled: false }],
    category_type: 'movie',
  },
  {
    id: 3,
    name: 'Drama',
    m3u_accounts: [{ m3u_account: 10, enabled: true }],
    category_type: 'movie',
  },
  {
    id: 4,
    name: 'News',
    m3u_accounts: [{ m3u_account: 10, enabled: true }],
    category_type: 'series',
  },
];

const makePlaylist = (overrides = {}) => ({
  id: 10,
  name: 'My Playlist',
  ...overrides,
});

const categoriesToDict = (arr) =>
  arr.reduce((acc, cat) => ({ ...acc, [cat.id]: cat }), {});

const setupMocks = ({ categories = makeCategories() } = {}) => {
  const dict = Array.isArray(categories)
    ? categoriesToDict(categories)
    : categories;
  vi.mocked(useVODStore).mockImplementation((sel) => sel({ categories: dict }));
};

const defaultProps = (overrides = {}) => {
  return {
    playlist: makePlaylist(),
    categoryStates: [
      {
        id: 1,
        name: 'Action',
        enabled: true,
        custom_properties: { language: 'en', quality: '1080p' },
      },
      { id: 2, name: 'Comedy', enabled: false, custom_properties: {} },
      { id: 3, name: 'Drama', enabled: true, custom_properties: {} },
    ],
    setCategoryStates: vi.fn(),
    type: 'movie',
    autoEnableNewGroups: true,
    setAutoEnableNewGroups: vi.fn(),
    ...overrides,
  };
};

// setCategoryStates may receive an array or a functional updater.
const latestCategoryStates = (setCategoryStates, previous) => {
  const next = setCategoryStates.mock.calls.at(-1)[0];
  return typeof next === 'function' ? next(previous) : next;
};

// ──────────────────────────────────────────────────────────────────────────────

describe('VODCategoryFilter', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupMocks();
  });

  // ── Rendering ─────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('reserves enough status-column width for the full badge label', () => {
      render(<VODCategoryFilter {...defaultProps()} />);
      expect(screen.getByRole('columnheader', { name: 'Status' })).toHaveStyle({
        width: '100px',
      });
      expect(
        within(screen.getByRole('table')).getByText('Disabled')
      ).toBeInTheDocument();
    });

    it('renders without crashing', () => {
      render(<VODCategoryFilter {...defaultProps()} />);
      expect(screen.getByRole('table')).toBeInTheDocument();
    });

    it('renders a text label for each category matching the type and playlist', () => {
      render(<VODCategoryFilter {...defaultProps()} />);
      expect(screen.getByText('Action')).toBeInTheDocument();
      expect(screen.getByText('Comedy')).toBeInTheDocument();
    });

    it('does not render categories of a different type', () => {
      render(<VODCategoryFilter {...defaultProps()} />);
      expect(
        screen.queryByRole('checkbox', { name: 'News' })
      ).not.toBeInTheDocument();
    });

    it('renders the text filter input', () => {
      render(<VODCategoryFilter {...defaultProps()} />);
      expect(screen.getByPlaceholderText(/filter/i)).toBeInTheDocument();
    });

    it('renders the category status filter', () => {
      render(<VODCategoryFilter {...defaultProps()} />);
      expect(
        screen.getByRole('button', { name: 'Filter category status' })
      ).toBeInTheDocument();
    });

    it('requires a selection before bulk actions', () => {
      render(<VODCategoryFilter {...defaultProps()} />);
      expect(screen.getByText('Edit settings (0)')).toBeDisabled();
      expect(screen.queryByText('Enable selected')).not.toBeInTheDocument();
      expect(screen.queryByText('Disable selected')).not.toBeInTheDocument();
    });

    it('explains that new categories require an import rule or manual selection', () => {
      render(<VODCategoryFilter {...defaultProps()} />);
      expect(
        screen.getByText('New unmatched categories are imported disabled.')
      ).toBeInTheDocument();
    });
  });

  // ── Text filter ───────────────────────────────────────────────────────────

  describe('text filter', () => {
    it('hides categories that do not match the filter', () => {
      render(<VODCategoryFilter {...defaultProps()} />);
      const input = screen.getByPlaceholderText(/filter/i);
      fireEvent.change(input, { target: { value: 'act' } });
      expect(screen.getByText('Action')).toBeInTheDocument();
      expect(screen.queryByText('Comedy')).not.toBeInTheDocument();
    });

    it('is case-insensitive', () => {
      render(<VODCategoryFilter {...defaultProps()} />);
      fireEvent.change(screen.getByPlaceholderText(/filter/i), {
        target: { value: 'COMEDY' },
      });
      expect(screen.getByText('Comedy')).toBeInTheDocument();
      expect(screen.queryByText('Action')).not.toBeInTheDocument();
    });

    it('shows all categories when filter is cleared', () => {
      render(<VODCategoryFilter {...defaultProps()} />);
      const input = screen.getByPlaceholderText(/filter/i);
      fireEvent.change(input, { target: { value: 'act' } });
      fireEvent.change(input, { target: { value: '' } });
      expect(screen.getByText('Action')).toBeInTheDocument();
      expect(screen.getByText('Comedy')).toBeInTheDocument();
      expect(screen.getByText('Drama')).toBeInTheDocument();
    });

    it('shows no categories when filter matches nothing', () => {
      render(<VODCategoryFilter {...defaultProps()} />);
      fireEvent.change(screen.getByPlaceholderText(/filter/i), {
        target: { value: 'zzznomatch' },
      });
      expect(screen.queryByText('Action')).not.toBeInTheDocument();
    });
  });

  // ── Status filter ─────────────────────────────────────────────────────────

  describe('status filter', () => {
    it('shows only enabled categories when "Enabled" segment is selected', () => {
      const props = defaultProps({
        categoryStates: [
          { id: 1, name: 'Action', enabled: true },
          { id: 2, name: 'Comedy', enabled: false },
          { id: 3, name: 'Drama', enabled: true },
        ],
      });
      render(<VODCategoryFilter {...props} />);
      filterStatus('enabled');
      expect(screen.getByText('Action')).toBeInTheDocument();
      expect(screen.queryByText('Comedy')).not.toBeInTheDocument();
      expect(screen.getByText('Drama')).toBeInTheDocument();
    });

    it('shows only disabled categories when "Disabled" segment is selected', () => {
      const props = defaultProps({
        categoryStates: [
          { id: 1, name: 'Action', enabled: true },
          { id: 2, name: 'Comedy', enabled: false },
          { id: 3, name: 'Drama', enabled: true },
        ],
      });
      render(<VODCategoryFilter {...props} />);
      filterStatus('disabled');
      expect(screen.queryByText('Action')).not.toBeInTheDocument();
      expect(screen.getByText('Comedy')).toBeInTheDocument();
    });

    it('shows all categories when "All" segment is active', () => {
      const props = defaultProps({
        categoryStates: [
          { id: 1, name: 'Action', enabled: true },
          { id: 2, name: 'Comedy', enabled: false },
          { id: 3, name: 'Drama', enabled: true },
        ],
      });
      render(<VODCategoryFilter {...props} />);
      filterStatus('disabled');
      filterStatus('all');
      expect(screen.getByText('Action')).toBeInTheDocument();
      expect(screen.getByText('Comedy')).toBeInTheDocument();
    });
  });

  // ── Combined filters ──────────────────────────────────────────────────────

  describe('combined text + status filters', () => {
    it('applies both text and status filters simultaneously', () => {
      const props = defaultProps();
      render(<VODCategoryFilter {...props} />);
      fireEvent.change(screen.getByPlaceholderText(/filter/i), {
        target: { value: 'o' },
      });
      filterStatus('disabled');
      // "Comedy" matches "o" AND is disabled; "Action" matches "o" but is enabled
      expect(screen.getByText('Comedy')).toBeInTheDocument();
      expect(screen.queryByText('Action')).not.toBeInTheDocument();
    });
  });

  // ── Enable All / Disable All ──────────────────────────────────────────────

  describe('Enable All button', () => {
    it('calls setCategoryStates with all visible categories set to true', () => {
      const setCategoryStates = vi.fn();
      const categoryStates = [
        { id: 1, name: 'Action', enabled: false },
        { id: 2, name: 'Comedy', enabled: false },
        { id: 3, name: 'Drama', enabled: false },
      ];
      render(
        <VODCategoryFilter
          {...defaultProps({ setCategoryStates, categoryStates })}
        />
      );
      fireEvent.click(
        screen.getByRole('checkbox', { name: 'Select visible categories' })
      );
      applyStatus('enabled');
      const called = latestCategoryStates(setCategoryStates, categoryStates);
      expect(called.find((s) => s.id === 1).enabled).toBe(true);
      expect(called.find((s) => s.id === 2).enabled).toBe(true);
      expect(called.find((s) => s.id === 3).enabled).toBe(true);
    });

    it('only enables filtered categories when a text filter is active', () => {
      const setCategoryStates = vi.fn();
      const categoryStates = [
        { id: 1, name: 'Action', enabled: false },
        { id: 2, name: 'Comedy', enabled: false },
        { id: 3, name: 'Drama', enabled: false },
      ];
      render(
        <VODCategoryFilter
          {...defaultProps({ setCategoryStates, categoryStates })}
        />
      );
      fireEvent.change(screen.getByPlaceholderText(/filter/i), {
        target: { value: 'act' },
      });
      fireEvent.click(
        screen.getByRole('checkbox', { name: 'Select visible categories' })
      );
      applyStatus('enabled');
      const called = latestCategoryStates(setCategoryStates, categoryStates);
      expect(called.find((s) => s.id === 1).enabled).toBe(true);
      // Comedy and Drama were filtered out — their state should be unchanged
      expect(called.find((s) => s.id === 2).enabled).toBe(false);
      expect(called.find((s) => s.id === 3).enabled).toBe(false);
    });
  });

  describe('Disable All button', () => {
    it('calls setCategoryStates with all visible categories set to false', () => {
      const setCategoryStates = vi.fn();
      const props = defaultProps({ setCategoryStates });
      render(<VODCategoryFilter {...props} />);
      fireEvent.click(
        screen.getByRole('checkbox', { name: 'Select visible categories' })
      );
      applyStatus('disabled');
      const called = latestCategoryStates(
        setCategoryStates,
        props.categoryStates
      );
      expect(called.find((s) => s.id === 1).enabled).toBe(false);
      expect(called.find((s) => s.id === 2).enabled).toBe(false);
      expect(called.find((s) => s.id === 3).enabled).toBe(false);
    });

    it('only disables filtered categories when a text filter is active', () => {
      const setCategoryStates = vi.fn();
      const categoryStates = [
        { id: 1, name: 'Action', enabled: true },
        { id: 2, name: 'Comedy', enabled: true },
        { id: 3, name: 'Drama', enabled: true },
      ];
      render(
        <VODCategoryFilter
          {...defaultProps({ setCategoryStates, categoryStates })}
        />
      );
      fireEvent.change(screen.getByPlaceholderText(/filter/i), {
        target: { value: 'comedy' },
      });
      fireEvent.click(
        screen.getByRole('checkbox', { name: 'Select visible categories' })
      );
      applyStatus('disabled');
      const called = latestCategoryStates(setCategoryStates, categoryStates);
      expect(called.find((s) => s.id === 2).enabled).toBe(false);
      expect(called.find((s) => s.id === 1).enabled).toBe(true);
      expect(called.find((s) => s.id === 3).enabled).toBe(true);
    });
  });

  // ── Auto-enable new groups ────────────────────────────────────────────────

  describe('selection and bulk settings', () => {
    it('clears a selection when switching accounts', () => {
      const props = defaultProps();
      const view = render(<VODCategoryFilter {...props} />);
      fireEvent.click(screen.getByRole('checkbox', { name: 'Select Action' }));
      expect(screen.getByText('Edit settings (1)')).toBeEnabled();
      view.rerender(
        <VODCategoryFilter {...props} playlist={makePlaylist({ id: 11 })} />
      );
      expect(screen.getByText('Edit settings (0)')).toBeDisabled();
    });
    it('selection alone never changes enabled or category metadata', () => {
      const setCategoryStates = vi.fn();
      render(<VODCategoryFilter {...defaultProps({ setCategoryStates })} />);
      setCategoryStates.mockClear();
      fireEvent.click(
        screen.getByRole('checkbox', { name: 'Select visible categories' })
      );
      expect(setCategoryStates).not.toHaveBeenCalled();
      expect(screen.getByText('Edit settings (3)')).toBeEnabled();
      fireEvent.click(
        screen.getByRole('checkbox', { name: 'Select visible categories' })
      );
      expect(screen.getByText('Edit settings (0)')).toBeDisabled();
    });

    it('bulk updates only selected categories and preserves unrelated properties', () => {
      const setCategoryStates = vi.fn();
      const categoryStates = [
        {
          id: 1,
          name: 'Action',
          enabled: true,
          custom_properties: {
            language: 'en',
            quality: '1080p',
            custom: 'keep',
          },
        },
        {
          id: 2,
          name: 'Comedy',
          enabled: false,
          custom_properties: { language: 'fr' },
        },
      ];
      render(
        <VODCategoryFilter
          {...defaultProps({ setCategoryStates, categoryStates })}
        />
      );
      fireEvent.click(screen.getByRole('checkbox', { name: 'Select Action' }));
      fireEvent.click(screen.getByText('Edit settings (1)'));
      const dialog = screen.getByRole('dialog', {
        name: 'Edit settings for 1 category',
      });
      expect(within(dialog).getByText('Metadata')).toBeInTheDocument();
      expect(
        within(dialog).queryByText(/Defaults apply only|Import defaults only/)
      ).not.toBeInTheDocument();
      fireEvent.change(within(dialog).getByLabelText('Resolution'), {
        target: { value: '2160p' },
      });
      fireEvent.click(
        within(dialog).getByRole('button', { name: 'Apply to selected' })
      );
      const next = latestCategoryStates(setCategoryStates, categoryStates);
      expect(next[0].custom_properties).toEqual({
        language: 'en',
        quality: '1080p',
        resolution: '2160p',
        custom: 'keep',
      });
      expect(next[1]).toBe(categoryStates[1]);
      expect(next[0].enabled).toBe(true);
    });

    it('canceling a bulk edit does not change the draft', () => {
      const setCategoryStates = vi.fn();
      render(<VODCategoryFilter {...defaultProps({ setCategoryStates })} />);
      setCategoryStates.mockClear();
      fireEvent.click(screen.getByRole('checkbox', { name: 'Select Action' }));
      fireEvent.click(screen.getByText('Edit settings (1)'));
      const dialog = screen.getByRole('dialog', {
        name: 'Edit settings for 1 category',
      });
      fireEvent.click(
        within(dialog).getByLabelText('Clear Resolution defaults')
      );
      fireEvent.click(
        within(dialog).getByRole('button', {
          name: 'Close bulk category settings',
        })
      );
      expect(setCategoryStates).not.toHaveBeenCalled();
    });
  });

  describe('new category defaults', () => {
    it('does not expose the legacy fallback when previously disabled', () => {
      const setAutoEnableNewGroups = vi.fn();
      render(
        <VODCategoryFilter
          {...defaultProps({
            autoEnableNewGroups: false,
            setAutoEnableNewGroups,
          })}
        />
      );
      expect(
        screen.queryByLabelText(/enable unmatched new/i)
      ).not.toBeInTheDocument();
      expect(setAutoEnableNewGroups).not.toHaveBeenCalled();
    });

    it('does not expose the legacy fallback when previously enabled', () => {
      const setAutoEnableNewGroups = vi.fn();
      render(
        <VODCategoryFilter
          {...defaultProps({
            autoEnableNewGroups: true,
            setAutoEnableNewGroups,
          })}
        />
      );
      expect(
        screen.queryByLabelText(/enable unmatched new/i)
      ).not.toBeInTheDocument();
      expect(setAutoEnableNewGroups).not.toHaveBeenCalled();
    });
  });

  // ── No playlist / empty categories ───────────────────────────────────────

  describe('edge cases', () => {
    it('renders no category buttons when categories list is empty', () => {
      setupMocks({ categories: [] });
      render(<VODCategoryFilter {...defaultProps({ categoryStates: [] })} />);
      expect(screen.queryByText('Action')).not.toBeInTheDocument();
    });

    it('renders no category buttons when categoryStates is empty', () => {
      render(<VODCategoryFilter {...defaultProps({ categoryStates: [] })} />);
      expect(screen.queryByText('Action')).not.toBeInTheDocument();
    });

    it('renders categories only for the matching playlist id', () => {
      setupMocks({
        categories: [
          ...makeCategories(),
          {
            id: 99,
            name: 'Foreign',
            m3u_accounts: [{ m3u_account: 99, enabled: true }],
            category_type: 'movie',
          },
        ],
      });
      render(<VODCategoryFilter {...defaultProps()} />);
      expect(
        screen.queryByRole('button', { name: 'Foreign' })
      ).not.toBeInTheDocument();
    });
  });

  // ── Language / quality ────────────────────────────────────────────────────

  describe('source metadata defaults', () => {
    it('keeps editors unmounted until opening and uses a disabled gear for disabled categories', () => {
      render(<VODCategoryFilter {...defaultProps()} />);
      expect(screen.queryByLabelText('Resolution')).not.toBeInTheDocument();
      const row = screen.getByText('Action').closest('tr');
      expect(
        within(row.lastElementChild)
          .getAllByRole('button')
          .map((button) => button.getAttribute('aria-label'))
      ).toEqual(['Edit defaults for Action', 'Preview category']);
      expect(
        screen.getByRole('button', { name: 'Edit defaults for Comedy' })
      ).toBeDisabled();
      fireEvent.click(
        screen.getByRole('button', { name: 'Edit defaults for Action' })
      );
      expect(screen.getByLabelText('Resolution')).toHaveValue('1080p');
      expect(
        screen.getByRole('button', {
          name: 'Remove English (eng) from DUB languages',
        })
      ).toBeInTheDocument();
    });

    it('cancels changes without mutating the draft and applies only to the selected category', () => {
      const StatefulFilter = () => {
        const [categoryStates, setCategoryStates] = useState(
          defaultProps().categoryStates
        );
        return (
          <VODCategoryFilter
            {...defaultProps({ categoryStates, setCategoryStates })}
          />
        );
      };
      render(<StatefulFilter />);
      fireEvent.click(
        screen.getByRole('button', { name: 'Edit defaults for Action' })
      );
      fireEvent.change(screen.getByLabelText('Resolution'), {
        target: { value: '2160p' },
      });
      fireEvent.click(
        screen.getByRole('button', { name: 'Close category defaults' })
      );
      expect(
        screen.getByRole('dialog', { name: 'Discard unsaved changes?' })
      ).toBeInTheDocument();
      fireEvent.click(
        screen.getByRole('button', { name: 'Discard', exact: true })
      );
      expect(screen.getByText('eng', { exact: true })).toBeInTheDocument();
      expect(screen.getByText('1080p', { exact: true })).toBeInTheDocument();
      fireEvent.click(
        screen.getByRole('button', { name: 'Edit defaults for Action' })
      );
      fireEvent.change(screen.getByLabelText('Resolution'), {
        target: { value: '2160p' },
      });
      fireEvent.click(
        screen.getByRole('button', { name: 'Apply', exact: true })
      );
      expect(screen.getByText('eng', { exact: true })).toBeInTheDocument();
      expect(screen.getByText('2160p', { exact: true })).toBeInTheDocument();
    });

    it('hydrates custom_properties from the store on mount', () => {
      const setCategoryStates = vi.fn();
      render(
        <VODCategoryFilter
          {...defaultProps({ setCategoryStates, categoryStates: [] })}
        />
      );
      expect(setCategoryStates).toHaveBeenCalled();
      const hydrated = latestCategoryStates(setCategoryStates, []);
      const action = hydrated.find((s) => s.id === 1);
      expect(action.custom_properties).toEqual({
        language: 'en',
        quality: '1080p',
      });
      expect(action.original_custom_properties).toEqual({
        language: 'en',
        quality: '1080p',
      });
      expect(action.original_enabled).toBe(true);
    });
    it('keeps category cleanup in the draft until Apply and preserves other properties', () => {
      const setCategoryStates = vi.fn();
      render(<VODCategoryFilter {...defaultProps({ setCategoryStates })} />);
      fireEvent.click(
        screen.getByRole('button', { name: 'Edit defaults for Action' })
      );
      fireEvent.change(screen.getByLabelText('Remove from titles (regex)'), {
        target: { value: '^EN \\|' },
      });
      setCategoryStates.mockClear();
      expect(setCategoryStates).not.toHaveBeenCalled();
      fireEvent.click(
        screen.getByRole('button', { name: 'Apply', exact: true })
      );
      const result = latestCategoryStates(
        setCategoryStates,
        defaultProps().categoryStates
      );
      expect(result.find((row) => row.id === 1).custom_properties).toEqual(
        expect.objectContaining({ title_cleanup: { pattern: '^EN \\|' } })
      );
      expect(result.find((row) => row.id === 2)).toEqual(
        defaultProps().categoryStates.find((row) => row.id === 2)
      );
    });
  });
});
