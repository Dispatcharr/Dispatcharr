import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import HourTimeline from '../HourTimeline';
import { format } from '../../utils/dateTimeUtils';
import { HOUR_WIDTH } from '../../utils/guideUtils';

// Mock date utilities
vi.mock('../../utils/dateTimeUtils', () => ({
  format: vi.fn((date, formatStr) => {
    if (!formatStr) return date.toISOString();
    return formatStr === 'h:mm a' ? '12:00 PM' : 'Jan 1';
  }),
}));

// Mock Mantine components
vi.mock('@mantine/core', async () => {
  return {
    Box: ({ children, ...props }) => <div {...props}>{children}</div>,
    Text: ({ children, ...props }) => <span {...props}>{children}</span>,
  };
});

describe('HourTimeline', () => {
  const mockTime1 = new Date('2024-01-01T10:00:00Z');
  const mockTime2 = new Date('2024-01-01T11:00:00Z');
  const mockTime3 = new Date('2024-01-02T00:00:00Z');

  const mockHourTimeline = [
    { time: mockTime1, isNewDay: false },
    { time: mockTime2, isNewDay: false },
  ];

  const mockTimeFormat = 'h:mm a';
  const mockFormatDayLabel = vi.fn((time) => 'Mon');
  const mockHandleTimeClick = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Rendering', () => {
    it('should render all hour blocks', () => {
      render(
        <HourTimeline
          hourTimeline={mockHourTimeline}
          timeFormat={mockTimeFormat}
          formatDayLabel={mockFormatDayLabel}
          handleTimeClick={mockHandleTimeClick}
        />
      );

      expect(mockFormatDayLabel).toHaveBeenCalledTimes(2);
      expect(format).toHaveBeenCalledWith(mockTime1, mockTimeFormat);
      expect(format).toHaveBeenCalledWith(mockTime2, mockTimeFormat);
    });

    it('should render empty when hourTimeline is empty', () => {
      const { container } = render(
        <HourTimeline
          hourTimeline={[]}
          timeFormat={mockTimeFormat}
          formatDayLabel={mockFormatDayLabel}
          handleTimeClick={mockHandleTimeClick}
        />
      );

      expect(container.firstChild).toBeNull();
    });

    it('should render formatted time labels', () => {
      render(
        <HourTimeline
          hourTimeline={mockHourTimeline}
          timeFormat={mockTimeFormat}
          formatDayLabel={mockFormatDayLabel}
          handleTimeClick={mockHandleTimeClick}
        />
      );

      const timeLabels = screen.getAllByText('12:00 PM');
      expect(timeLabels.length).toBe(2);
    });

    it('should render day labels', () => {
      render(
        <HourTimeline
          hourTimeline={mockHourTimeline}
          timeFormat={mockTimeFormat}
          formatDayLabel={mockFormatDayLabel}
          handleTimeClick={mockHandleTimeClick}
        />
      );

      const dayLabels = screen.getAllByText('Mon');
      expect(dayLabels.length).toBe(2);
    });
  });

  describe('HourBlock Styling', () => {
    it('should apply correct width and height to hour blocks', () => {
      const { container } = render(
        <HourTimeline
          hourTimeline={mockHourTimeline}
          timeFormat={mockTimeFormat}
          formatDayLabel={mockFormatDayLabel}
          handleTimeClick={mockHandleTimeClick}
        />
      );

      const hourBlocks = container.querySelectorAll(
        '[style*="cursor: pointer"]'
      );
      hourBlocks.forEach((block) => {
        expect(block).toHaveAttribute('w', `${HOUR_WIDTH}`);
        expect(block).toHaveAttribute('h', '40px');
        expect(block).toHaveAttribute('pos', 'relative');
      });
    });

    it('should apply default styling for non-new-day blocks', () => {
      const { container } = render(
        <HourTimeline
          hourTimeline={mockHourTimeline}
          timeFormat={mockTimeFormat}
          formatDayLabel={mockFormatDayLabel}
          handleTimeClick={mockHandleTimeClick}
        />
      );

      const hourBlocks = container.querySelectorAll(
        '[style*="cursor: pointer"]'
      );
      expect(hourBlocks[0]).toHaveStyle({
        backgroundColor: '#1B2421',
      });
    });

    it('should apply special styling for new day blocks', () => {
      const newDayTimeline = [{ time: mockTime3, isNewDay: true }];

      const { container } = render(
        <HourTimeline
          hourTimeline={newDayTimeline}
          timeFormat={mockTimeFormat}
          formatDayLabel={mockFormatDayLabel}
          handleTimeClick={mockHandleTimeClick}
        />
      );

      const hourBlock = container.querySelector('[style*="cursor: pointer"]');
      expect(hourBlock).toHaveStyle({
        borderLeft: '2px solid #3BA882',
        backgroundColor: '#1E2A27',
      });
    });

    it('should apply bold font weight to day label on new day', () => {
      const newDayTimeline = [{ time: mockTime3, isNewDay: true }];

      const { container } = render(
        <HourTimeline
          hourTimeline={newDayTimeline}
          timeFormat={mockTimeFormat}
          formatDayLabel={mockFormatDayLabel}
          handleTimeClick={mockHandleTimeClick}
        />
      );

      const dayLabel = screen.getByText('Mon');
      expect(dayLabel).toHaveAttribute('fw', '600');
      expect(dayLabel).toHaveAttribute('c', '#3BA882');
    });

    it('should apply normal font weight to day label on regular day', () => {
      const { container } = render(
        <HourTimeline
          hourTimeline={mockHourTimeline}
          timeFormat={mockTimeFormat}
          formatDayLabel={mockFormatDayLabel}
          handleTimeClick={mockHandleTimeClick}
        />
      );

      const dayLabels = screen.getAllByText('Mon');
      expect(dayLabels[0]).toHaveAttribute('fw', '400');
    });
  });

  describe('Quarter Hour Markers', () => {
    it('should render quarter hour markers', () => {
      const { container } = render(
        <HourTimeline
          hourTimeline={[mockHourTimeline[0]]}
          timeFormat={mockTimeFormat}
          formatDayLabel={mockFormatDayLabel}
          handleTimeClick={mockHandleTimeClick}
        />
      );

      const markers = container.querySelectorAll(
        '[style*="background-color: rgb(113, 128, 150);"]'
      );
      expect(markers.length).toBe(3); // 15, 30, 45 minute markers
    });

    it('should position quarter hour markers correctly', () => {
      const { container } = render(
        <HourTimeline
          hourTimeline={[mockHourTimeline[0]]}
          timeFormat={mockTimeFormat}
          formatDayLabel={mockFormatDayLabel}
          handleTimeClick={mockHandleTimeClick}
        />
      );

      const markers = container.querySelectorAll(
        '[style*="backgroundColor: #718096"]'
      );
      const positions = ['25%', '50%', '75%'];

      markers.forEach((marker, index) => {
        expect(marker).toHaveStyle({
          left: positions[index],
          width: '1px',
          height: '8px',
          position: 'absolute',
          bottom: '0px',
        });
      });
    });
  });

  describe('Click Interactions', () => {
    it('should call handleTimeClick when hour block is clicked', () => {
      const { container } = render(
        <HourTimeline
          hourTimeline={mockHourTimeline}
          timeFormat={mockTimeFormat}
          formatDayLabel={mockFormatDayLabel}
          handleTimeClick={mockHandleTimeClick}
        />
      );

      const hourBlocks = container.querySelectorAll(
        '[style*="cursor: pointer"]'
      );
      fireEvent.click(hourBlocks[0]);

      expect(mockHandleTimeClick).toHaveBeenCalledWith(
        mockTime1,
        expect.any(Object)
      );
    });

    it('should call handleTimeClick with correct time for each block', () => {
      const { container } = render(
        <HourTimeline
          hourTimeline={mockHourTimeline}
          timeFormat={mockTimeFormat}
          formatDayLabel={mockFormatDayLabel}
          handleTimeClick={mockHandleTimeClick}
        />
      );

      const hourBlocks = container.querySelectorAll(
        '[style*="cursor: pointer"]'
      );

      fireEvent.click(hourBlocks[0]);
      expect(mockHandleTimeClick).toHaveBeenCalledWith(
        mockTime1,
        expect.any(Object)
      );

      fireEvent.click(hourBlocks[1]);
      expect(mockHandleTimeClick).toHaveBeenCalledWith(
        mockTime2,
        expect.any(Object)
      );
    });
  });

  describe('Component Keys', () => {
    it('should use formatted time as key for each hour block', () => {
      format.mockImplementation((date) => date.toISOString());

      const { container } = render(
        <HourTimeline
          hourTimeline={mockHourTimeline}
          timeFormat={mockTimeFormat}
          formatDayLabel={mockFormatDayLabel}
          handleTimeClick={mockHandleTimeClick}
        />
      );

      expect(format).toHaveBeenCalledWith(mockTime1);
      expect(format).toHaveBeenCalledWith(mockTime2);
    });
  });

  describe('Time Label Positioning', () => {
    it('should position time label correctly', () => {
      const { container } = render(
        <HourTimeline
          hourTimeline={[mockHourTimeline[0]]}
          timeFormat={mockTimeFormat}
          formatDayLabel={mockFormatDayLabel}
          handleTimeClick={mockHandleTimeClick}
        />
      );

      const timeLabel = container.querySelector('[pos*="absolute"][top*="8"]');
      expect(timeLabel).toHaveAttribute('left', '4');
    });
  });

  describe('Visual Separators', () => {
    it('should render left separator box', () => {
      const { container } = render(
        <HourTimeline
          hourTimeline={[mockHourTimeline[0]]}
          timeFormat={mockTimeFormat}
          formatDayLabel={mockFormatDayLabel}
          handleTimeClick={mockHandleTimeClick}
        />
      );

      const separator = container.querySelector('[w*="1px"][left*="0"]');
      expect(separator).toHaveAttribute('pos', 'absolute');
      expect(separator).toHaveAttribute('top', '0');
      expect(separator).toHaveAttribute('bottom', '0');
    });
  });
});
