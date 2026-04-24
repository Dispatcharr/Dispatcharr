import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { YouTubeTrailerModal } from '../YouTubeTrailerModal';

// Mock Mantine components
vi.mock('@mantine/core', () => ({
  Modal: ({ opened, onClose, title, children, size, centered }) => {
    if (!opened) return null;
    return (
      <div
        data-testid="modal"
        data-title={title}
        data-size={size}
        data-centered={centered}
      >
        <button onClick={onClose} data-testid="modal-close">Close</button>
        <div>{children}</div>
      </div>
    );
  },
  Box: ({ children, ...props }) => (
    <div data-testid="box" {...props}>{children}</div>
  ),
}));

describe('YouTubeTrailerModal', () => {
  const mockTrailerUrl = 'https://www.youtube.com/embed/dQw4w9WgXcQ';
  const mockOnClose = vi.fn();

  it('should not render when opened is false', () => {
    render(
      <YouTubeTrailerModal
        opened={false}
        onClose={mockOnClose}
        trailerUrl={mockTrailerUrl}
      />
    );

    expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
  });

  it('should render modal when opened is true', () => {
    render(
      <YouTubeTrailerModal
        opened={true}
        onClose={mockOnClose}
        trailerUrl={mockTrailerUrl}
      />
    );

    expect(screen.getByTestId('modal')).toBeInTheDocument();
  });

  it('should display correct modal title', () => {
    render(
      <YouTubeTrailerModal
        opened={true}
        onClose={mockOnClose}
        trailerUrl={mockTrailerUrl}
      />
    );

    const modal = screen.getByTestId('modal');
    expect(modal).toHaveAttribute('data-title', 'Trailer');
  });

  it('should render iframe with correct trailerUrl', () => {
    render(
      <YouTubeTrailerModal
        opened={true}
        onClose={mockOnClose}
        trailerUrl={mockTrailerUrl}
      />
    );

    const iframe = screen.getByTitle('YouTube Trailer');
    expect(iframe).toBeInTheDocument();
    expect(iframe).toHaveAttribute('src', mockTrailerUrl);
  });

  it('should not render iframe when trailerUrl is null', () => {
    render(
      <YouTubeTrailerModal
        opened={true}
        onClose={mockOnClose}
        trailerUrl={null}
      />
    );

    expect(screen.queryByTitle('YouTube Trailer')).not.toBeInTheDocument();
  });

  it('should call onClose when close button clicked', () => {
    const mockClose = vi.fn();

    render(
      <YouTubeTrailerModal
        opened={true}
        onClose={mockClose}
        trailerUrl={mockTrailerUrl}
      />
    );

    const closeButton = screen.getByTestId('modal-close');
    closeButton.click();

    expect(mockClose).toHaveBeenCalledOnce();
  });
});
