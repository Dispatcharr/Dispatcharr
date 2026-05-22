import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

// Contract test for the per-group Configure modal. Covers the footer
// affordances added so users have an unambiguous bottom-of-modal action:
// Done keeps in-memory edits, Cancel triggers the parent's revert path.
// The corner X is gone; Esc / click-outside route the modal's onClose
// to onCancel.

vi.mock('@mantine/core', () => ({
  Modal: ({ opened, onClose, withCloseButton, children, title }) =>
    opened ? (
      <div
        data-testid="modal"
        data-with-close-button={String(withCloseButton ?? true)}
        onClick={(e) => {
          if (e.target.dataset.testid === 'modal-overlay') onClose?.();
        }}
      >
        <div data-testid="modal-title">{title}</div>
        {children}
      </div>
    ) : null,
  Stack: ({ children }) => <div>{children}</div>,
  Group: ({ children }) => <div>{children}</div>,
  Text: ({ children }) => <span>{children}</span>,
  Button: ({ children, onClick }) => (
    <button onClick={onClick}>{children}</button>
  ),
}));

import GroupConfigureModal from '../GroupConfigureModal';

const baseGroup = { channel_group: 1, name: 'Sports', stream_count: 42 };

const renderModal = (overrides = {}) => {
  const onDone = vi.fn();
  const onCancel = vi.fn();
  render(
    <GroupConfigureModal
      opened
      onDone={onDone}
      onCancel={onCancel}
      group={baseGroup}
      {...overrides}
    >
      <div data-testid="advanced-options">advanced options content</div>
    </GroupConfigureModal>
  );
  return { onDone, onCancel };
};

describe('GroupConfigureModal footer affordances', () => {
  it('returns null when no group is provided', () => {
    const { container } = render(
      <GroupConfigureModal opened group={null}>
        child
      </GroupConfigureModal>
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders Done and Cancel buttons in the footer', () => {
    renderModal();
    expect(screen.getByText('Done')).toBeInTheDocument();
    expect(screen.getByText('Cancel')).toBeInTheDocument();
  });

  it('removes the corner X close button so the footer is the only action', () => {
    renderModal();
    expect(screen.getByTestId('modal')).toHaveAttribute(
      'data-with-close-button',
      'false'
    );
  });

  it('clicking Done calls onDone and not onCancel', () => {
    const { onDone, onCancel } = renderModal();
    fireEvent.click(screen.getByText('Done'));
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
  });

  it('clicking Cancel calls onCancel and not onDone', () => {
    const { onDone, onCancel } = renderModal();
    fireEvent.click(screen.getByText('Cancel'));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onDone).not.toHaveBeenCalled();
  });

  it('renders the children passed in (advanced options content)', () => {
    renderModal();
    expect(screen.getByTestId('advanced-options')).toBeInTheDocument();
  });
});
