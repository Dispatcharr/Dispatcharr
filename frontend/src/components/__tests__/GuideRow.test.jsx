import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import GuideRow from '../GuideRow';
import {
  CHANNEL_WIDTH,
  HOUR_WIDTH,
  PROGRAM_HEIGHT,
} from '../../utils/guideUtils';

// Mock logo import
vi.mock('../../images/logo.png', () => ({
  default: 'mocked-logo.png',
}));

// Mock lucide-react icons
vi.mock('lucide-react', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    Play: (props) => <div data-testid="play-icon" {...props} />,
  };
});

// Mock Mantine components
vi.mock('@mantine/core', async () => {
  return {
    Box: ({ children, ...props }) => <div {...props}>{children}</div>,
    Flex: ({ children, ...props }) => <div {...props}>{children}</div>,
    Text: ({ children, ...props }) => <div {...props}>{children}</div>,
    Tooltip: ({ children }) => children,
  };
});

// Helper function to create programs at specific times
const createProgramAtTime = (id, startHour, durationMinutes) => {
  const timelineStart = new Date('2024-01-01T00:00:00Z');
  const startMs = timelineStart.getTime() + startHour * 60 * 60 * 1000;
  return {
    id,
    title: `Program ${id}`,
    startMs,
    endMs: startMs + durationMinutes * 60 * 1000,
  };
};

describe('GuideRow', () => {
  const mockChannel = {
    id: 'channel-1',
    name: 'Test Channel',
    channel_number: '101',
    logo_id: 'logo-1',
  };

  const mockProgram = {
    id: 'program-1',
    title: 'Test Program',
    start_time: '2024-01-01T10:00:00Z',
    end_time: '2024-01-01T11:00:00Z',
  };

  const mockLogos = {
    'logo-1': {
      cache_url: 'https://example.com/logo.png',
    },
  };

  const mockData = {
    filteredChannels: [mockChannel],
    programsByChannelId: new Map([[mockChannel.id, [mockProgram]]]),
    rowHeights: {},
    logos: mockLogos,
    hoveredChannelId: null,
    setHoveredChannelId: vi.fn(),
    renderProgram: vi.fn((program) => (
      <div key={program.id} data-testid={`program-${program.id}`}>
        {program.title}
      </div>
    )),
    handleLogoClick: vi.fn(),
    contentWidth: 1920,
    guideScrollLeftRef: { current: 0 },
    viewportWidth: 1920,
    timelineStartMs: new Date('2024-01-01T00:00:00Z').getTime(),
  };

  const mockStyle = {
    position: 'absolute',
    left: 0,
    top: 0,
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Rendering', () => {
    it('should render channel row with channel information', () => {
      render(<GuideRow index={0} style={mockStyle} data={mockData} />);

      expect(screen.getByTestId('guide-row')).toBeInTheDocument();
      expect(screen.getByAltText('Test Channel')).toBeInTheDocument();
      expect(screen.getByText('101')).toBeInTheDocument();
    });

    it('should return null when channel does not exist', () => {
      const data = { ...mockData, filteredChannels: [] };
      const { container } = render(
        <GuideRow index={0} style={mockStyle} data={data} />
      );

      expect(container.firstChild).toBeNull();
    });

    it('should use default logo when channel logo is not available', () => {
      const channelWithoutLogo = { ...mockChannel, logo_id: 'missing-logo' };
      const data = {
        ...mockData,
        filteredChannels: [channelWithoutLogo],
      };

      render(<GuideRow index={0} style={mockStyle} data={data} />);

      const img = screen.getByAltText('Test Channel');
      expect(img).toHaveAttribute('src', 'mocked-logo.png');
    });

    it('should display channel number or dash if missing', () => {
      const channelWithoutNumber = { ...mockChannel, channel_number: null };
      const data = {
        ...mockData,
        filteredChannels: [channelWithoutNumber],
      };

      render(<GuideRow index={0} style={mockStyle} data={data} />);

      expect(screen.getByText('-')).toBeInTheDocument();
    });
  });

  describe('Row Height Calculation', () => {
    it('should use default PROGRAM_HEIGHT when no expanded program', () => {
      render(<GuideRow index={0} style={mockStyle} data={mockData} />);

      const row = screen.getByTestId('guide-row');
      expect(row).toHaveStyle({ height: `${PROGRAM_HEIGHT}px` });
    });

    it('should use pre-calculated row height from rowHeights array', () => {
      const customHeight = 150;
      const data = {
        ...mockData,
        rowHeights: { 0: customHeight },
      };

      render(<GuideRow index={0} style={mockStyle} data={data} />);

      const row = screen.getByTestId('guide-row');
      expect(row).toHaveStyle({ height: `${customHeight}px` });
    });
  });

  describe('Programs Rendering', () => {
    it('should render programs when channel has programs', () => {
      // Create program at hour 0 (definitely within viewport at scrollLeft 0)
      const visibleProgram = createProgramAtTime('program-1', 0, 60);

      const data = {
        ...mockData,
        programsByChannelId: new Map([[mockChannel.id, [visibleProgram]]]),
      };

      render(<GuideRow index={0} style={mockStyle} data={data} />);

      expect(screen.getByTestId('program-program-1')).toBeInTheDocument();
      expect(mockData.renderProgram).toHaveBeenCalledWith(
        visibleProgram,
        undefined,
        mockChannel
      );
    });

    it('should render multiple programs', () => {
      const programs = [
        createProgramAtTime('prog-1', 0, 60),
        createProgramAtTime('prog-2', 1, 30),
      ];

      const data = {
        ...mockData,
        programsByChannelId: new Map([[mockChannel.id, programs]]),
      };

      render(<GuideRow index={0} style={mockStyle} data={data} />);

      expect(screen.getByTestId('program-prog-1')).toBeInTheDocument();
      expect(screen.getByTestId('program-prog-2')).toBeInTheDocument();
    });

    it('should render placeholder when channel has no programs', () => {
      const data = {
        ...mockData,
        programsByChannelId: new Map([[mockChannel.id, []]]),
      };

      render(<GuideRow index={0} style={mockStyle} data={data} />);

      const placeholders = screen.getAllByText('No program data');
      expect(placeholders.length).toBeGreaterThan(0);
    });

    it('should render placeholder when programsByChannelId does not contain channel', () => {
      const data = {
        ...mockData,
        programsByChannelId: new Map(),
      };

      render(<GuideRow index={0} style={mockStyle} data={data} />);

      const placeholders = screen.getAllByText('No program data');
      expect(placeholders.length).toBeGreaterThan(0);
    });

    it('should position placeholder programs correctly', () => {
      const data = {
        ...mockData,
        programsByChannelId: new Map([[mockChannel.id, []]]),
      };

      const { container } = render(
        <GuideRow index={0} style={mockStyle} data={data} />
      );

      const placeholders = container.querySelectorAll('[pos*="absolute"]');
      const filteredPlaceholders = Array.from(placeholders).filter((el) =>
        el.textContent.includes('No program data')
      );

      filteredPlaceholders.forEach((placeholder, index) => {
        expect(placeholder).toHaveAttribute(
          'left',
          `${index * (HOUR_WIDTH * 2)}`
        );
        expect(placeholder).toHaveAttribute('w', `${HOUR_WIDTH * 2}`);
      });
    });
  });

  describe('Channel Logo Interactions', () => {
    it('should call handleLogoClick when logo is clicked', () => {
      render(<GuideRow index={0} style={mockStyle} data={mockData} />);

      const logo = screen.getByAltText('Test Channel').closest('.channel-logo');
      fireEvent.click(logo);

      expect(mockData.handleLogoClick).toHaveBeenCalledWith(
        mockChannel,
        expect.any(Object)
      );
    });

    it('should show play icon on hover', () => {
      render(<GuideRow index={0} style={mockStyle} data={mockData} />);

      const logo = screen.getByAltText('Test Channel').closest('.channel-logo');
      fireEvent.mouseEnter(logo);

      expect(screen.getByTestId('play-icon')).toBeInTheDocument();
    });

    it('should not show play icon when not hovering', () => {
      render(<GuideRow index={0} style={mockStyle} data={mockData} />);

      expect(screen.queryByTestId('play-icon')).not.toBeInTheDocument();
    });
  });

  describe('Layout and Styling', () => {
    it('should set correct channel logo width', () => {
      const { container } = render(
        <GuideRow index={0} style={mockStyle} data={mockData} />
      );

      const logoContainer = container.querySelector('.channel-logo');
      expect(logoContainer).toHaveAttribute('w', `${CHANNEL_WIDTH}`);
      expect(logoContainer).toHaveAttribute('miw', `${CHANNEL_WIDTH}`);
    });

    it('should apply content width to row', () => {
      const customWidth = 2400;
      const data = {
        ...mockData,
        contentWidth: customWidth,
      };

      render(<GuideRow index={0} style={mockStyle} data={data} />);

      const row = screen.getByTestId('guide-row');
      expect(row).toHaveStyle({ width: `${customWidth}px` });
    });

    it('should adjust logo image container height based on row height', () => {
      const customHeight = 200;
      const data = {
        ...mockData,
        rowHeights: { 0: customHeight },
      };

      const { container } = render(
        <GuideRow index={0} style={mockStyle} data={data} />
      );

      const imageContainer = container.querySelector('img').parentElement;
      expect(imageContainer).toHaveAttribute('h', `${customHeight - 12}px`);
    });
  });

  describe('Horizontal Viewport Culling', () => {
    it('should only render programs visible in viewport', () => {
      const programs = [
        createProgramAtTime('prog-1', 0, 60), // Hour 0
        createProgramAtTime('prog-2', 6, 60), // Hour 6
        createProgramAtTime('prog-3', 12, 60), // Hour 12
        createProgramAtTime('prog-4', 18, 60), // Hour 18
      ];

      const data = {
        ...mockData,
        programsByChannelId: new Map([[mockChannel.id, programs]]),
        guideScrollLeftRef: { current: HOUR_WIDTH * 6 }, // Scroll to hour 6
        viewportWidth: HOUR_WIDTH * 4, // Show 4 hours
        timelineStartMs: new Date('2024-01-01T00:00:00Z').getTime(),
      };

      render(<GuideRow index={0} style={mockStyle} data={data} />);

      // Program at hour 6 should be visible
      expect(screen.getByTestId('program-prog-2')).toBeInTheDocument();

      // Programs outside viewport + buffer should not be rendered
      expect(mockData.renderProgram).toHaveBeenCalledTimes(1);
    });

    it('should render programs within buffer zone', () => {
      const programs = [
        createProgramAtTime('prog-1', 0, 60),
        createProgramAtTime('prog-2', 1, 60),
      ];

      const data = {
        ...mockData,
        programsByChannelId: new Map([[mockChannel.id, programs]]),
        guideScrollLeftRef: { current: HOUR_WIDTH * 2 },
        viewportWidth: HOUR_WIDTH * 2,
        timelineStartMs: new Date('2024-01-01T00:00:00Z').getTime(),
      };

      render(<GuideRow index={0} style={mockStyle} data={data} />);

      // Programs within H_BUFFER (600px) should be rendered
      const renderedPrograms = mockData.renderProgram.mock.calls.map(
        (call) => call[0]
      );

      expect(renderedPrograms.length).toBeGreaterThan(0);
    });

    it('should not render programs completely outside viewport and buffer', () => {
      const programs = [
        createProgramAtTime('prog-far-left', 0, 60),
        createProgramAtTime('prog-visible', 10, 60),
        createProgramAtTime('prog-far-right', 22, 60),
      ];

      const data = {
        ...mockData,
        programsByChannelId: new Map([[mockChannel.id, programs]]),
        guideScrollLeftRef: { current: HOUR_WIDTH * 10 },
        viewportWidth: HOUR_WIDTH * 2,
        timelineStartMs: new Date('2024-01-01T00:00:00Z').getTime(),
      };

      render(<GuideRow index={0} style={mockStyle} data={data} />);

      const renderedPrograms = mockData.renderProgram.mock.calls.map(
        (call) => call[0].id
      );

      // Only visible program should be rendered
      expect(renderedPrograms).toContain('prog-visible');
      expect(renderedPrograms).not.toContain('prog-far-left');
      expect(renderedPrograms).not.toContain('prog-far-right');
    });

    it('should handle edge case where program spans viewport boundary', () => {
      const programs = [
        createProgramAtTime('prog-spanning', 5, 180), // 3-hour program
      ];

      const data = {
        ...mockData,
        programsByChannelId: new Map([[mockChannel.id, programs]]),
        guideScrollLeftRef: { current: HOUR_WIDTH * 6 },
        viewportWidth: HOUR_WIDTH * 2,
        timelineStartMs: new Date('2024-01-01T00:00:00Z').getTime(),
      };

      render(<GuideRow index={0} style={mockStyle} data={data} />);

      // Program spanning viewport should be visible
      expect(screen.getByTestId('program-prog-spanning')).toBeInTheDocument();
    });

    it('should update visible programs when scroll position changes', () => {
      const programs = [
        createProgramAtTime('prog-1', 0, 60),
        createProgramAtTime('prog-2', 12, 60),
      ];

      const scrollRef = { current: 0 };
      const data = {
        ...mockData,
        programsByChannelId: new Map([[mockChannel.id, programs]]),
        guideScrollLeftRef: scrollRef,
        viewportWidth: HOUR_WIDTH * 4,
        timelineStartMs: new Date('2024-01-01T00:00:00Z').getTime(),
      };

      const { rerender } = render(
        <GuideRow index={0} style={mockStyle} data={data} />
      );

      const initialCalls = mockData.renderProgram.mock.calls.length;

      // Scroll to different position
      scrollRef.current = HOUR_WIDTH * 12;
      const newData = { ...data, guideScrollLeftRef: scrollRef };

      rerender(<GuideRow index={0} style={mockStyle} data={newData} />);

      // Different programs should be rendered
      expect(mockData.renderProgram.mock.calls.length).toBeGreaterThan(
        initialCalls
      );
    });
  });

  describe('Placeholder Culling', () => {
    it('should only render placeholders visible in viewport', () => {
      const data = {
        ...mockData,
        programsByChannelId: new Map([[mockChannel.id, []]]),
        guideScrollLeftRef: { current: HOUR_WIDTH * 10 },
        viewportWidth: HOUR_WIDTH * 4,
        timelineStartMs: new Date('2024-01-01T00:00:00Z').getTime(),
      };

      const { container } = render(
        <GuideRow index={0} style={mockStyle} data={data} />
      );

      const visiblePlaceholders = screen.getAllByText('No program data');

      // Should render fewer than total placeholders due to culling
      expect(visiblePlaceholders.length).toBeLessThan(Math.ceil(24 / 2));
      expect(visiblePlaceholders.length).toBeGreaterThan(0);
    });

    it('should not render placeholders outside viewport', () => {
      const data = {
        ...mockData,
        programsByChannelId: new Map([[mockChannel.id, []]]),
        guideScrollLeftRef: { current: HOUR_WIDTH * 20 },
        viewportWidth: HOUR_WIDTH * 2,
        timelineStartMs: new Date('2024-01-01T00:00:00Z').getTime(),
      };

      const { container } = render(
        <GuideRow index={0} style={mockStyle} data={data} />
      );

      const visiblePlaceholders = screen.getAllByText('No program data');

      // Near the end of timeline, should show fewer placeholders
      expect(visiblePlaceholders.length).toBeGreaterThan(0);
      expect(visiblePlaceholders.length).toBeLessThanOrEqual(3);
    });
  });

  describe('Hover State Management', () => {
    it('should show play icon on mouse enter', () => {
      render(<GuideRow index={0} style={mockStyle} data={mockData} />);

      const logoContainer = screen
        .getByAltText('Test Channel')
        .closest('.channel-logo');

      expect(screen.queryByTestId('play-icon')).not.toBeInTheDocument();

      fireEvent.mouseEnter(logoContainer);

      expect(screen.getByTestId('play-icon')).toBeInTheDocument();
    });

    it('should hide play icon on mouse leave', () => {
      render(<GuideRow index={0} style={mockStyle} data={mockData} />);

      const logoContainer = screen
        .getByAltText('Test Channel')
        .closest('.channel-logo');

      fireEvent.mouseEnter(logoContainer);
      expect(screen.getByTestId('play-icon')).toBeInTheDocument();

      fireEvent.mouseLeave(logoContainer);
      expect(screen.queryByTestId('play-icon')).not.toBeInTheDocument();
    });

    it('should maintain hover state independently per row', () => {
      const data = {
        ...mockData,
        filteredChannels: [
          mockChannel,
          { ...mockChannel, id: 'channel-2', name: 'Channel 2' },
        ],
      };

      // Render both rows separately
      const { container: container1 } = render(
        <GuideRow index={0} style={mockStyle} data={data} />
      );
      const { container: container2 } = render(
        <GuideRow
          index={1}
          style={{ ...mockStyle, top: PROGRAM_HEIGHT }}
          data={data}
        />
      );

      // Hover over first row
      const logo1 = container1.querySelector('.channel-logo');
      fireEvent.mouseEnter(logo1);

      // First row should show play icon
      expect(
        container1.querySelector('[data-testid="play-icon"]')
      ).toBeInTheDocument();

      // Second row should not show play icon
      expect(
        container2.querySelector('[data-testid="play-icon"]')
      ).not.toBeInTheDocument();
    });
  });

  describe('Program Time Positioning', () => {
    const createTimedProgram = (startHour, durationMinutes) => {
      const timelineStart = new Date('2024-01-01T00:00:00Z');
      const startMs = timelineStart.getTime() + startHour * 60 * 60 * 1000;
      return {
        id: `program-${startHour}`,
        title: `Program at ${startHour}h`,
        startMs,
        endMs: startMs + durationMinutes * 60 * 1000,
      };
    };

    it('should calculate correct viewport boundaries', () => {
      const programs = [createTimedProgram(6, 60), createTimedProgram(12, 60)];

      const data = {
        ...mockData,
        programsByChannelId: new Map([[mockChannel.id, programs]]),
        guideScrollLeftRef: { current: HOUR_WIDTH * 8 },
        viewportWidth: HOUR_WIDTH * 4,
        timelineStartMs: new Date('2024-01-01T00:00:00Z').getTime(),
      };

      render(<GuideRow index={0} style={mockStyle} data={data} />);

      // Both programs should be rendered since they're within viewport range
      expect(mockData.renderProgram).toHaveBeenCalled();
    });

    it('should handle programs at timeline boundaries', () => {
      const programs = [
        createTimedProgram(0, 60), // Start of timeline
        createTimedProgram(23, 60), // End of timeline
      ];

      const data = {
        ...mockData,
        programsByChannelId: new Map([[mockChannel.id, programs]]),
        guideScrollLeftRef: { current: 0 },
        viewportWidth: HOUR_WIDTH * 24,
        timelineStartMs: new Date('2024-01-01T00:00:00Z').getTime(),
      };

      render(<GuideRow index={0} style={mockStyle} data={data} />);

      expect(screen.getByText('Program at 0h')).toBeInTheDocument();
      expect(screen.getByText('Program at 23h')).toBeInTheDocument();
    });

    it('should handle very short programs', () => {
      const programs = [
        createTimedProgram(12, 5), // 5-minute program
      ];

      const data = {
        ...mockData,
        programsByChannelId: new Map([[mockChannel.id, programs]]),
        guideScrollLeftRef: { current: HOUR_WIDTH * 12 },
        viewportWidth: HOUR_WIDTH * 2,
        timelineStartMs: new Date('2024-01-01T00:00:00Z').getTime(),
      };

      render(<GuideRow index={0} style={mockStyle} data={data} />);

      expect(screen.getByTestId('program-program-12')).toBeInTheDocument();
    });

    it('should handle very long programs', () => {
      const programs = [
        createTimedProgram(6, 360), // 6-hour program
      ];

      const data = {
        ...mockData,
        programsByChannelId: new Map([[mockChannel.id, programs]]),
        guideScrollLeftRef: { current: HOUR_WIDTH * 8 },
        viewportWidth: HOUR_WIDTH * 2,
        timelineStartMs: new Date('2024-01-01T00:00:00Z').getTime(),
      };

      render(<GuideRow index={0} style={mockStyle} data={data} />);

      // Long program spanning viewport should be visible
      expect(screen.getByTestId('program-program-6')).toBeInTheDocument();
    });
  });

  describe('Edge Cases', () => {
    it('should handle empty programsByChannelId gracefully', () => {
      const data = {
        ...mockData,
        programsByChannelId: new Map(),
        guideScrollLeftRef: { current: 0 },
        viewportWidth: HOUR_WIDTH * 4,
        timelineStartMs: new Date('2024-01-01T00:00:00Z').getTime(),
      };

      render(<GuideRow index={0} style={mockStyle} data={data} />);

      expect(screen.getAllByText('No program data').length).toBeGreaterThan(0);
    });

    it('should handle zero viewport width', () => {
      const programs = [mockProgram];

      const data = {
        ...mockData,
        programsByChannelId: new Map([[mockChannel.id, programs]]),
        guideScrollLeftRef: { current: 0 },
        viewportWidth: 0,
        timelineStartMs: new Date('2024-01-01T00:00:00Z').getTime(),
      };

      render(<GuideRow index={0} style={mockStyle} data={data} />);

      // Should still render due to buffer
      expect(screen.getByTestId('guide-row')).toBeInTheDocument();
    });

    it('should handle negative scroll position', () => {
      const programs = [createProgramAtTime('prog-1', 0, 60)];

      const data = {
        ...mockData,
        programsByChannelId: new Map([[mockChannel.id, programs]]),
        guideScrollLeftRef: { current: -100 },
        viewportWidth: HOUR_WIDTH * 4,
        timelineStartMs: new Date('2024-01-01T00:00:00Z').getTime(),
      };

      render(<GuideRow index={0} style={mockStyle} data={data} />);

      expect(screen.getByTestId('guide-row')).toBeInTheDocument();
    });

    it('should handle row index out of bounds', () => {
      const data = {
        ...mockData,
        filteredChannels: [mockChannel],
      };

      const { container } = render(
        <GuideRow index={999} style={mockStyle} data={data} />
      );

      expect(container.firstChild).toBeNull();
    });

    it('should memoize component to prevent unnecessary re-renders', () => {
      const { rerender } = render(
        <GuideRow index={0} style={mockStyle} data={mockData} />
      );

      const renderCount = mockData.renderProgram.mock.calls.length;

      // Re-render with same props
      rerender(<GuideRow index={0} style={mockStyle} data={mockData} />);

      // Should not cause additional renders due to React.memo
      expect(mockData.renderProgram.mock.calls.length).toBe(renderCount);
    });
  });
});
