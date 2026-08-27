import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import ErrorBoundary from '../ErrorBoundary';

// Component that throws an error for testing
const ThrowError = ({ shouldThrow }) => {
  if (shouldThrow) {
    throw new Error('Test error');
  }
  return <div>Child component</div>;
};

describe('ErrorBoundary', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Suppress console.error for cleaner test output
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('should render children when there is no error', () => {
    render(
      <ErrorBoundary>
        <div>Test content</div>
      </ErrorBoundary>
    );

    expect(screen.getByText('Test content')).toBeInTheDocument();
  });

  it('should render error message when child component throws error', () => {
    render(
      <ErrorBoundary>
        <ThrowError shouldThrow={true} />
      </ErrorBoundary>
    );

    expect(screen.getByText(/Something went wrong/)).toBeInTheDocument();
    expect(screen.queryByText('Child component')).not.toBeInTheDocument();
  });

  it('should not render error message when child component does not throw', () => {
    render(
      <ErrorBoundary>
        <ThrowError shouldThrow={false} />
      </ErrorBoundary>
    );

    expect(screen.getByText('Child component')).toBeInTheDocument();
    expect(screen.queryByText('Something went wrong')).not.toBeInTheDocument();
  });

  it('should handle multiple children', () => {
    render(
      <ErrorBoundary>
        <div>First child</div>
        <div>Second child</div>
      </ErrorBoundary>
    );

    expect(screen.getByText('First child')).toBeInTheDocument();
    expect(screen.getByText('Second child')).toBeInTheDocument();
  });

  it('should catch errors from nested children', () => {
    render(
      <ErrorBoundary>
        <div>
          <div>
            <ThrowError shouldThrow={true} />
          </div>
        </div>
      </ErrorBoundary>
    );

    expect(screen.getByText(/Something went wrong/)).toBeInTheDocument();
  });

  it('should have hasError state set to true after catching error', () => {
    const { container } = render(
      <ErrorBoundary>
        <ThrowError shouldThrow={true} />
      </ErrorBoundary>
    );

    // Verify error boundary rendered fallback UI
    expect(container.querySelector('[role="alert"]')).toHaveTextContent(
      'Something went wrong'
    );
  });

  it('should have hasError state set to false initially', () => {
    render(
      <ErrorBoundary>
        <div data-testid="child">Normal content</div>
      </ErrorBoundary>
    );

    // Verify children are rendered (not error state)
    expect(screen.getByTestId('child')).toBeInTheDocument();
  });

  it('copies a report with the error and React component stacks', async () => {
    const writeText = vi.fn().mockResolvedValue();
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });

    render(
      <ErrorBoundary name="channels">
        <ThrowError shouldThrow={true} />
      </ErrorBoundary>
    );

    fireEvent.click(
      screen.getByRole('button', { name: 'Copy diagnostic report' })
    );

    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(
        expect.stringContaining('Dispatcharr frontend error report')
      );
    });
    expect(writeText).toHaveBeenCalledWith(
      expect.stringContaining('Boundary: channels')
    );
    expect(writeText).toHaveBeenCalledWith(
      expect.stringContaining('React component stack:')
    );
    expect(
      screen.getByRole('button', { name: 'Copied!' })
    ).toBeInTheDocument();
  });

  it('renders nothing when Hide is clicked', () => {
    render(
      <ErrorBoundary>
        <ThrowError shouldThrow={true} />
      </ErrorBoundary>
    );

    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Hide' }));

    expect(screen.queryByText('Something went wrong')).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
