import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import useAuthStore from '../../store/auth';
import useLocalStorage from '../../hooks/useLocalStorage';
import ChannelsPage from '../Channels';

vi.mock('../../store/auth');
vi.mock('../../hooks/useLocalStorage');
vi.mock('../../components/tables/ChannelsTable', () => ({
  default: () => <div data-testid="channels-table">ChannelsTable</div>,
}));
vi.mock('../../components/tables/StreamsTable', () => ({
  default: () => <div data-testid="streams-table">StreamsTable</div>,
}));
vi.mock('@mantine/core', () => ({
  Box: ({ children, ...props }) => <div {...props}>{children}</div>,
}));
vi.mock('allotment', () => ({
  Allotment: ({ children }) => <div data-testid="allotment">{children}</div>,
}));

describe('ChannelsPage', () => {
  beforeEach(() => {
    useLocalStorage.mockReturnValue([[50, 50], vi.fn()]);
  });

  it('renders nothing when user is not authenticated', () => {
    useAuthStore.mockReturnValue({ id: null, user_level: 0 });
    const { container } = render(<ChannelsPage />);
    expect(container.firstChild).toBeNull();
  });

  it('renders only ChannelsTable for standard users', () => {
    useAuthStore.mockReturnValue({ id: 1, user_level: 1 });
    render(<ChannelsPage />);
    expect(screen.getByTestId('channels-table')).toBeInTheDocument();
    expect(screen.queryByTestId('streams-table')).not.toBeInTheDocument();
  });

  it('renders split view for higher-level users', async () => {
    useAuthStore.mockReturnValue({ id: 1, user_level: 2 });
    render(<ChannelsPage />);
    expect(screen.getByTestId('channels-table')).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId('streams-table')).toBeInTheDocument()
    );
  });
});
