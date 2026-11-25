import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { SafeModeSidebar } from '../SafeModeNotice';
import useSettingsStore from '../../store/settings';

vi.mock('../../store/settings', () => ({ default: vi.fn() }));

function renderWithTheme(component) {
  return render(<MantineProvider>{component}</MantineProvider>);
}

describe('safe mode notices', () => {
  it('does not show notices when safe mode is off', () => {
    useSettingsStore.mockImplementation((selector) => selector({ environment: { safe_mode: false } }));
    renderWithTheme(<SafeModeSidebar />);
    expect(screen.queryByText(/safe mode active/i)).not.toBeInTheDocument();
  });

  it('shows a collapsed sidebar warning and recovery instructions', async () => {
    useSettingsStore.mockImplementation((selector) => selector({ environment: {
      safe_mode: true,
      safe_mode_effects: [{ id: 'refresh', label: 'Automatic M3U and EPG refreshes', status: 'Disabled' }],
    } }));
    renderWithTheme(<SafeModeSidebar collapsed />);
    fireEvent.click(screen.getByRole('button', { name: /safe mode active/i }));
    expect(await screen.findByText(/remove DISPATCHARR_SAFE_MODE/)).toBeInTheDocument();
    expect(screen.getByText(/both web and Celery/)).toBeInTheDocument();
    expect(screen.getByText('Automatic M3U and EPG refreshes')).toBeInTheDocument();
  });

  it('shows a clickable warning in the expanded sidebar', () => {
    useSettingsStore.mockImplementation((selector) => selector({ environment: { safe_mode: true } }));
    renderWithTheme(<SafeModeSidebar collapsed={false} />);
    expect(screen.getByRole('button', { name: /safe mode active/i })).toHaveTextContent('Some features may be unavailable.');
    expect(screen.queryByText('Learn more')).not.toBeInTheDocument();
  });
});
