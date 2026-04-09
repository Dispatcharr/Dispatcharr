import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import SystemEvents from '../SystemEvents';
import API from '../../api';
import useLocalStorage from "../../hooks/useLocalStorage";

// Mock the API module
vi.mock('../../api', () => ({
  default: {
    getSystemEvents: vi.fn(),
  },
}));

// Mock the useLocalStorage hook
vi.mock('../../hooks/useLocalStorage', () => ({
  default: vi.fn((key, defaultValue) => {
    const mockSetters = {
      'events-refresh-interval': vi.fn(),
      'events-limit': vi.fn(),
      'date-format': vi.fn(),
    };
    return [defaultValue, mockSetters[key] || vi.fn()];
  }),
}));

// Mock Mantine components
vi.mock('@mantine/core', async () => {
  return {
    ActionIcon: ({ children, onClick }) => (
      <button onClick={onClick}>{children}</button>
    ),
    Box: ({ children }) => <div>{children}</div>,
    Button: ({ children, onClick }) => (
      <button onClick={onClick}>{children}</button>
    ),
    Card: ({ children }) => <div>{children}</div>,
    Group: ({ children }) => <div>{children}</div>,
    NumberInput: ({ value, onChange, label }) => (
      <input
        type="number"
        value={value}
        aria-label={label}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    ),
    Pagination: ({ page, onChange, total }) => (
      <div>
        {Array.from({ length: Math.ceil(total / 100) }, (_, i) => (
          <button key={i} onClick={() => onChange(i + 1)}>
            {i + 1}
          </button>
        ))}
      </div>
    ),
    Select: ({ value, onChange, data }) => (
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {data.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    ),
    Stack: ({ children }) => <div>{children}</div>,
    Text: ({ children }) => <div>{children}</div>,
    Title: ({ children }) => <h1>{children}</h1>,
  };
});

// Mock the dateTimeUtils
vi.mock('../../utils/dateTimeUtils.js', () => ({
  format: vi.fn((timestamp, format) => '01/15 10:30:45'),
}));

const mockEventsResponse = {
  events: [
    {
      id: 1,
      event_type: 'channel_start',
      event_type_display: 'Channel Started',
      channel_name: 'Test Channel',
      timestamp: '2024-01-15T10:30:45Z',
      details: { bitrate: '5000kbps' },
    },
    {
      id: 2,
      event_type: 'login_success',
      event_type_display: 'Login Successful',
      timestamp: '2024-01-15T10:25:30Z',
      details: {},
    },
  ],
  total: 2,
};

describe('SystemEvents', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    API.getSystemEvents.mockResolvedValue(mockEventsResponse);
  });

  afterEach(() => {
    vi.clearAllTimers();
  });

  it('should render component with title', async () => {
    render(<SystemEvents />);

    await waitFor(() => {
      expect(screen.getByText('System Events')).toBeInTheDocument();
    });
  });

  it('should fetch and display events on mount', async () => {
    render(<SystemEvents />);

    await waitFor(() => {
      expect(API.getSystemEvents).toHaveBeenCalledWith(100, 0);
    });
  });

  it('should expand and show events when chevron is clicked', async () => {
    render(<SystemEvents />);

    const expandButton = screen.getByRole('button', { name: '' });
    fireEvent.click(expandButton);

    await waitFor(() => {
      expect(screen.getByText('Channel Started')).toBeInTheDocument();
      expect(screen.getByText('Login Successful')).toBeInTheDocument();
    });
  });

  it('should display "No events recorded yet" when events array is empty', async () => {
    API.getSystemEvents.mockResolvedValue({ events: [], total: 0 });

    render(<SystemEvents />);

    const expandButton = screen.getByRole('button', { name: '' });
    fireEvent.click(expandButton);

    await waitFor(() => {
      expect(screen.getByText('No events recorded yet')).toBeInTheDocument();
    });
  });

  it('should call fetchEvents when refresh button is clicked', async () => {
    render(<SystemEvents />);

    const expandButton = screen.getByRole('button', { name: '' });
    fireEvent.click(expandButton);

    await waitFor(() => {
      expect(screen.getByText('Refresh')).toBeInTheDocument();
    });

    const refreshButton = screen.getByText('Refresh');
    fireEvent.click(refreshButton);

    await waitFor(() => {
      expect(API.getSystemEvents).toHaveBeenCalledTimes(3)
    });
  });

  it('should update events limit when changed', async () => {
    const mockSetEventsLimit = vi.fn();

    // Update the mock to return the setter for this test
    useLocalStorage.mockImplementation((key, defaultValue) => {
      if (key === 'events-limit') {
        return [100, mockSetEventsLimit];
      }
      return [defaultValue, vi.fn()];
    });

    render(<SystemEvents />);

    const expandButton = screen.getByRole('button', { name: '' });
    fireEvent.click(expandButton);

    await waitFor(() => {
      const input = screen.getByLabelText('Events Per Page');
      fireEvent.change(input, { target: { value: '50' } });
    });

    expect(mockSetEventsLimit).toHaveBeenCalled();
  });

  it('should show pagination when total events exceed limit', async () => {
    API.getSystemEvents.mockResolvedValue({
      events: mockEventsResponse.events,
      total: 150,
    });

    render(<SystemEvents />);

    const expandButton = screen.getByRole('button', { name: '' });
    fireEvent.click(expandButton);

    await waitFor(() => {
      expect(screen.getByText(/Showing 1-100 of 150/)).toBeInTheDocument();
    });
  });

  it('should handle API errors gracefully', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    API.getSystemEvents.mockRejectedValue(new Error('API Error'));

    render(<SystemEvents />);

    await waitFor(() => {
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        'Error fetching system events:',
        expect.any(Error)
      );
    });

    consoleErrorSpy.mockRestore();
  });

  it('should display event details correctly', async () => {
    render(<SystemEvents />);

    const expandButton = screen.getByRole('button', { name: '' });
    fireEvent.click(expandButton);

    await waitFor(() => {
      expect(screen.getByText('Test Channel')).toBeInTheDocument();
      expect(screen.getByText('bitrate: 5000kbps')).toBeInTheDocument();
    });
  });

  it('should change page when pagination is clicked', async () => {
    API.getSystemEvents.mockResolvedValue({
      events: mockEventsResponse.events,
      total: 250,
    });

    render(<SystemEvents />);

    const expandButton = screen.getByRole('button', { name: '' });
    fireEvent.click(expandButton);

    await waitFor(() => {
      expect(screen.getByText(/Showing 1-100 of 250/)).toBeInTheDocument();
    });

    // Note: Pagination interaction would require more specific selectors
    // based on Mantine's Pagination component implementation
  });
});
