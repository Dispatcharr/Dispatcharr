import { render, screen, fireEvent } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { describe, it, expect, vi } from 'vitest';
import ListPagination from '../ListPagination.jsx';

describe('ListPagination', () => {
  it('keeps the existing row options and names pagination controls', () => {
    const onPageChange = vi.fn();
    render(
      <MantineProvider>
        <ListPagination
          page={2}
          pageSize={25}
          total={80}
          onPageChange={onPageChange}
          onPageSizeChange={vi.fn()}
        />
      </MantineProvider>
    );
    expect(screen.getByRole('textbox', { name: 'Rows per page' })).toHaveValue(
      '25'
    );
    expect(screen.getByText('26–50 of 80')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Next page' }));
    expect(onPageChange).toHaveBeenCalledWith(3);
  });

  it('supports Library item counts without changing row-based views', () => {
    const onPageSizeChange = vi.fn();
    render(
      <MantineProvider>
        <ListPagination
          page={1}
          pageSize={12}
          total={48}
          onPageChange={vi.fn()}
          onPageSizeChange={onPageSizeChange}
          pageSizeOptions={[12, 24, 48, 96]}
          itemLabel="Items"
        />
      </MantineProvider>
    );
    expect(screen.getByText('1–12 of 48')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('textbox', { name: 'Items per page' }));
    fireEvent.click(screen.getByRole('option', { name: '24' }));
    expect(onPageSizeChange).toHaveBeenCalledWith(24);
  });
  it('disables both page and size controls while a result is loading', () => {
    render(
      <MantineProvider>
        <ListPagination
          page={1}
          pageSize={25}
          total={80}
          onPageChange={vi.fn()}
          onPageSizeChange={vi.fn()}
          disabled
        />
      </MantineProvider>
    );
    expect(
      screen.getByRole('textbox', { name: 'Rows per page' })
    ).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled();
  });
});
