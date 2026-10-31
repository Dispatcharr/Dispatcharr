import { act, fireEvent, render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import api from '../../api';
import { showNotification } from '../../utils/notificationUtils.js';
import CategoryCleanupFields from '../CategoryCleanupFields.jsx';

vi.mock('../../api', () => ({ default: { vodLibraryAction: vi.fn() } }));
vi.mock('../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));
const data = {
  count: 1,
  page: 1,
  page_size: 10,
  results: [
    {
      id: 1,
      source_id: 3,
      content_type: 'movie',
      before: 'EN | Film (2020)',
      after: 'Film',
      year: 2020,
    },
  ],
};
const ui = (props = {}) => (
  <MantineProvider env="test">
    <CategoryCleanupFields
      accountId={7}
      categoryId={9}
      value={{ pattern: '^EN \\|' }}
      onChange={vi.fn()}
      {...props}
    />
  </MantineProvider>
);
beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  api.vodLibraryAction.mockResolvedValue(data);
});
afterEach(() => vi.useRealTimers());

describe('Category cleanup preview', () => {
  it('explains global cleanup and has no case-sensitivity control', () => {
    const onChange = vi.fn();
    render(ui({ onChange }));
    expect(
      screen.queryByRole('switch', { name: 'Case sensitive' })
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(
        'Prefixes, text removals and release-year formats configured in Settings → Cleanup are applied before this rule.'
      )
    ).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });
  it('automatically previews the unsaved rule without an import or save action', async () => {
    const valid = vi.fn();
    render(ui({ onValidityChange: valid }));
    expect(valid).toHaveBeenLastCalledWith(false);
    expect(api.vodLibraryAction).not.toHaveBeenCalled();
    await act(async () => vi.advanceTimersByTimeAsync(300));
    expect(api.vodLibraryAction).toHaveBeenCalledExactlyOnceWith(
      'cleanup-preview',
      {
        scope: 'category',
        account: 7,
        category: 9,
        title_cleanup: { pattern: '^EN \\|' },
        page: 1,
        page_size: 10,
      }
    );
    expect(valid).toHaveBeenLastCalledWith(true);
    expect(screen.getByText('Film', { exact: true })).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /Save|Apply|Import/ })
    ).not.toBeInTheDocument();
  });
  it('rejects invalid drafts and can retry without persisting anything', async () => {
    api.vodLibraryAction.mockRejectedValueOnce(
      new Error('Invalid regular expression')
    );
    const valid = vi.fn();
    render(ui({ onValidityChange: valid }));
    await act(async () => vi.advanceTimersByTimeAsync(300));
    expect(showNotification).toHaveBeenCalledWith(
      expect.objectContaining({
        message: 'Invalid regular expression',
        color: 'red',
      })
    );
    expect(screen.getByLabelText('Remove from titles (regex)')).toHaveAttribute(
      'aria-invalid',
      'true'
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(valid).toHaveBeenLastCalledWith(false);
    fireEvent.click(screen.getByRole('button', { name: 'Retry preview' }));
    await act(async () => vi.advanceTimersByTimeAsync(300));
    expect(valid).toHaveBeenLastCalledWith(true);
    expect(
      api.vodLibraryAction.mock.calls.every(
        ([action]) => action === 'cleanup-preview'
      )
    ).toBe(true);
  });
  it('ignores an older response when a category or draft changes', async () => {
    let finish;
    api.vodLibraryAction.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        })
    );
    const view = render(ui());
    await act(async () => vi.advanceTimersByTimeAsync(300));
    view.rerender(ui({ categoryId: 10, value: {} }));
    await act(async () =>
      finish({
        ...data,
        results: [{ ...data.results[0], after: 'Stale result' }],
      })
    );
    expect(screen.queryByText('Stale result')).not.toBeInTheDocument();
    await act(async () => vi.advanceTimersByTimeAsync(300));
    expect(api.vodLibraryAction).toHaveBeenLastCalledWith(
      'cleanup-preview',
      expect.objectContaining({ category: 10, title_cleanup: {} })
    );
  });
});
