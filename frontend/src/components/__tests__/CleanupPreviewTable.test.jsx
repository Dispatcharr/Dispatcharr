import { fireEvent, render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { describe, expect, it, vi } from 'vitest';
import CleanupPreviewTable from '../CleanupPreviewTable.jsx';

const row = {
  content_type: 'movie',
  id: 1,
  before: 'Raw Film (2020)',
  after: 'Film',
  year: 2020,
  locked: true,
};
describe('cleanup preview tables', () => {
  it('uses paginated server context when selected titles are not loaded in the table', () => {
    const item = {
      content_type: 'series',
      content_id: 8,
      name: 'Canonical title',
      provider_name: 'Provider title',
      tmdb_id: '123',
    };
    const onPreview = vi.fn();
    render(
      <MantineProvider env="test">
        <CleanupPreviewTable
          rows={[{ ...row, content_type: 'series', id: 8, item }]}
          onPreview={onPreview}
        />
      </MantineProvider>
    );
    expect(
      screen.getByText('Provider title', { selector: 'p' })
    ).toBeInTheDocument();
    expect(screen.getByText('TMDB 123')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Preview Film' }));
    expect(onPreview).toHaveBeenCalledExactlyOnceWith(item);
  });
  it('keeps the compact category preview without TMDB or protection details and with safe title truncation', () => {
    render(
      <MantineProvider env="test">
        <CleanupPreviewTable rows={[row]} />
      </MantineProvider>
    );
    expect(
      screen.getAllByRole('columnheader').map((cell) => cell.textContent)
    ).toEqual(['Provider title', 'Clean title', 'Year']);
    expect(screen.queryByLabelText('Protected')).not.toBeInTheDocument();
    expect(screen.getByText(row.after)).toHaveStyle({
      color: 'var(--mantine-color-teal-text)',
    });
    expect(screen.getByText(row.before).className).toContain('cleanupTitle');
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
  it('uses the exact type and ID for status and preview and the fresh protection result', () => {
    const movie = {
      content_type: 'movie',
      content_id: 1,
      provider_name: 'Original Provider Film',
      tmdb_id: '42',
      metadata_locked: false,
    };
    const onPreview = vi.fn();
    render(
      <MantineProvider env="test">
        <CleanupPreviewTable
          rows={[row, { ...row, content_type: 'series', locked: false }]}
          items={[
            movie,
            {
              content_type: 'series',
              content_id: 1,
              metadata_status: 'failed',
            },
          ]}
          onPreview={onPreview}
        />
      </MantineProvider>
    );
    expect(screen.getByText('Original Provider Film')).toBeInTheDocument();
    expect(screen.getByText('TMDB 42')).toBeInTheDocument();
    expect(screen.getByText('TMDB lookup failed')).toBeInTheDocument();
    expect(screen.getByLabelText('Metadata locked')).toBeInTheDocument();
    expect(screen.getByLabelText('Metadata unlocked')).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: 'Preview Film' })[0]);
    expect(onPreview).toHaveBeenCalledExactlyOnceWith(movie);
  });
});
