import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import GuideRow from '../GuideRow';
import {
  CHANNEL_WIDTH,
  EXPANDED_PROGRAM_HEIGHT,
  HOUR_WIDTH,
  PROGRAM_HEIGHT,
} from '../../pages/guideUtils';

// Mock logo import
vi.mock('../../images/logo.png', () => ({
  default: 'mocked-logo.png',
}));

// Mock lucide-react icons
vi.mock('lucide-react', () => ({
  Play: (props) => <div data-testid="play-icon" {...props} />,
}));

// Mock Mantine components
vi.mock('@mantine/core', async () => {
  return {
    Box: ({ children, ...props }) => <div {...props}>{children}</div>,
    Flex: ({ children, ...props }) => <div {...props}>{children}</div>,
    Text: ({ children, ...props }) => <div {...props}>{children}</div>,
  };
});

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
    expandedProgramId: null,
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
      render(
        <GuideRow index={0} style={mockStyle} data={mockData} />
      );

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
      render(
        <GuideRow index={0} style={mockStyle} data={mockData} />
      );

      const row = screen.getByTestId('guide-row');
      expect(row).toHaveStyle({ height: `${PROGRAM_HEIGHT}px` });
    });

    it('should use EXPANDED_PROGRAM_HEIGHT when program is expanded', () => {
      const data = {
        ...mockData,
        expandedProgramId: mockProgram.id,
      };

      render(<GuideRow index={0} style={mockStyle} data={data} />);

      const row = screen.getByTestId('guide-row');
      expect(row).toHaveStyle({ height: `${EXPANDED_PROGRAM_HEIGHT}px` });
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
      render(
        <GuideRow index={0} style={mockStyle} data={mockData} />
      );

      expect(screen.getByTestId(`program-${mockProgram.id}`)).toBeInTheDocument();
      expect(screen.getByText('Test Program')).toBeInTheDocument();
      expect(mockData.renderProgram).toHaveBeenCalledWith(
        mockProgram,
        undefined,
        mockChannel
      );
    });

    it('should render multiple programs', () => {
      const programs = [
        mockProgram,
        { ...mockProgram, id: 'program-2', title: 'Another Program' },
      ];
      const data = {
        ...mockData,
        programsByChannelId: new Map([[mockChannel.id, programs]]),
      };

      render(<GuideRow index={0} style={mockStyle} data={data} />);

      expect(screen.getByText('Test Program')).toBeInTheDocument();
      expect(screen.getByText('Another Program')).toBeInTheDocument();
      expect(mockData.renderProgram).toHaveBeenCalledTimes(2);
    });

    it('should render placeholder when channel has no programs', () => {
      const data = {
        ...mockData,
        programsByChannelId: new Map([[mockChannel.id, []]]),
      };

      render(<GuideRow index={0} style={mockStyle} data={data} />);

      const placeholders = screen.getAllByText('No program data');
      expect(placeholders.length).toBe(Math.ceil(24 / 2));
    });

    it('should render placeholder when programsByChannelId does not contain channel', () => {
      const data = {
        ...mockData,
        programsByChannelId: new Map(),
      };

      render(<GuideRow index={0} style={mockStyle} data={data} />);

      const placeholders = screen.getAllByText('No program data');
      expect(placeholders.length).toBe(Math.ceil(24 / 2));
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
      const filteredPlaceholders = Array.from(placeholders).filter(el =>
        el.textContent.includes('No program data')
      );

      filteredPlaceholders.forEach((placeholder, index) => {
        expect(placeholder).toHaveAttribute('left', `${index * (HOUR_WIDTH * 2)}`);
        expect(placeholder).toHaveAttribute('w', `${HOUR_WIDTH * 2}`);
      });
    });
  });

  describe('Channel Logo Interactions', () => {
    it('should call handleLogoClick when logo is clicked', () => {
      render(
        <GuideRow index={0} style={mockStyle} data={mockData} />
      );

      const logo = screen.getByAltText('Test Channel').closest('.channel-logo');
      fireEvent.click(logo);

      expect(mockData.handleLogoClick).toHaveBeenCalledWith(
        mockChannel,
        expect.any(Object)
      );
    });

    it('should show play icon on hover', () => {
      const data = {
        ...mockData,
        hoveredChannelId: mockChannel.id,
      };

      render(<GuideRow index={0} style={mockStyle} data={data} />);

      expect(screen.getByTestId('play-icon')).toBeInTheDocument();
    });

    it('should not show play icon when not hovering', () => {
      render(
        <GuideRow index={0} style={mockStyle} data={mockData} />
      );

      expect(screen.queryByTestId('play-icon')).not.toBeInTheDocument();
    });

    it('should call setHoveredChannelId on mouse enter', () => {
      render(
        <GuideRow index={0} style={mockStyle} data={mockData} />
      );

      const logo = screen.getByAltText('Test Channel').closest('.channel-logo');
      fireEvent.mouseEnter(logo);

      expect(mockData.setHoveredChannelId).toHaveBeenCalledWith(mockChannel.id);
    });

    it('should call setHoveredChannelId with null on mouse leave', () => {
      render(
        <GuideRow index={0} style={mockStyle} data={mockData} />
      );

      const logo = screen.getByAltText('Test Channel').closest('.channel-logo');
      fireEvent.mouseLeave(logo);

      expect(mockData.setHoveredChannelId).toHaveBeenCalledWith(null);
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
      expect(imageContainer).toHaveAttribute('h', `${customHeight - 32}px`);
    });
  });
});
