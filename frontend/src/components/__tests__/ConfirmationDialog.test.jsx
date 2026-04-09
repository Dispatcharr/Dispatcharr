import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import ConfirmationDialog from '../ConfirmationDialog';
import useWarningsStore from '../../store/warnings';

// Mock the warnings store
vi.mock('../../store/warnings');

// Mock Mantine components
vi.mock('@mantine/core', async () => {
  return {
    Modal: ({ children, opened, onClose, title }) =>
      opened ? (
        <div data-testid="modal">
          <div data-testid="modal-title">{title}</div>
          {children}
        </div>
      ) : null,
    Group: ({ children }) => <div>{children}</div>,
    Button: ({ children, onClick, disabled }) => (
      <button onClick={onClick} disabled={disabled}>
        {children}
      </button>
    ),
    Checkbox: ({ label, checked, onChange }) => (
      <label>
        <input
          type="checkbox"
          checked={checked}
          onChange={onChange}
        />
        {label}
      </label>
    ),
    Box: ({ children }) => <div>{children}</div>,
  };
});

describe('ConfirmationDialog', () => {
  const mockOnClose = vi.fn();
  const mockOnConfirm = vi.fn();
  const mockOnSuppressChange = vi.fn();
  const mockSuppressWarning = vi.fn();
  const mockIsWarningSuppressed = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    useWarningsStore.mockImplementation((selector) => {
      const state = {
        suppressWarning: mockSuppressWarning,
        isWarningSuppressed: mockIsWarningSuppressed,
      };
      return selector ? selector(state) : state;
    });
  });

  it('should render when opened', () => {
    render(
      <ConfirmationDialog
        opened={true}
        onClose={mockOnClose}
        onConfirm={mockOnConfirm}
      />
    );

    expect(screen.getByTestId('modal')).toBeInTheDocument();
    expect(screen.getByText('Are you sure you want to proceed?')).toBeInTheDocument();
  });

  it('should not render when closed', () => {
    render(
      <ConfirmationDialog
        opened={false}
        onClose={mockOnClose}
        onConfirm={mockOnConfirm}
      />
    );

    expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
  });

  it('should display custom title and message', () => {
    render(
      <ConfirmationDialog
        opened={true}
        onClose={mockOnClose}
        onConfirm={mockOnConfirm}
        title="Delete Item"
        message="This action cannot be undone"
      />
    );

    expect(screen.getByTestId('modal-title')).toHaveTextContent('Delete Item');
    expect(screen.getByText('This action cannot be undone')).toBeInTheDocument();
  });

  it('should call onConfirm when confirm button is clicked', () => {
    render(
      <ConfirmationDialog
        opened={true}
        onClose={mockOnClose}
        onConfirm={mockOnConfirm}
        confirmLabel="Delete"
      />
    );

    fireEvent.click(screen.getByText('Delete'));
    expect(mockOnConfirm).toHaveBeenCalledTimes(1);
  });

  it('should call onClose when cancel button is clicked', () => {
    render(
      <ConfirmationDialog
        opened={true}
        onClose={mockOnClose}
        onConfirm={mockOnConfirm}
        cancelLabel="Cancel"
      />
    );

    fireEvent.click(screen.getByText('Cancel'));
    expect(mockOnClose).toHaveBeenCalledTimes(1);
  });

  it('should show suppress checkbox when actionKey is provided', () => {
    render(
      <ConfirmationDialog
        opened={true}
        onClose={mockOnClose}
        onConfirm={mockOnConfirm}
        actionKey="delete-action"
      />
    );

    expect(screen.getByLabelText("Don't ask me again")).toBeInTheDocument();
  });

  it('should not show suppress checkbox when actionKey is not provided', () => {
    render(
      <ConfirmationDialog
        opened={true}
        onClose={mockOnClose}
        onConfirm={mockOnConfirm}
      />
    );

    expect(screen.queryByLabelText("Don't ask me again")).not.toBeInTheDocument();
  });

  it('should call suppressWarning when suppress is checked and confirmed', () => {
    render(
      <ConfirmationDialog
        opened={true}
        onClose={mockOnClose}
        onConfirm={mockOnConfirm}
        actionKey="delete-action"
      />
    );

    fireEvent.click(screen.getByLabelText("Don't ask me again"));
    fireEvent.click(screen.getByText('Confirm'));

    expect(mockSuppressWarning).toHaveBeenCalledWith('delete-action');
  });

  it('should call onSuppressChange when suppress checkbox is toggled', () => {
    render(
      <ConfirmationDialog
        opened={true}
        onClose={mockOnClose}
        onConfirm={mockOnConfirm}
        actionKey="delete-action"
        onSuppressChange={mockOnSuppressChange}
      />
    );

    fireEvent.click(screen.getByLabelText("Don't ask me again"));
    expect(mockOnSuppressChange).toHaveBeenCalledWith(true);
  });

  it('should show delete file option when enabled', () => {
    render(
      <ConfirmationDialog
        opened={true}
        onClose={mockOnClose}
        onConfirm={mockOnConfirm}
        showDeleteFileOption={true}
      />
    );

    expect(screen.getByLabelText('Also delete files from disk')).toBeInTheDocument();
  });

  it('should pass deleteFiles state to onConfirm when delete option is checked', () => {
    render(
      <ConfirmationDialog
        opened={true}
        onClose={mockOnClose}
        onConfirm={mockOnConfirm}
        showDeleteFileOption={true}
      />
    );

    fireEvent.click(screen.getByLabelText('Also delete files from disk'));
    fireEvent.click(screen.getByText('Confirm'));

    expect(mockOnConfirm).toHaveBeenCalledWith(true);
  });

  it('should reset deleteFiles state after confirmation', () => {
    const { rerender } = render(
      <ConfirmationDialog
        opened={true}
        onClose={mockOnClose}
        onConfirm={mockOnConfirm}
        showDeleteFileOption={true}
      />
    );

    fireEvent.click(screen.getByLabelText('Also delete files from disk'));
    fireEvent.click(screen.getByText('Confirm'));

    rerender(
      <ConfirmationDialog
        opened={true}
        onClose={mockOnClose}
        onConfirm={mockOnConfirm}
        showDeleteFileOption={true}
      />
    );

    expect(screen.getByLabelText('Also delete files from disk')).not.toBeChecked();
  });

  it('should show loading state on confirm button', () => {
    render(
      <ConfirmationDialog
        opened={true}
        onClose={mockOnClose}
        onConfirm={mockOnConfirm}
        loading={true}
      />
    );

    expect(screen.getByText('Confirm')).toBeDisabled();
  });

  it('should disable cancel button when loading', () => {
    render(
      <ConfirmationDialog
        opened={true}
        onClose={mockOnClose}
        onConfirm={mockOnConfirm}
        loading={true}
      />
    );

    expect(screen.getByText('Cancel')).toBeDisabled();
  });

  it('should initialize suppress checkbox based on store state', () => {
    mockIsWarningSuppressed.mockReturnValue(true);

    render(
      <ConfirmationDialog
        opened={true}
        onClose={mockOnClose}
        onConfirm={mockOnConfirm}
        actionKey="delete-action"
      />
    );

    expect(screen.getByLabelText("Don't ask me again")).toBeChecked();
  });
});
