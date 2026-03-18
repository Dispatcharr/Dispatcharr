import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import RecordingSynopsis from '../RecordingSynopsis';

// Mock Mantine components
vi.mock('@mantine/core', async () => {
  return {
    Text: ({ children, size, c, lineClamp, onClick, title, style, ...props }) => {
      return (
        <div
          data-testid="text"
          data-size={size}
          data-color={c}
          data-line-clamp={lineClamp}
          title={title}
          onClick={onClick}
          style={style}
          {...props}
        >
          {children}
        </div>
      );
    },
  };
});

describe('RecordingSynopsis', () => {
  let mockOnOpen;

  beforeEach(() => {
    vi.clearAllMocks();
    mockOnOpen = vi.fn();
  });

  describe('Rendering', () => {
    it('should render with short description', () => {
      const shortDescription = 'This is a short description.';

      render(
        <RecordingSynopsis description={shortDescription} onOpen={mockOnOpen} />
      );

      const text = screen.getByText(shortDescription);
      expect(text).toBeInTheDocument();
    });

    it('should return null when description is undefined', () => {
      const { container } = render(
        <RecordingSynopsis description={undefined} onOpen={mockOnOpen} />
      );

      expect(container.firstChild).toBeNull();
    });

    it('should return null when description is null', () => {
      const { container } = render(
        <RecordingSynopsis description={null} onOpen={mockOnOpen} />
      );

      expect(container.firstChild).toBeNull();
    });

    it('should return null when description is empty string', () => {
      const { container } = render(
        <RecordingSynopsis description="" onOpen={mockOnOpen} />
      );

      expect(container.firstChild).toBeNull();
    });

    it('should render without onOpen callback', () => {
      const description = 'Test description';

      render(<RecordingSynopsis description={description} />);

      expect(screen.getByText(description)).toBeInTheDocument();
    });
  });

  describe('Text Truncation', () => {
    it('should not truncate description with exactly 140 characters', () => {
      const exactLength = 'A'.repeat(140);

      render(
        <RecordingSynopsis description={exactLength} onOpen={mockOnOpen} />
      );

      expect(screen.getByText(exactLength)).toBeInTheDocument();
      expect(screen.queryByText(/\.\.\./)).not.toBeInTheDocument();
    });

    it('should truncate description with 141 characters', () => {
      const overLength = 'A'.repeat(141);

      render(
        <RecordingSynopsis description={overLength} onOpen={mockOnOpen} />
      );

      const expectedPreview = `${overLength.slice(0, 140).trim()}...`;
      expect(screen.getByText(expectedPreview)).toBeInTheDocument();
    });

    it('should trim whitespace before adding ellipsis', () => {
      const description = 'A'.repeat(135) + '     B'.repeat(10);

      render(
        <RecordingSynopsis description={description} onOpen={mockOnOpen} />
      );

      const preview = screen.getByTestId('text').textContent;
      expect(preview).toMatch(/\.\.\./);
      expect(preview).not.toMatch(/\s+\.\.\./);
    });
  });

  describe('Click Interactions', () => {
    it('should call onOpen when clicked', () => {
      const description = 'Test description';

      render(
        <RecordingSynopsis description={description} onOpen={mockOnOpen} />
      );

      const text = screen.getByText(description);
      fireEvent.click(text);

      expect(mockOnOpen).toHaveBeenCalledTimes(1);
    });

    it('should not throw error when clicked without onOpen callback', () => {
      const description = 'Test description';

      render(<RecordingSynopsis description={description} />);

      const text = screen.getByText(description);
      expect(() => fireEvent.click(text)).not.toThrow();
    });

    it('should handle multiple clicks', () => {
      const description = 'Test description';

      render(
        <RecordingSynopsis description={description} onOpen={mockOnOpen} />
      );

      const text = screen.getByText(description);

      fireEvent.click(text);
      fireEvent.click(text);
      fireEvent.click(text);

      expect(mockOnOpen).toHaveBeenCalledTimes(3);
    });

    it('should be clickable with truncated text', () => {
      const longDescription = 'A'.repeat(200);

      render(
        <RecordingSynopsis description={longDescription} onOpen={mockOnOpen} />
      );

      const text = screen.getByTestId('text');
      fireEvent.click(text);

      expect(mockOnOpen).toHaveBeenCalledTimes(1);
    });
  });
});
