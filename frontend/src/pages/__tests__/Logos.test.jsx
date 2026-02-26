import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import LogosPage from '../Logos';
import useLogosStore from '../../store/logos';
import useVODLogosStore from '../../store/vodLogos';
import {
  showNotification,
  updateNotification,
} from '../../utils/notificationUtils.js';

vi.mock('../../store/logos');
vi.mock('../../store/vodLogos');
vi.mock('../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
  updateNotification: vi.fn(),
}));
vi.mock('../../components/tables/LogosTable', () => ({
  default: () => <div data-testid="logos-table">LogosTable</div>,
}));
vi.mock('../../components/tables/VODLogosTable', () => ({
  default: () => <div data-testid="vod-logos-table">VODLogosTable</div>,
}));
vi.mock('@mantine/core', () => {
  const tabsComponent = ({ children, value, onChange }) => (
    <div data-testid="tabs" data-value={value} onClick={() => onChange('vod')}>
      {children}
    </div>
  );
  tabsComponent.List = ({ children }) => <div>{children}</div>;
  tabsComponent.Tab = ({ children, value }) => (
    <button data-value={value}>{children}</button>
  );

  return {
    Box: ({ children, ...props }) => <div {...props}>{children}</div>,
    Flex: ({ children, ...props }) => <div {...props}>{children}</div>,
    Text: ({ children, ...props }) => <span {...props}>{children}</span>,
    Tabs: tabsComponent,
    TabsList: tabsComponent.List,
    TabsTab: tabsComponent.Tab,
  };
});

describe('LogosPage', () => {
  const mockFetchAllLogos = vi.fn();
  const mockNeedsAllLogos = vi.fn();

  const defaultLogosState = {
    fetchAllLogos: mockFetchAllLogos,
    needsAllLogos: mockNeedsAllLogos,
    logos: { 1: {}, 2: {}, 3: {} },
  };

  const defaultVODLogosState = {
    totalCount: 5,
  };

  beforeEach(() => {
    vi.clearAllMocks();

    useLogosStore.mockImplementation((selector) => {
      return selector ? selector(defaultLogosState) : defaultLogosState;
    });
    useLogosStore.getState = () => defaultLogosState;

    useVODLogosStore.mockImplementation((selector) => {
      return selector ? selector(defaultVODLogosState) : defaultVODLogosState;
    });

    mockNeedsAllLogos.mockReturnValue(true);
    mockFetchAllLogos.mockResolvedValue();
  });

  it('renders with channel logos tab by default', () => {
    render(<LogosPage />);

    expect(screen.getByText('Logos')).toBeInTheDocument();
    expect(screen.getByTestId('logos-table')).toBeInTheDocument();
    expect(screen.queryByTestId('vod-logos-table')).not.toBeInTheDocument();
  });

  it('displays correct channel logos count', () => {
    render(<LogosPage />);

    expect(screen.getByText(/\(3 logos\)/i)).toBeInTheDocument();
  });

  it('displays singular "logo" when count is 1', () => {
    useLogosStore.mockImplementation((selector) => {
      const state = {
        fetchAllLogos: mockFetchAllLogos,
        needsAllLogos: mockNeedsAllLogos,
        logos: { 1: {} },
      };
      return selector ? selector(state) : state;
    });

    render(<LogosPage />);

    expect(screen.getByText(/\(1 logo\)/i)).toBeInTheDocument();
  });

  it('fetches all logos on mount when needed', async () => {
    render(<LogosPage />);

    await waitFor(() => {
      expect(mockNeedsAllLogos).toHaveBeenCalled();
      expect(mockFetchAllLogos).toHaveBeenCalled();
    });
  });

  it('does not fetch logos when not needed', async () => {
    mockNeedsAllLogos.mockReturnValue(false);

    render(<LogosPage />);

    await waitFor(() => {
      expect(mockNeedsAllLogos).toHaveBeenCalled();
      expect(mockFetchAllLogos).not.toHaveBeenCalled();
    });
  });

  it('shows error notification when fetching logos fails', async () => {
    const consoleErrorSpy = vi
      .spyOn(console, 'error')
      .mockImplementation(() => {});
    const error = new Error('Failed to fetch');
    mockFetchAllLogos.mockRejectedValue(error);

    render(<LogosPage />);

    await waitFor(() => {
      expect(showNotification).toHaveBeenCalledWith({
        title: 'Error',
        message: 'Failed to load channel logos',
        color: 'red',
      });
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        'Failed to load channel logos:',
        error
      );
    });

    consoleErrorSpy.mockRestore();
  });

  it('switches to VOD logos tab when clicked', () => {
    const { rerender } = render(<LogosPage />);

    expect(screen.getByTestId('logos-table')).toBeInTheDocument();

    const tabs = screen.getByTestId('tabs');
    fireEvent.click(tabs);

    rerender(<LogosPage />);

    expect(screen.getByTestId('vod-logos-table')).toBeInTheDocument();
    expect(screen.queryByTestId('logos-table')).not.toBeInTheDocument();
  });

  it('renders both tab options', () => {
    render(<LogosPage />);

    expect(screen.getByText('Channel Logos')).toBeInTheDocument();
    expect(screen.getByText('VOD Logos')).toBeInTheDocument();
  });

  it('displays zero logos correctly', () => {
    useLogosStore.mockImplementation((selector) => {
      const state = {
        fetchAllLogos: mockFetchAllLogos,
        needsAllLogos: mockNeedsAllLogos,
        logos: {},
      };
      return selector ? selector(state) : state;
    });

    render(<LogosPage />);

    expect(screen.getByText(/\(0 logos\)/i)).toBeInTheDocument();
  });
});
