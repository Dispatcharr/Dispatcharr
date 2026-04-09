import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import LazyLogo from '../LazyLogo';
import useLogosStore from '../../store/logos';

// Mock the logos store
vi.mock('../../store/logos', () => ({
  default: vi.fn(),
}));

// Mock the logo import
vi.mock('../../images/logo.png', () => ({
  default: 'mocked-default-logo.png',
}));

// Mock Mantine Skeleton component
vi.mock('@mantine/core', async () => {
  return {
    Skeleton: ({ height, width, style, ...props }) => {
      return <div data-testid="skeleton" style={{ height, width, ...style }} {...props} />;
    },
  };
});

describe('LazyLogo', () => {
  let mockFetchLogosByIds;
  let mockStore;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.clearAllTimers();
    vi.useFakeTimers();

    mockFetchLogosByIds = vi.fn().mockResolvedValue(undefined);

    mockStore = {
      logos: {},
      fetchLogosByIds: mockFetchLogosByIds,
      allowLogoRendering: true,
    };

    useLogosStore.mockImplementation((selector) => selector(mockStore));
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  describe('Rendering', () => {
    it('should render image with logo data', () => {
      mockStore.logos = {
        'logo-1': { cache_url: 'https://example.com/logo.png' },
      };

      render(<LazyLogo logoId="logo-1" alt="Test Logo" />);

      const img = screen.getByAltText('Test Logo');
      expect(img).toBeInTheDocument();
      expect(img).toHaveAttribute('src', 'https://example.com/logo.png');
    });

    it('should render with default style', () => {
      mockStore.logos = {
        'logo-1': { cache_url: 'https://example.com/logo.png' },
      };

      render(<LazyLogo logoId="logo-1" />);

      const img = screen.getByAltText('logo');
      expect(img).toHaveStyle({
        maxHeight: '18px',
        maxWidth: '55px',
      });
    });

    it('should render with custom style', () => {
      mockStore.logos = {
        'logo-1': { cache_url: 'https://example.com/logo.png' },
      };

      const customStyle = { maxHeight: 30, maxWidth: 100 };
      render(<LazyLogo logoId="logo-1" style={customStyle} />);

      const img = screen.getByAltText('logo');
      expect(img).toHaveStyle({
        maxHeight: '30px',
        maxWidth: '100px',
      });
    });

    it('should render fallback logo when no logoId provided', () => {
      render(<LazyLogo />);

      const img = screen.getByAltText('logo');
      expect(img).toHaveAttribute('src', 'mocked-default-logo.png');
    });

    it('should pass through additional props to img element', () => {
      mockStore.logos = {
        'logo-1': { cache_url: 'https://example.com/logo.png' },
      };

      render(
        <LazyLogo logoId="logo-1" className="test-class" data-testid="custom-logo" />
      );

      const img = screen.getByTestId('custom-logo');
      expect(img).toHaveClass('test-class');
    });
  });

  describe('Skeleton Loading State', () => {
    it('should show skeleton when logo rendering is not allowed', () => {
      mockStore.allowLogoRendering = false;

      render(<LazyLogo logoId="logo-1" />);

      expect(screen.getByTestId('skeleton')).toBeInTheDocument();
      expect(screen.queryByAltText('logo')).not.toBeInTheDocument();
    });

    it('should show skeleton when logo data is not available', () => {
      mockStore.logos = {};

      render(<LazyLogo logoId="logo-1" />);

      expect(screen.getByTestId('skeleton')).toBeInTheDocument();
    });

    it('should render skeleton with default dimensions', () => {
      mockStore.logos = {};

      render(<LazyLogo logoId="logo-1" />);

      const skeleton = screen.getByTestId('skeleton');
      expect(skeleton).toHaveStyle({
        height: '18px',
        width: '55px',
      });
    });

    it('should render skeleton with custom dimensions', () => {
      mockStore.logos = {};

      const customStyle = { maxHeight: 40, maxWidth: 120 };
      render(<LazyLogo logoId="logo-1" style={customStyle} />);

      const skeleton = screen.getByTestId('skeleton');
      expect(skeleton).toHaveStyle({
        height: '40px',
        width: '120px',
      });
    });

    it('should apply border radius to skeleton', () => {
      mockStore.logos = {};

      render(<LazyLogo logoId="logo-1" />);

      const skeleton = screen.getByTestId('skeleton');
      expect(skeleton).toHaveStyle({
        borderRadius: '4px',
      });
    });
  });

  describe('Logo Fetching', () => {
    it('should fetch logo when logoId is provided and logo data is missing', async () => {
      mockStore.logos = {};

      render(<LazyLogo logoId="logo-1" />);

      vi.advanceTimersByTime(100);

      expect(mockFetchLogosByIds).toHaveBeenCalledWith(['logo-1']);
    });

    it('should not fetch logo when logo data already exists', () => {
      mockStore.logos = {
        'logo-1': { cache_url: 'https://example.com/logo.png' },
      };

      render(<LazyLogo logoId="logo-1" />);

      vi.advanceTimersByTime(100);

      expect(mockFetchLogosByIds).not.toHaveBeenCalled();
    });

    it('should not fetch logo when allowLogoRendering is false', () => {
      mockStore.allowLogoRendering = false;
      mockStore.logos = {};

      render(<LazyLogo logoId="logo-1" />);

      vi.advanceTimersByTime(100);

      expect(mockFetchLogosByIds).not.toHaveBeenCalled();
    });

    it('should not fetch logo when no logoId is provided', () => {
      render(<LazyLogo />);

      vi.advanceTimersByTime(100);

      expect(mockFetchLogosByIds).not.toHaveBeenCalled();
    });

    it('should batch multiple logo requests', async () => {
      mockStore.logos = {};

      render(
        <>
          <LazyLogo logoId="logo-1" />
          <LazyLogo logoId="logo-2" />
          <LazyLogo logoId="logo-3" />
        </>
      );

      vi.advanceTimersByTime(100);

      expect(mockFetchLogosByIds).toHaveBeenCalledTimes(1);
      expect(mockFetchLogosByIds).toHaveBeenCalledWith(
        expect.arrayContaining(['logo-1', 'logo-2', 'logo-3'])
      );
    });

    it('should debounce fetch requests with 100ms delay', async () => {
      mockStore.logos = {};

      render(<LazyLogo logoId="logo-1" />);

      vi.advanceTimersByTime(50);
      expect(mockFetchLogosByIds).not.toHaveBeenCalled();

      vi.advanceTimersByTime(50);
      expect(mockFetchLogosByIds).toHaveBeenCalled();
    });

    it('should handle fetch errors gracefully', async () => {
      mockFetchLogosByIds.mockRejectedValueOnce(new Error('Fetch failed'));
      mockStore.logos = {};

      render(<LazyLogo logoId="logo-1" />);

      vi.advanceTimersByTime(100);
    });

    it('should not fetch same logo twice', async () => {
      mockStore.logos = {};

      const { rerender } = render(<LazyLogo logoId="logo-1" />);

      vi.advanceTimersByTime(100);

      expect(mockFetchLogosByIds).toHaveBeenCalledTimes(1);

      rerender(<LazyLogo logoId="logo-1" />);

      vi.advanceTimersByTime(100);

      expect(mockFetchLogosByIds).toHaveBeenCalledTimes(1);
    });
  });

  describe('Error Handling', () => {
    it('should fallback to default logo on image load error', () => {
      mockStore.logos = {
        'logo-1': { cache_url: 'https://example.com/invalid-logo.png' },
      };

      render(<LazyLogo logoId="logo-1" />);

      const img = screen.getByAltText('logo');

      // Simulate image load error
      img.dispatchEvent(new Event('error'));

      expect(img).toHaveAttribute('src', 'mocked-default-logo.png');
    });

    it('should use custom fallback source on error', () => {
      mockStore.logos = {
        'logo-1': { cache_url: 'https://example.com/invalid-logo.png' },
      };

      const customFallback = 'custom-fallback.png';
      render(<LazyLogo logoId="logo-1" fallbackSrc={customFallback} />);

      const img = screen.getByAltText('logo');

      img.dispatchEvent(new Event('error'));

      expect(img).toHaveAttribute('src', customFallback);
    });

    it('should only set fallback once to prevent infinite error loop', () => {
      mockStore.logos = {
        'logo-1': { cache_url: 'https://example.com/invalid-logo.png' },
      };

      render(<LazyLogo logoId="logo-1" />);

      const img = screen.getByAltText('logo');

      // First error - should set fallback
      img.dispatchEvent(new Event('error'));
      expect(img).toHaveAttribute('src', 'mocked-default-logo.png');

      // Reset src to test second error
      img.src = 'https://example.com/another-invalid.png';

      // Second error - should not change src again
      img.dispatchEvent(new Event('error'));
      expect(img).toHaveAttribute('src', 'mocked-default-logo.png');
    });

    it('should reset error state when logoId changes', async () => {
      mockStore.logos = {
        'logo-1': { cache_url: 'https://example.com/logo1.png' },
        'logo-2': { cache_url: 'https://example.com/logo2.png' },
      };

      const { rerender } = render(<LazyLogo logoId="logo-1" />);

      const img = screen.getByAltText('logo');
      img.dispatchEvent(new Event('error'));

      rerender(<LazyLogo logoId="logo-2" />);

      const newImg = screen.getByAltText('logo');
      expect(newImg).toHaveAttribute('src', 'https://example.com/logo2.png');
    });
  });

  describe('Component Lifecycle', () => {
    it('should cleanup on unmount', () => {
      const { unmount } = render(<LazyLogo logoId="logo-1" />);

      unmount();

      // Should not throw errors after unmount
      vi.advanceTimersByTime(100);
    });

    it('should handle rapid logoId changes', async () => {
      mockStore.logos = {};

      const { rerender } = render(<LazyLogo logoId="logo-1" />);

      rerender(<LazyLogo logoId="logo-2" />);
      rerender(<LazyLogo logoId="logo-3" />);

      vi.advanceTimersByTime(100);

      expect(mockFetchLogosByIds).toHaveBeenCalled();
    });
  });

  describe('Store Integration', () => {
    it('should react to store updates', async () => {
      mockStore.logos = {};

      const { rerender } = render(<LazyLogo logoId="logo-1" />);

      expect(screen.getByTestId('skeleton')).toBeInTheDocument();

      // Update store with logo data
      mockStore.logos = {
        'logo-1': { cache_url: 'https://example.com/logo.png' },
      };

      rerender(<LazyLogo logoId="logo-1" />);

      expect(screen.queryByTestId('skeleton')).not.toBeInTheDocument();
      expect(screen.getByAltText('logo')).toBeInTheDocument();
    });

    it('should handle allowLogoRendering becoming true', async () => {
      mockStore.allowLogoRendering = false;
      mockStore.logos = {};

      const { rerender } = render(<LazyLogo logoId="logo-1" />);

      expect(screen.getByTestId('skeleton')).toBeInTheDocument();
      expect(mockFetchLogosByIds).not.toHaveBeenCalled();

      mockStore.allowLogoRendering = true;
      rerender(<LazyLogo logoId="logo-1" />);

      vi.advanceTimersByTime(100);

      expect(mockFetchLogosByIds).toHaveBeenCalledWith(['logo-1']);
    });
  });
});
