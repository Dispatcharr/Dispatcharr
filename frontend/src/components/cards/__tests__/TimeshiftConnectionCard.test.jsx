import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../../../utils/dateTimeUtils.js', () => ({
  useDateTimeFormat: vi.fn(() => ({ fullDateTimeFormat: 'MM/DD/YYYY h:mm A' })),
}));

vi.mock('../../../store/users.jsx', () => ({
  default: vi.fn(() => []),
}));

vi.mock('../../../images/logo.png', () => ({ default: 'default-logo.png' }));

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

vi.mock('../../LazyLogo.jsx', () => ({
  default: ({ logoId, fallbackSrc, ...props }) => (
    <img
      src={logoId ? `logo-${logoId}.png` : fallbackSrc}
      alt="channel logo"
      {...props}
    />
  ),
}));

import TimeshiftConnectionCard from '../TimeshiftConnectionCard.jsx';

describe('TimeshiftConnectionCard logos', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('passes the channel logo ID to LazyLogo', () => {
    render(
      <TimeshiftConnectionCard
        timeshiftSession={{
          session_id: 'sess-1',
          channel_name: 'Test Channel',
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
      />
    );

    const img = screen.getByAltText('channel logo');
    expect(img.getAttribute('src')).toBe('logo-77.png');
  });
});

describe('TimeshiftConnectionCard audio badge', () => {
  const session = (overrides = {}) => ({
    session_id: 'sess-1',
    channel_name: 'Test Channel',
    programme_start: '2026-07-17:20-00-00',
    connections: [
      {
        session_id: 'sess-1',
        client_id: 'sess-1',
        ip_address: '10.0.0.5',
        connected_at: 1_700_000_000,
      },
    ],
    ...overrides,
  });

  it('shows the best track with a count of the other tracks', () => {
    render(
      <TimeshiftConnectionCard
        timeshiftSession={session({
          audio_language: 'eng',
          audio_channels: '5.1',
          audio_codec: 'ac3',
          audio_streams: [{ index: 1 }, { index: 2 }, { index: 3 }],
        })}
      />
    );
    expect(screen.getByText('ENG 5.1 AC3 +2')).toBeInTheDocument();
  });

  it('falls back to channels and codec without a track list', () => {
    render(
      <TimeshiftConnectionCard
        timeshiftSession={session({
          audio_channels: 'stereo',
          audio_codec: 'aac',
        })}
      />
    );
    expect(screen.getByText('stereo AAC')).toBeInTheDocument();
  });

  it('renders no audio badge when no audio info exists', () => {
    render(<TimeshiftConnectionCard timeshiftSession={session()} />);
    expect(screen.queryByText(/AAC|AC3/)).not.toBeInTheDocument();
  });
});
