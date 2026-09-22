import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ListPagination from '../ListPagination.jsx';

vi.mock('@mantine/core', () => ({
  Group: ({ children }) => <div>{children}</div>,
  Text: ({ children }) => <span>{children}</span>,
  Select: ({ value, onChange, data, 'aria-label': ariaLabel }) => (
    <select
      aria-label={ariaLabel}
      value={value}
      onChange={(event) => onChange(event.target.value)}
    >
      {data.map((item) => (
        <option key={item.value} value={item.value}>
          {item.label}
        </option>
      ))}
    </select>
  ),
  Pagination: ({ value, onChange, total }) => (
    <button onClick={() => onChange(Math.min(value + 1, total))}>
      Page {value} of {total}
    </button>
  ),
}));

describe('ListPagination', () => {
  it('shows the current range and advances pages', () => {
    const onPageChange = vi.fn();
    render(
      <ListPagination
        page={2}
        pageSize={25}
        total={61}
        onPageChange={onPageChange}
        onPageSizeChange={vi.fn()}
      />
    );

    expect(screen.getByText('26–50 of 61')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Page 2 of 3' }));
    expect(onPageChange).toHaveBeenCalledWith(3);
  });

  it('changes the row count and handles an empty list', () => {
    const onPageSizeChange = vi.fn();
    render(
      <ListPagination
        page={1}
        pageSize={25}
        total={0}
        onPageChange={vi.fn()}
        onPageSizeChange={onPageSizeChange}
      />
    );

    expect(screen.getByText('0–0 of 0')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Rows'), {
      target: { value: '100' },
    });
    expect(onPageSizeChange).toHaveBeenCalledWith(100);
  });
});
