import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { describe, expect, it, vi } from 'vitest';
import GroupConfigureModal from '../GroupConfigureModal.jsx';

const renderModal = (props = {}) => {
  const onDone = vi.fn(),
    onCancel = vi.fn(),
    onRetryContent = vi.fn();
  render(
    <MantineProvider env="test">
      <GroupConfigureModal
        opened
        group={{ channel_group: 1, name: 'Sports', stream_count: 0 }}
        onDone={onDone}
        onCancel={onCancel}
        onRetryContent={onRetryContent}
        {...props}
      >
        <span>Settings content</span>
      </GroupConfigureModal>
    </MantineProvider>
  );
  return { onDone, onCancel, onRetryContent };
};

describe('Live category settings', () => {
  it('has a named X and Apply, without a redundant Cancel button', () => {
    renderModal();
    expect(
      screen.getByRole('button', { name: 'Close category settings' })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Apply', exact: true })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Cancel', exact: true })
    ).not.toBeInTheDocument();
  });

  it('closes an unchanged draft immediately', () => {
    const { onCancel } = renderModal();
    fireEvent.click(
      screen.getByRole('button', { name: 'Close category settings' })
    );
    expect(onCancel).toHaveBeenCalledOnce();
    expect(
      screen.queryByText('Discard changes to this category?')
    ).not.toBeInTheDocument();
  });

  it('keeps edits or explicitly discards them when X is used', async () => {
    const { onDone, onCancel } = renderModal({ dirty: true });
    fireEvent.click(
      screen.getByRole('button', { name: 'Close category settings' })
    );
    expect(
      await screen.findByRole('button', { name: 'Keep editing' })
    ).toBeInTheDocument();
    expect(screen.getByText('Settings content')).toBeVisible();
    expect(onCancel).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
    await waitFor(() =>
      expect(
        screen.queryByRole('button', { name: 'Discard', exact: true })
      ).not.toBeInTheDocument()
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Close category settings' })
    );
    fireEvent.click(
      await screen.findByRole('button', { name: 'Discard', exact: true })
    );
    expect(onCancel).toHaveBeenCalledOnce();
    expect(onDone).not.toHaveBeenCalled();
  });

  it('also protects dirty drafts when Escape is used', async () => {
    const { onCancel } = renderModal({ dirty: true });
    fireEvent.keyDown(
      screen.getByRole('button', { name: 'Close category settings' }),
      { key: 'Escape', code: 'Escape' }
    );
    expect(
      await screen.findByRole('button', { name: 'Discard', exact: true })
    ).toBeInTheDocument();
    expect(onCancel).not.toHaveBeenCalled();
  });

  it('applies to the parent draft without invoking Discard', () => {
    const { onDone, onCancel } = renderModal({ dirty: true });
    fireEvent.click(screen.getByRole('button', { name: 'Apply', exact: true }));
    expect(onDone).toHaveBeenCalledOnce();
    expect(onCancel).not.toHaveBeenCalled();
  });

  it('separates preview and imported counts and never calls either available', () => {
    renderModal({ content: { source: 'provider', count: 238 } });
    expect(screen.getByRole('status')).toHaveTextContent(
      '238 in preview · 0 imported'
    );
    expect(screen.queryByText(/streams available/)).not.toBeInTheDocument();
  });

  it('uses an unknown marker instead of claiming an unqueried category is empty', () => {
    renderModal({
      group: { channel_group: 1, name: 'Sports' },
      content: { loading: true },
    });
    expect(screen.getByRole('status')).toHaveTextContent(
      '— imported · loading…'
    );
  });

  it('offers Retry after a loading error without changing settings', () => {
    const { onRetryContent, onDone } = renderModal({
      content: { error: 'Preview unavailable' },
    });
    expect(screen.getByRole('alert')).toHaveTextContent('Preview unavailable');
    fireEvent.click(
      screen.getByRole('button', { name: 'Retry category preview' })
    );
    expect(onRetryContent).toHaveBeenCalledOnce();
    expect(onDone).not.toHaveBeenCalled();
  });
});
