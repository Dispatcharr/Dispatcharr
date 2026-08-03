import { MantineProvider } from '@mantine/core';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { SourceCard } from '../MediaLibrary';

const source = {
  id: 20,
  name: 'Emby',
  provider_type: 'emby',
  base_url: 'https://emby.example.com',
  enabled: true,
  include_libraries: ['movies', 'shows'],
  last_synced_at: '2026-08-01T21:59:25Z',
  sync_interval: 0,
};

const latestRun = {
  status: 'completed',
  processed_items: 9498,
  created_items: 7806,
  updated_items: 11,
  removed_items: 4,
  skipped_items: 9,
  ambiguous_items: 2,
};

const handlers = {
  onToggle: vi.fn(),
  onTest: vi.fn(),
  onSync: vi.fn(),
  onViewScan: vi.fn(),
  onEdit: vi.fn(),
  onDelete: vi.fn(),
};

describe('Media Library source card', () => {
  it('keeps status, scan metrics, and actions in a consistent order', async () => {
    const user = userEvent.setup();
    render(
      <MantineProvider>
        <SourceCard
          source={source}
          latestRun={latestRun}
          busy={false}
          {...handlers}
        />
      </MantineProvider>
    );

    expect(screen.getByRole('switch', { name: 'Enabled' })).toBeChecked();

    const summary = screen.getByTestId('source-scan-summary');
    const summaryText = summary.textContent;
    const labels = [
      'Processed',
      'Created',
      'Updated',
      'Stale relations',
      'Skipped',
      'Ambiguous',
    ];

    expect(within(summary).getByText('9,498')).toBeInTheDocument();
    expect(
      within(summary).queryByText('What does ambiguous mean?')
    ).not.toBeInTheDocument();
    labels.slice(1).forEach((label, index) => {
      expect(summaryText.indexOf(labels[index])).toBeLessThan(
        summaryText.indexOf(label)
      );
    });

    const actions = within(screen.getByTestId('source-action-bar'))
      .getAllByRole('button')
      .map((button) => button.textContent.trim());
    expect(actions).toEqual(['Test', 'Sync', 'View Scan', 'Edit', 'Delete']);
    expect(screen.getByTestId('source-actions-row')).toHaveStyle({
      display: 'grid',
      gridTemplateColumns: '0.9fr 0.95fr 1.3fr 0.75fr 0.9fr',
      width: '100%',
    });

    await user.hover(within(summary).getByText('Ambiguous'));
    expect(
      await screen.findByText(/multiple plausible records or conflicting/i)
    ).toBeInTheDocument();
  });
});
