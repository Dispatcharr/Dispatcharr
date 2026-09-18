import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@mantine/core', () => ({
  Alert: ({ children }) => <div>{children}</div>,
  Button: ({ children, onClick, disabled }) => (
    <button onClick={onClick} disabled={disabled}>
      {children}
    </button>
  ),
  Checkbox: ({ checked, onChange, ...props }) => (
    <input
      type="checkbox"
      aria-label={props['aria-label']}
      checked={checked ?? false}
      onChange={(event) =>
        onChange?.({ currentTarget: { checked: event.target.checked } })
      }
    />
  ),
  Group: ({ children }) => <div>{children}</div>,
  Modal: ({ opened, children, title }) =>
    opened ? (
      <div role="dialog" aria-label={title}>
        {children}
      </div>
    ) : null,
  Pagination: () => <div data-testid="pagination" />,
  ScrollArea: ({ children }) => <div>{children}</div>,
  SegmentedControl: ({ value, onChange, data }) => (
    <div>
      {data.map((item) => (
        <button
          key={item.value}
          aria-pressed={value === item.value}
          onClick={() => onChange(item.value)}
        >
          {item.label}
        </button>
      ))}
    </div>
  ),
  Select: ({ label, value, onChange, data = [] }) => (
    <label>
      {label}
      <select
        aria-label={label}
        value={value || ''}
        onChange={(event) => onChange(event.target.value || null)}
      >
        <option value="" />
        {data.map((item) => (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        ))}
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
  TextInput: ({ label, value, onChange }) => (
    <label>
      {label}
      <input aria-label={label} value={value} onChange={onChange} />
    </label>
  ),
}));

import VODUserCategorySelector from '../VODUserCategorySelector.jsx';
import { flattenVODCategoryRelations } from '../VODUserCategorySelector.utils.js';

const relation = (id, accountName, overrides = {}) => ({
  id,
  m3u_account: id,
  account_name: accountName,
  enabled: true,
  metadata_defaults: {},
  ...overrides,
});

describe('VODUserCategorySelector', () => {
  it('flattens enabled account/category relations for per-user access', () => {
    const rows = flattenVODCategoryRelations({
      1: {
        name: 'Anime',
        category_type: 'series',
        m3u_accounts: [
          relation(11, 'Provider B'),
          relation(12, 'Provider A', { enabled: false }),
        ],
      },
    });

    expect(rows).toEqual([
      expect.objectContaining({
        id: '11',
        accountName: 'Provider B',
        categoryName: 'Anime',
        categoryType: 'series',
      }),
    ]);
  });

  it('applies mass selection to every filtered row across pages', () => {
    const matching = Array.from({ length: 55 }, (_, index) =>
      relation(index + 1, `Provider ${index + 1}`)
    );
    const categories = {
      1: {
        name: 'Anime',
        category_type: 'series',
        m3u_accounts: matching,
      },
      2: {
        name: 'Keep me',
        category_type: 'movie',
        m3u_accounts: [relation(999, 'Other provider')],
      },
    };
    const onChange = vi.fn();
    const onClose = vi.fn();

    render(
      <VODUserCategorySelector
        opened
        onClose={onClose}
        categories={categories}
        selectedIds={[]}
        onChange={onChange}
      />
    );

    fireEvent.change(screen.getByLabelText('Search'), {
      target: { value: 'Anime' },
    });
    fireEvent.click(screen.getByLabelText('Select all filtered categories'));
    expect(
      screen.getByRole('button', { name: 'Block selected (55)' })
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', { name: 'Block selected (55)' })
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Apply category access' })
    );

    expect(onChange).toHaveBeenCalledWith(['999']);
    expect(onClose).toHaveBeenCalled();
  });

  it('persists an explicit selection even when every category is allowed', () => {
    const onChange = vi.fn();

    render(
      <VODUserCategorySelector
        opened
        onClose={vi.fn()}
        categories={{
          1: {
            name: 'Movies',
            category_type: 'movie',
            m3u_accounts: [
              relation(11, 'Provider A'),
              relation(12, 'Provider B'),
            ],
          },
        }}
        selectedIds={[]}
        onChange={onChange}
      />
    );

    fireEvent.click(
      screen.getByRole('button', { name: 'Apply category access' })
    );

    expect(onChange).toHaveBeenCalledWith(['11', '12']);
  });
});
