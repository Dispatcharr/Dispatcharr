import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import ContentSourcesPage from '../ContentSources';
import useUserAgentsStore from '../../store/userAgents';

vi.mock('../../store/userAgents');
vi.mock('../../components/tables/M3UsTable', () => ({
  default: () => <div data-testid="m3us-table">M3UsTable</div>,
}));
vi.mock('../../components/tables/EPGsTable', () => ({
  default: () => <div data-testid="epgs-table">EPGsTable</div>,
}));
vi.mock('@mantine/core', () => ({
  Box: ({ children, ...props }) => <div {...props}>{children}</div>,
  Stack: ({ children, ...props }) => <div {...props}>{children}</div>,
}));

describe('ContentSourcesPage', () => {
  it('shows only M3U accounts on the M3U source page', () => {
    useUserAgentsStore.mockReturnValue(null);
    render(<ContentSourcesPage section="m3u" />);
    expect(screen.getByTestId('m3us-table')).toBeInTheDocument();
    expect(screen.queryByTestId('epgs-table')).not.toBeInTheDocument();
  });
  it('shows only EPG sources on the EPG source page', () => {
    useUserAgentsStore.mockReturnValue(null);
    render(<ContentSourcesPage section="epg" />);
    expect(screen.getByTestId('epgs-table')).toBeInTheDocument();
    expect(screen.queryByTestId('m3us-table')).not.toBeInTheDocument();
  });
  it('renders error on userAgents error', () => {
    const errorMessage = 'Failed to load userAgents.';
    useUserAgentsStore.mockReturnValue(errorMessage);
    render(<ContentSourcesPage />);
    const element = screen.getByText(/Something went wrong/i);
    expect(element).toBeInTheDocument();
  });

  it('no error renders tables', () => {
    useUserAgentsStore.mockReturnValue(null);
    render(<ContentSourcesPage />);
    expect(screen.getByTestId('m3us-table')).toBeInTheDocument();
    expect(screen.getByTestId('epgs-table')).toBeInTheDocument();
  });
});
