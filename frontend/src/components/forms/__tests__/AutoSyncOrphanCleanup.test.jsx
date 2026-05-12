import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Module mocks ───────────────────────────────────────────────────────────────
vi.mock('../../../utils/forms/M3uUtils.js', () => ({
  updatePlaylist: vi.fn(() => Promise.resolve({})),
}));

vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

vi.mock('@mantine/core', () => ({
  Box: ({ children }) => <div>{children}</div>,
  Group: ({ children }) => <div>{children}</div>,
  Text: ({ children }) => <span>{children}</span>,
  Tooltip: ({ children }) => <>{children}</>,
  SegmentedControl: ({ value, onChange, data }) => (
    <div data-testid="segmented-control" data-value={value}>
      {data.map((opt) => (
        <button
          key={opt.value}
          data-testid={`segmented-${opt.value}`}
          data-active={value === opt.value}
          onClick={() => onChange?.(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  ),
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import OrphanCleanupControl from '../AutoSyncOrphanCleanup';
import { updatePlaylist } from '../../../utils/forms/M3uUtils.js';
import { showNotification } from '../../../utils/notificationUtils.js';

// ── Helpers ────────────────────────────────────────────────────────────────────
const makePlaylist = (overrides = {}) => ({
  id: 7,
  custom_properties: null,
  ...overrides,
});

const renderControl = (playlistOverrides = {}) =>
  render(<OrphanCleanupControl playlist={makePlaylist(playlistOverrides)} />);

const getControl = () => screen.getByTestId('segmented-control');

// ──────────────────────────────────────────────────────────────────────────────
describe('OrphanCleanupControl', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Initial state ──────────────────────────────────────────────────────────
  describe('initial state', () => {
    it('defaults to "always" when custom_properties is null', () => {
      renderControl({ custom_properties: null });
      expect(getControl()).toHaveAttribute('data-value', 'always');
    });

    it('defaults to "always" when orphan_channel_cleanup key is absent', () => {
      renderControl({ custom_properties: { compact_numbering: true } });
      expect(getControl()).toHaveAttribute('data-value', 'always');
    });

    it('reads persisted "preserve_customized" mode from custom_properties', () => {
      renderControl({
        custom_properties: { orphan_channel_cleanup: 'preserve_customized' },
      });
      expect(getControl()).toHaveAttribute('data-value', 'preserve_customized');
    });

    it('reads persisted "never" mode from custom_properties', () => {
      renderControl({
        custom_properties: { orphan_channel_cleanup: 'never' },
      });
      expect(getControl()).toHaveAttribute('data-value', 'never');
    });
  });

  // ── Optimistic update ──────────────────────────────────────────────────────
  describe('on mode change', () => {
    it('updates the displayed value immediately before the PATCH resolves', () => {
      vi.mocked(updatePlaylist).mockReturnValue(new Promise(() => {})); // never resolves
      renderControl();
      fireEvent.click(screen.getByTestId('segmented-never'));
      expect(getControl()).toHaveAttribute('data-value', 'never');
    });

    it('calls updatePlaylist with merged custom_properties', async () => {
      renderControl({ custom_properties: { compact_numbering: true } });
      fireEvent.click(screen.getByTestId('segmented-never'));

      await waitFor(() => {
        expect(updatePlaylist).toHaveBeenCalledWith(
          expect.objectContaining({ id: 7 }),
          {
            custom_properties: {
              compact_numbering: true,
              orphan_channel_cleanup: 'never',
            },
          }
        );
      });
    });

    it('does not call updatePlaylist when playlist has no id', async () => {
      renderControl({ id: undefined });
      fireEvent.click(screen.getByTestId('segmented-never'));
      await Promise.resolve();
      expect(updatePlaylist).not.toHaveBeenCalled();
    });

    it('preserves final "always" value after successful PATCH', async () => {
      renderControl({ custom_properties: { orphan_channel_cleanup: 'never' } });
      fireEvent.click(screen.getByTestId('segmented-always'));
      await waitFor(() => expect(updatePlaylist).toHaveBeenCalled());
      expect(getControl()).toHaveAttribute('data-value', 'always');
    });
  });

  // ── Error / revert ─────────────────────────────────────────────────────────
  describe('on PATCH failure', () => {
    it('reverts to the previous mode', async () => {
      vi.mocked(updatePlaylist).mockRejectedValueOnce(
        new Error('Server error')
      );
      renderControl({
        custom_properties: { orphan_channel_cleanup: 'always' },
      });
      fireEvent.click(screen.getByTestId('segmented-never'));

      await waitFor(() => expect(showNotification).toHaveBeenCalled());
      expect(getControl()).toHaveAttribute('data-value', 'always');
    });

    it('shows a red error notification', async () => {
      vi.mocked(updatePlaylist).mockRejectedValueOnce(
        new Error('Server error')
      );
      renderControl();
      fireEvent.click(screen.getByTestId('segmented-never'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'red' })
        );
      });
    });

    it('includes err.message in the notification when body.detail is absent', async () => {
      vi.mocked(updatePlaylist).mockRejectedValueOnce(new Error('Timeout'));
      renderControl();
      fireEvent.click(screen.getByTestId('segmented-never'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ message: 'Timeout' })
        );
      });
    });

    it('prefers err.body.detail over err.message', async () => {
      const err = Object.assign(new Error('generic'), {
        body: { detail: 'Specific detail from server' },
      });
      vi.mocked(updatePlaylist).mockRejectedValueOnce(err);
      renderControl();
      fireEvent.click(screen.getByTestId('segmented-never'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ message: 'Specific detail from server' })
        );
      });
    });

    it('falls back to "Please try again." when error has no message or body', async () => {
      vi.mocked(updatePlaylist).mockRejectedValueOnce({});
      renderControl();
      fireEvent.click(screen.getByTestId('segmented-never'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ message: 'Please try again.' })
        );
      });
    });
  });

  // ── useEffect sync ─────────────────────────────────────────────────────────
  describe('useEffect sync on prop change', () => {
    it('syncs displayed mode when playlist.custom_properties changes', () => {
      const { rerender } = render(
        <OrphanCleanupControl
          playlist={makePlaylist({
            custom_properties: { orphan_channel_cleanup: 'always' },
          })}
        />
      );
      expect(getControl()).toHaveAttribute('data-value', 'always');

      rerender(
        <OrphanCleanupControl
          playlist={makePlaylist({
            custom_properties: { orphan_channel_cleanup: 'never' },
          })}
        />
      );
      expect(getControl()).toHaveAttribute('data-value', 'never');
    });

    it('resets to "always" when orphan_channel_cleanup is removed from custom_properties', () => {
      const { rerender } = render(
        <OrphanCleanupControl
          playlist={makePlaylist({
            custom_properties: { orphan_channel_cleanup: 'never' },
          })}
        />
      );
      rerender(
        <OrphanCleanupControl
          playlist={makePlaylist({ custom_properties: {} })}
        />
      );
      expect(getControl()).toHaveAttribute('data-value', 'always');
    });
  });
});
