import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@mantine/core', () => ({
  ActionIcon: ({ children, onClick, disabled, 'aria-label': ariaLabel }) => (
    <button aria-label={ariaLabel} onClick={onClick} disabled={disabled}>
      {children}
    </button>
  ),
  Button: ({ children, onClick, disabled }) => (
    <button onClick={onClick} disabled={disabled}>
      {children}
    </button>
  ),
  Group: ({ children }) => <div>{children}</div>,
  Tooltip: ({ children }) => <>{children}</>,
}));

vi.mock('lucide-react', () => ({
  LockKeyhole: () => null,
  LockKeyholeOpen: () => null,
  Pencil: () => null,
}));

import VODEnrichmentButton from '../VODEnrichmentButton.jsx';

describe('VODEnrichmentButton', () => {
  it('keeps the lock control visible for an unlocked title', () => {
    const onLock = vi.fn();
    render(
      <VODEnrichmentButton
        onClick={vi.fn()}
        onLock={onLock}
        onUnlock={vi.fn()}
      />
    );

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Lock automatic metadata matching',
      })
    );
    expect(onLock).toHaveBeenCalledOnce();
    expect(screen.getByRole('button', { name: 'Edit metadata' })).toBeEnabled();
  });

  it('offers unlock and protects editing while the title is locked', () => {
    const onUnlock = vi.fn();
    render(
      <VODEnrichmentButton
        locked
        onClick={vi.fn()}
        onLock={vi.fn()}
        onUnlock={onUnlock}
      />
    );

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Unlock automatic metadata matching',
      })
    );
    expect(onUnlock).toHaveBeenCalledOnce();
    expect(
      screen.getByRole('button', { name: 'Edit metadata' })
    ).toBeDisabled();
  });
});
