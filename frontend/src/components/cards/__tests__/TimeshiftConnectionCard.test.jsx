import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../../../utils/dateTimeUtils.js', () => ({
  useDateTimeFormat: vi.fn(() => ({ fullDateTimeFormat: 'MM/DD/YYYY h:mm A' })),
}));

vi.mock('../../../store/users.jsx', () => ({
  default: vi.fn(() => []),
}));

vi.mock('../../../images/logo.png', () => ({ default: 'default-logo.png' }));

vi.mock('../../../utils/cards/StreamConnectionCardUtils.js', () => ({
  getLogoUrl: vi.fn(),
}));

vi.mock('../../../utils/cards/TimeshiftConnectionCardUtils.js', () => ({
  calculateConnectionDuration: vi.fn(() => '5m'),
  calculateConnectionStartTime: vi.fn(() => 'Jan 1 2024 10:00 AM'),
  computeCatchupPlaybackSeconds: vi.fn(() => 0),
  getConnectionDurationSeconds: vi.fn(() => 0),
}));

vi.mock('@mantine/core', () => ({
  ActionIcon: ({ children }) => <button type="button">{children}</button>,
  Badge: ({ children }) => <span>{children}</span>,
  Box: ({ children }) => <div>{children}</div>,
  Card: ({ children }) => <div data-testid="timeshift-connection-card">{children}</div>,
  Center: ({ children }) => <div>{children}</div>,
  Group: ({ children }) => <div>{children}</div>,
  Stack: ({ children }) => <div>{children}</div>,
  Text: ({ children }) => <span>{children}</span>,
  Tooltip: ({ children }) => <>{children}</>,
}));

vi.mock('lucide-react', () => ({
  ChevronDown: () => null,
  HardDriveUpload: () => null,
  History: () => null,
  SquareX: () => null,
  Timer: () => null,
}));

vi.mock('../../ProgramPreview.jsx', () => ({
  default: () => <div data-testid="program-preview" />,
}));

import TimeshiftConnectionCard from '../TimeshiftConnectionCard.jsx';
import { getLogoUrl } from '../../../utils/cards/StreamConnectionCardUtils.js';

describe('TimeshiftConnectionCard logos', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getLogoUrl.mockReturnValue('/api/channels/logos/77/cache/');
  });

  it('resolves the channel logo via logo_id and the logos store', () => {
    render(
      <TimeshiftConnectionCard
        timeshiftSession={{
          session_id: 'sess-1',
          channel_name: 'US | A&E',
          logo_id: 77,
          programme_start: '2026-07-17:20-00-00',
          connections: [
            {
              session_id: 'sess-1',
              client_id: 'sess-1',
              ip_address: '10.0.0.5',
              connected_at: 1_700_000_000,
            },
          ],
        }}
        logos={{ 77: { cache_url: '/api/channels/logos/77/cache/' } }}
      />
    );

    expect(getLogoUrl).toHaveBeenCalledWith(77, {
      77: { cache_url: '/api/channels/logos/77/cache/' },
    });
    const img = screen.getByAltText('channel logo');
    expect(img.getAttribute('src')).toBe('/api/channels/logos/77/cache/');
  });
});
