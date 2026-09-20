import React, { useState } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../store/useVODStore', () => ({ default: vi.fn() }));
vi.mock('../../../api', () => ({
  default: {
    bulkUpdateVODCategoryMetadata: vi.fn().mockResolvedValue({}),
    updateVODCategoryTitleCleanup: vi.fn(),
    previewVODCategoryTitleCleanup: vi.fn(),
  },
}));
vi.mock('../../../utils/notificationUtils', () => ({
  showNotification: vi.fn(),
}));
vi.mock('../../LanguagePicker.jsx', () => ({
  default: ({ label, value = [], onChange, disabled }) => (
    <label>
      {label}
      <input
        aria-label={label}
        value={value.join(',')}
        disabled={disabled}
        onChange={(event) =>
          onChange(event.target.value.split(',').filter(Boolean))
        }
      />
    </label>
  ),
}));
vi.mock('../M3UDeveloperCatalog.jsx', () => ({
  default: () => <div data-testid="category-preview">Preview</div>,
}));
vi.mock('../../VideoFeaturePicker.jsx', () => ({
  default: ({ label }) => <div>{label}</div>,
}));

vi.mock('@mantine/core', () => ({
  ActionIcon: ({ children, onClick, disabled, ...props }) => (
    <button onClick={onClick} disabled={disabled} {...props}>
      {children}
    </button>
  ),
  Button: ({ children, onClick, disabled, loading, ...props }) => (
    <button onClick={onClick} disabled={disabled || loading} {...props}>
      {children}
    </button>
  ),
  Checkbox: ({ label, checked, onChange, disabled, ...props }) => (
    <label>
      <input
        type="checkbox"
        aria-label={props['aria-label'] || label}
        checked={checked ?? false}
        disabled={disabled}
        onChange={(event) =>
          onChange?.({ currentTarget: { checked: event.target.checked } })
        }
      />
      {label}
    </label>
  ),
  Flex: ({ children }) => <div>{children}</div>,
  Group: ({ children }) => <div>{children}</div>,
  Switch: ({ label, checked, onChange }) => (
    <label>
      <input
        type="checkbox"
        aria-label={label}
        checked={checked ?? false}
        onChange={(event) =>
          onChange?.({ currentTarget: { checked: event.target.checked } })
        }
      />
      {label}
    </label>
  ),
  Tooltip: ({ children }) => <>{children}</>,
  Modal: ({ opened, children, title }) =>
    opened ? (
      <div role="dialog" aria-label={title}>
        {children}
      </div>
    ) : null,
  Pagination: () => <div data-testid="pagination" />,
  ScrollArea: ({ children }) => <div>{children}</div>,
  MultiSelect: ({ label, value = [], onChange, data = [], disabled }) => (
    <label>
      {label}
      <select
        aria-label={label}
        multiple
        value={value}
        disabled={disabled}
        onChange={(event) =>
          onChange?.(
            Array.from(event.target.selectedOptions, (option) => option.value)
          )
        }
      >
        {data.map((item) => (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        ))}
      </select>
    </label>
  ),
  SegmentedControl: ({ value, onChange, data }) => (
    <div>
      {data.map((item) => (
        <button
          key={item.value}
          data-testid={`segment-${item.value}`}
          aria-pressed={value === item.value}
          onClick={() => onChange(item.value)}
        >
          {item.label}
        </button>
      ))}
    </div>
  ),
  Select: ({ label, value, onChange, data = [], disabled }) => (
    <label>
      {label}
      <select
        aria-label={label}
        value={value || ''}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="" />
        {data.map((item) => {
          const value = typeof item === 'string' ? item : item.value;
          const optionLabel = typeof item === 'string' ? item : item.label;
          return (
            <option key={value} value={value}>
              {optionLabel}
            </option>
          );
        })}
      </select>
    </label>
  ),
  Stack: ({ children }) => <div>{children}</div>,
  Table: ({ children }) => <table>{children}</table>,
  TableTbody: ({ children }) => <tbody>{children}</tbody>,
  TableTd: ({ children }) => <td>{children}</td>,
  TableTh: ({ children }) => <th>{children}</th>,
  TableThead: ({ children }) => <thead>{children}</thead>,
  TableTr: ({ children }) => <tr>{children}</tr>,
  Text: ({ children }) => <span>{children}</span>,
  TextInput: ({ label, value, onChange, placeholder }) => (
    <input
      aria-label={label || placeholder}
      value={value}
      onChange={onChange}
      placeholder={placeholder}
    />
  ),
}));

import API from '../../../api';
import useVODStore from '../../../store/useVODStore';
import VODCategoryFilter from '../VODCategoryFilter';

const categories = {
  1: {
    id: 1,
    name: 'Action',
    category_type: 'movie',
    m3u_accounts: [
      {
        id: 101,
        m3u_account: 10,
        enabled: true,
        metadata_defaults: {
          audio_languages: ['ger'],
          video_features: ['dv'],
        },
      },
    ],
  },
  2: {
    id: 2,
    name: 'Comedy',
    category_type: 'movie',
    m3u_accounts: [
      { id: 102, m3u_account: 10, enabled: false, metadata_defaults: {} },
    ],
  },
  3: {
    id: 3,
    name: 'Drama',
    category_type: 'movie',
    m3u_accounts: [
      { id: 103, m3u_account: 10, enabled: true, metadata_defaults: {} },
    ],
  },
  4: {
    id: 4,
    name: 'News',
    category_type: 'series',
    m3u_accounts: [
      { id: 104, m3u_account: 10, enabled: true, metadata_defaults: {} },
    ],
  },
};

const Wrapper = ({ initialAutoEnable = true }) => {
  const [categoryStates, setCategoryStates] = useState([]);
  const [autoEnable, setAutoEnable] = useState(initialAutoEnable);
  const [useRules, setUseRules] = useState(true);

  return (
    <VODCategoryFilter
      playlist={{ id: 10, name: 'Provider' }}
      categoryStates={categoryStates}
      setCategoryStates={setCategoryStates}
      type="movie"
      autoEnableNewGroups={autoEnable}
      setAutoEnableNewGroups={setAutoEnable}
      useGroupRules={useRules}
      setUseGroupRules={setUseRules}
    />
  );
};

describe('VODCategoryFilter', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    API.updateVODCategoryTitleCleanup.mockResolvedValue({
      title_cleanup: {
        pattern: '-\\d+-\\s*|\\b4K\\b',
        case_sensitive: true,
      },
    });
    API.previewVODCategoryTitleCleanup.mockResolvedValue({
      results: [
        {
          relation_id: 501,
          content_type: 'movie',
          before: '(DE-) -1- Prisons 4K - 2024',
          after: 'Prisons',
          year: 2024,
          matched: true,
          changed: true,
        },
        {
          relation_id: 502,
          content_type: 'movie',
          before: 'Ordinary Movie',
          after: 'Ordinary Movie',
          year: null,
          matched: false,
          changed: false,
        },
      ],
      page_match_count: 1,
      page: 1,
      page_size: 25,
      total_in_category: 2,
      error: null,
    });
    vi.mocked(useVODStore).mockImplementation((selector) =>
      selector({ categories })
    );
  });

  it('renders categories as a searchable table with metadata columns', () => {
    render(<Wrapper />);

    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByText('Action')).toBeInTheDocument();
    expect(screen.getByText('Comedy')).toBeInTheDocument();
    expect(screen.queryByText('News')).not.toBeInTheDocument();
    expect(screen.getByText('DUB')).toBeInTheDocument();
    expect(screen.getByText('ger')).toBeInTheDocument();
    expect(screen.getByText('DV')).toBeInTheDocument();
  });

  it('filters categories by text and enabled state', () => {
    render(<Wrapper />);

    fireEvent.change(screen.getByPlaceholderText('Filter categories...'), {
      target: { value: 'com' },
    });
    expect(screen.getByText('Comedy')).toBeInTheDocument();
    expect(screen.queryByText('Action')).not.toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText('Filter categories...'), {
      target: { value: '' },
    });
    fireEvent.click(screen.getByTestId('segment-disabled'));
    expect(screen.getByText('Comedy')).toBeInTheDocument();
    expect(screen.queryByText('Action')).not.toBeInTheDocument();
  });

  it('updates a single category through its enabled checkbox', () => {
    render(<Wrapper />);

    expect(screen.getByLabelText('Enable Comedy')).toHaveAttribute(
      'aria-pressed',
      'false'
    );
    fireEvent.click(screen.getByLabelText('Enable Comedy'));
    expect(screen.getByLabelText('Enable Comedy')).toHaveAttribute(
      'aria-pressed',
      'true'
    );
  });

  it('selects visible rows and applies bulk enable/disable changes', () => {
    render(<Wrapper />);

    fireEvent.click(screen.getByLabelText('Select visible categories'));
    fireEvent.click(screen.getByText('Disable selected'));
    expect(screen.getByLabelText('Enable Action')).toHaveAttribute(
      'aria-pressed',
      'false'
    );
    expect(screen.getByLabelText('Enable Comedy')).toHaveAttribute(
      'aria-pressed',
      'false'
    );
    expect(screen.getByLabelText('Enable Drama')).toHaveAttribute(
      'aria-pressed',
      'false'
    );

    fireEvent.click(screen.getByText('Enable selected'));
    expect(screen.getByLabelText('Enable Action')).toHaveAttribute(
      'aria-pressed',
      'true'
    );
    expect(screen.getByLabelText('Enable Comedy')).toHaveAttribute(
      'aria-pressed',
      'true'
    );
    expect(screen.getByLabelText('Enable Drama')).toHaveAttribute(
      'aria-pressed',
      'true'
    );
  });

  it('bulk edits category metadata with one API request', async () => {
    render(<Wrapper />);

    fireEvent.click(screen.getByLabelText('Select Action'));
    fireEvent.click(screen.getByLabelText('Select Comedy'));
    fireEvent.click(screen.getByText('Edit metadata (2)'));
    const setButtons = screen.getAllByTestId('segment-set');
    setButtons.forEach((button) => fireEvent.click(button));
    fireEvent.change(screen.getByLabelText('DUB'), {
      target: { value: 'ger,eng' },
    });
    fireEvent.change(screen.getByLabelText('SUB'), {
      target: { value: 'ger' },
    });
    fireEvent.change(screen.getByLabelText('Resolution'), {
      target: { value: '1080p' },
    });
    fireEvent.click(screen.getByText('Apply to selected'));

    await waitFor(() =>
      expect(API.bulkUpdateVODCategoryMetadata).toHaveBeenCalledWith(
        [101, 102],
        {
          audio_languages: ['ger', 'eng'],
          subtitle_languages: ['ger'],
          resolution: '1080p',
          video_features: [],
        }
      )
    );
  });

  it('uses import rules and keeps unmatched new categories inactive', () => {
    render(<Wrapper initialAutoEnable={false} />);

    expect(screen.getByText('Import rules')).toBeInTheDocument();
    expect(
      screen.getByText('New unmatched categories are imported inactive.')
    ).toBeInTheDocument();
    expect(
      screen.queryByLabelText(/enable unmatched new movie categories/i)
    ).not.toBeInTheDocument();
  });

  it('saves a category-specific title regex', async () => {
    render(<Wrapper />);

    fireEvent.click(screen.getByLabelText('Edit title removal for Action'));
    fireEvent.change(
      screen.getByLabelText('Text to remove (regular expression)'),
      {
        target: {
          value: '-\\d+-\\s*|\\b4K\\b',
        },
      }
    );
    expect(screen.queryByLabelText('Replacement')).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Case-sensitive matching'));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(API.updateVODCategoryTitleCleanup).toHaveBeenCalledWith(101, {
        pattern: '-\\d+-\\s*|\\b4K\\b',
        case_sensitive: true,
      })
    );
  });

  it('previews category title cleanup while editing the regex', async () => {
    render(<Wrapper />);

    fireEvent.click(screen.getByLabelText('Edit title removal for Action'));
    expect(
      screen.queryByText(/Use a category-specific regular expression/)
    ).not.toBeInTheDocument();
    expect(
      screen.getByText('Open global title cleanup settings')
    ).toHaveAttribute('href', '/settings#vod-title-cleanup');
    expect(
      screen.getByLabelText('Text to remove (regular expression)')
    ).toHaveAttribute('placeholder', '-\\d+-\\s*|\\b4K\\b');
    expect(screen.getByText('Final title preview')).toBeInTheDocument();
    await waitFor(() =>
      expect(API.previewVODCategoryTitleCleanup).toHaveBeenCalledWith(
        101,
        {},
        expect.objectContaining({
          page: 1,
          pageSize: 25,
          signal: expect.any(AbortSignal),
        })
      )
    );
    expect(
      await screen.findByText('(DE-) -1- Prisons 4K - 2024')
    ).toBeInTheDocument();

    fireEvent.change(
      screen.getByLabelText('Text to remove (regular expression)'),
      {
        target: {
          value: '-\\d+-\\s*|\\b4K\\b',
        },
      }
    );

    await waitFor(() =>
      expect(API.previewVODCategoryTitleCleanup).toHaveBeenCalledWith(
        101,
        {
          pattern: '-\\d+-\\s*|\\b4K\\b',
          case_sensitive: false,
        },
        expect.objectContaining({
          page: 1,
          pageSize: 25,
          signal: expect.any(AbortSignal),
        })
      )
    );
    expect(screen.getByText('Prisons')).toBeInTheDocument();
    expect(
      screen.getByRole('columnheader', { name: 'Year' })
    ).toBeInTheDocument();
    expect(screen.getByText('2024')).toBeInTheDocument();
    expect(screen.getAllByText('Ordinary Movie')).toHaveLength(2);
    expect(
      screen.getByText(
        '2 titles in this category. 1 title on this page contains text that will be removed.'
      )
    ).toBeInTheDocument();
  });

  it('keeps direct profile decisions without a Follow rules action', () => {
    render(
      <VODCategoryFilter
        mode="profile"
        type="movie"
        categoryStates={[
          {
            id: 1,
            relation_id: 101,
            name: 'Action',
            accountName: 'Provider',
            enabled: true,
            explicit: true,
            metadata_defaults: {},
          },
          {
            id: 2,
            relation_id: 102,
            name: 'Comedy',
            accountName: 'Provider',
            enabled: false,
            explicit: false,
            metadata_defaults: {},
          },
        ]}
        setCategoryStates={vi.fn()}
      />
    );

    expect(screen.queryByText('Follow rules')).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Select Action'));
    expect(screen.queryByText('Follow rules')).not.toBeInTheDocument();
  });

  it('selects every filtered category across pagination', () => {
    const PaginatedProfile = () => {
      const [categoryStates, setCategoryStates] = useState(
        Array.from({ length: 26 }, (_, index) => ({
          id: index + 1,
          relation_id: index + 1,
          name: `Category ${String(index + 1).padStart(2, '0')}`,
          accountName: 'Provider',
          enabled: true,
          metadata_defaults: {},
        }))
      );
      return (
        <VODCategoryFilter
          mode="profile"
          type="movie"
          categoryStates={categoryStates}
          setCategoryStates={setCategoryStates}
        />
      );
    };

    render(<PaginatedProfile />);
    fireEvent.click(screen.getByLabelText('Select visible categories'));
    fireEvent.click(screen.getByText('Block selected'));
    fireEvent.change(screen.getByPlaceholderText('Filter categories...'), {
      target: { value: 'Category 26' },
    });

    expect(screen.getByLabelText('Allow Category 26')).toHaveAttribute(
      'aria-pressed',
      'false'
    );
  });
});
