import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import PluginManifestMessages from '../PluginManifestMessages.jsx';
import API from '../../api.js';

vi.mock('../../api.js', () => ({
  default: {
    getPluginManifestMessages: vi.fn(),
    dismissPluginManifestMessage: vi.fn(),
  },
}));

vi.mock('@mantine/core', () => ({
  ActionIcon: ({ children, onClick, ...props }) => <button onClick={onClick} {...props}>{children}</button>,
  Alert: ({ children, color }) => <div data-testid="message" data-color={color}>{children}</div>,
  Button: ({ children, ...props }) => <a {...props}>{children}</a>,
  Group: ({ children }) => <div>{children}</div>,
  Stack: ({ children }) => <div>{children}</div>,
  Text: ({ children }) => <span>{children}</span>,
  Tooltip: ({ children }) => <>{children}</>,
}));

vi.mock('lucide-react', () => ({
  AlertTriangle: () => null, CheckCircle2: () => null, CircleAlert: () => null,
  Info: () => null, ExternalLink: () => null, GitBranch: () => null, X: () => null,
}));

describe('PluginManifestMessages', () => {
  beforeEach(() => vi.resetAllMocks());

  it('renders a safe external link button beside the dismiss action', async () => {
    API.getPluginManifestMessages.mockResolvedValue([{
      id: '5fba1255-b2d7-4d7a-bf4c-1338dfd8c94e', severity: 'warning',
      title: 'Maintenance', body: 'Line one\nLine two', link: 'https://status.example.test/',
    }]);
    render(<PluginManifestMessages />);

    expect(await screen.findByText('Maintenance')).toBeInTheDocument();
    const link = screen.getByText('Open status.example.test');
    expect(link).toHaveAttribute('href', 'https://status.example.test/');
    expect(link).toHaveAttribute('target', '_blank');
    expect(screen.getByTestId('message')).toHaveAttribute('data-color', 'orange');
  });

  it('removes a message after dismissal', async () => {
    API.getPluginManifestMessages.mockResolvedValue([{
      id: '5fba1255-b2d7-4d7a-bf4c-1338dfd8c94e', severity: 'info', body: 'Dismiss me',
    }]);
    API.dismissPluginManifestMessage.mockResolvedValue({ success: true });
    render(<PluginManifestMessages />);

    await screen.findByText('Dismiss me');
    fireEvent.click(screen.getByLabelText('Dismiss message'));
    await waitFor(() => expect(screen.queryByText('Dismiss me')).not.toBeInTheDocument());
  });
});
