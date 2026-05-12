import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/forms/AutoSyncBasicUtils.js', () => ({
  clampChannelNumber: vi.fn((v) =>
    Math.min(999999, Math.max(1, Math.floor(Number(v) || 1)))
  ),
  computeRangeOverlapsFor: vi.fn(() => []),
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Flex: ({ children }) => <div data-testid="flex">{children}</div>,
  Stack: ({ children }) => <div data-testid="stack">{children}</div>,
  Text: ({ children, size, c }) => (
    <span data-testid="text" data-size={size} data-color={c}>
      {children}
    </span>
  ),
  Tooltip: ({ children, label }) => (
    <div data-testid="tooltip" data-label={label}>
      {children}
    </div>
  ),
  NumberInput: ({
    value,
    onChange,
    label,
    'data-testid': testId,
    min,
    max,
  }) => (
    <div>
      {label && <label>{label}</label>}
      <input
        data-testid={testId || label}
        type="number"
        value={value ?? ''}
        min={min}
        max={max}
        onChange={(e) =>
          onChange?.(e.target.value === '' ? '' : Number(e.target.value))
        }
      />
    </div>
  ),
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  AlertTriangle: () => <svg data-testid="icon-alert-triangle" />,
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import AutoSyncBasic from '../AutoSyncBasic';
import {
  clampChannelNumber,
  computeRangeOverlapsFor,
} from '../../../utils/forms/AutoSyncBasicUtils.js';

// ── Helpers ────────────────────────────────────────────────────────────────────
const makeGroup = (overrides = {}) => ({
  channel_group: 1,
  name: 'Sports',
  auto_sync_channel_start: 100,
  auto_sync_channel_end: 200,
  custom_properties: { channel_numbering_mode: 'fixed' },
  ...overrides,
});

const renderComponent = (groupOverrides = {}, props = {}) => {
  const group = makeGroup(groupOverrides);
  const onApplyGroupChange = vi.fn();
  const utils = render(
    <AutoSyncBasic
      group={group}
      groupStates={[]}
      groupConflicts={{}}
      onApplyGroupChange={onApplyGroupChange}
      {...props}
    />
  );
  return { group, onApplyGroupChange, ...utils };
};

// ──────────────────────────────────────────────────────────────────────────────
describe('AutoSyncBasic', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(computeRangeOverlapsFor).mockReturnValue([]);
    vi.mocked(clampChannelNumber).mockImplementation((v) =>
      Math.min(999999, Math.max(1, Math.floor(Number(v) || 1)))
    );
  });

  // ── next_available mode ────────────────────────────────────────────────────
  describe('next_available mode', () => {
    it('renders the explanation text instead of inputs', () => {
      renderComponent({
        custom_properties: { channel_numbering_mode: 'next_available' },
      });
      expect(
        screen.getByText(/Channels receive the lowest available numbers/i)
      ).toBeInTheDocument();
    });

    it('does not render any NumberInput', () => {
      renderComponent({
        custom_properties: { channel_numbering_mode: 'next_available' },
      });
      expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument();
    });
  });

  // ── fixed mode rendering ───────────────────────────────────────────────────
  describe('fixed mode rendering', () => {
    it('renders Start and End inputs', () => {
      renderComponent();
      expect(screen.getByTestId(/start/i)).toBeInTheDocument();
      expect(screen.getByTestId(/end/i)).toBeInTheDocument();
    });

    it('displays auto_sync_channel_start as the start value', () => {
      renderComponent({ auto_sync_channel_start: 150 });
      expect(screen.getByTestId(/start/i)).toHaveValue(150);
    });

    it('defaults start to 1 when auto_sync_channel_start is undefined', () => {
      renderComponent({ auto_sync_channel_start: undefined });
      expect(screen.getByTestId(/start/i)).toHaveValue(1);
    });

    it('displays auto_sync_channel_end as the end value', () => {
      renderComponent({ auto_sync_channel_end: 250 });
      expect(screen.getByTestId(/end/i)).toHaveValue(250);
    });

    it('displays empty end when auto_sync_channel_end is undefined', () => {
      renderComponent({ auto_sync_channel_end: undefined });
      expect(screen.getByTestId(/end/i)).toHaveValue(null);
    });
  });

  // ── provider mode rendering ────────────────────────────────────────────────
  describe('provider mode rendering', () => {
    it('reads start from custom_properties.channel_numbering_fallback', () => {
      renderComponent({
        custom_properties: {
          channel_numbering_mode: 'provider',
          channel_numbering_fallback: 500,
        },
      });
      expect(screen.getByTestId(/start/i)).toHaveValue(500);
    });

    it('defaults fallback start to 1 when channel_numbering_fallback is undefined', () => {
      renderComponent({
        custom_properties: {
          channel_numbering_mode: 'provider',
        },
      });
      expect(screen.getByTestId(/start/i)).toHaveValue(1);
    });
  });

  // ── defaults when no mode is set ──────────────────────────────────────────
  describe('defaults when mode is absent', () => {
    it('treats missing mode as fixed and renders inputs', () => {
      renderComponent({ custom_properties: {} });
      expect(screen.getByTestId(/start/i)).toBeInTheDocument();
      expect(screen.getByTestId(/end/i)).toBeInTheDocument();
    });
  });

  // ── updateStart — fixed mode ───────────────────────────────────────────────
  describe('updateStart in fixed mode', () => {
    it('calls onApplyGroupChange with clamped start value', () => {
      const { onApplyGroupChange } = renderComponent({
        auto_sync_channel_start: 100,
        auto_sync_channel_end: 200,
      });
      fireEvent.change(screen.getByTestId(/start/i), {
        target: { value: '150' },
      });
      expect(clampChannelNumber).toHaveBeenCalledWith(150);
      expect(onApplyGroupChange).toHaveBeenCalledWith(
        expect.objectContaining({ auto_sync_channel_start: expect.any(Number) })
      );
    });

    it('normalizes empty string input to 1', () => {
      const { onApplyGroupChange } = renderComponent();
      fireEvent.change(screen.getByTestId(/start/i), { target: { value: '' } });
      expect(onApplyGroupChange).toHaveBeenCalledWith(
        expect.objectContaining({ auto_sync_channel_start: 1 })
      );
      expect(clampChannelNumber).not.toHaveBeenCalled();
    });

    it('drops auto_sync_channel_end when new start exceeds current end', () => {
      const { onApplyGroupChange } = renderComponent({
        auto_sync_channel_start: 100,
        auto_sync_channel_end: 200,
      });
      vi.mocked(clampChannelNumber).mockReturnValueOnce(300);
      fireEvent.change(screen.getByTestId(/start/i), {
        target: { value: '300' },
      });
      expect(onApplyGroupChange).toHaveBeenCalledWith(
        expect.objectContaining({ auto_sync_channel_end: null })
      );
    });

    it('keeps auto_sync_channel_end when new start is below end', () => {
      const { onApplyGroupChange, group } = renderComponent({
        auto_sync_channel_start: 100,
        auto_sync_channel_end: 200,
      });
      vi.mocked(clampChannelNumber).mockReturnValueOnce(150);
      fireEvent.change(screen.getByTestId(/start/i), {
        target: { value: '150' },
      });
      expect(onApplyGroupChange).toHaveBeenCalledWith(
        expect.objectContaining({
          auto_sync_channel_end: group.auto_sync_channel_end,
        })
      );
    });

    it('keeps end when there is no existing end value', () => {
      const { onApplyGroupChange } = renderComponent({
        auto_sync_channel_start: 100,
        auto_sync_channel_end: undefined,
      });
      vi.mocked(clampChannelNumber).mockReturnValueOnce(500);
      fireEvent.change(screen.getByTestId(/start/i), {
        target: { value: '500' },
      });
      const call = onApplyGroupChange.mock.calls[0][0];
      expect(call.auto_sync_channel_end).toBeFalsy();
    });
  });

  // ── updateStart — provider mode ────────────────────────────────────────────
  describe('updateStart in provider mode', () => {
    it('writes to custom_properties.channel_numbering_fallback', () => {
      const { onApplyGroupChange } = renderComponent({
        custom_properties: {
          channel_numbering_mode: 'provider',
          channel_numbering_fallback: 100,
        },
      });
      vi.mocked(clampChannelNumber).mockReturnValueOnce(400);
      fireEvent.change(screen.getByTestId(/start/i), {
        target: { value: '400' },
      });
      expect(onApplyGroupChange).toHaveBeenCalledWith(
        expect.objectContaining({
          custom_properties: expect.objectContaining({
            channel_numbering_fallback: 400,
          }),
        })
      );
    });

    it('merges existing custom_properties when updating fallback', () => {
      const { onApplyGroupChange } = renderComponent({
        custom_properties: {
          channel_numbering_mode: 'provider',
          channel_numbering_fallback: 100,
          some_other_key: true,
        },
      });
      vi.mocked(clampChannelNumber).mockReturnValueOnce(200);
      fireEvent.change(screen.getByTestId(/start/i), {
        target: { value: '200' },
      });
      const call = onApplyGroupChange.mock.calls[0][0];
      expect(call.custom_properties.some_other_key).toBe(true);
      expect(call.custom_properties.channel_numbering_mode).toBe('provider');
    });

    it('normalizes empty string to 1 in provider mode', () => {
      const { onApplyGroupChange } = renderComponent({
        custom_properties: { channel_numbering_mode: 'provider' },
      });
      fireEvent.change(screen.getByTestId(/start/i), { target: { value: '' } });
      const call = onApplyGroupChange.mock.calls[0][0];
      expect(call.custom_properties.channel_numbering_fallback).toBe(1);
    });
  });

  // ── updateEnd ──────────────────────────────────────────────────────────────
  describe('updateEnd', () => {
    it('calls onApplyGroupChange with clamped end value', () => {
      const { onApplyGroupChange } = renderComponent();
      vi.mocked(clampChannelNumber).mockReturnValueOnce(300);
      fireEvent.change(screen.getByTestId(/end/i), {
        target: { value: '300' },
      });
      expect(onApplyGroupChange).toHaveBeenCalledWith(
        expect.objectContaining({ auto_sync_channel_end: 300 })
      );
    });

    it('normalizes empty end to null/falsy', () => {
      const { onApplyGroupChange } = renderComponent();
      fireEvent.change(screen.getByTestId(/end/i), { target: { value: '' } });
      const call = onApplyGroupChange.mock.calls[0][0];
      expect(
        call.auto_sync_channel_end == null || call.auto_sync_channel_end === ''
      ).toBe(true);
    });

    it('does not call clampChannelNumber when end is cleared', () => {
      renderComponent();
      fireEvent.change(screen.getByTestId(/end/i), { target: { value: '' } });
      expect(clampChannelNumber).not.toHaveBeenCalled();
    });
  });

  // ── Meta text ──────────────────────────────────────────────────────────────
  describe('meta text', () => {
    it('shows range info when end is set', () => {
      renderComponent({
        auto_sync_channel_start: 100,
        auto_sync_channel_end: 200,
      });
      expect(screen.getByTestId('text').textContent).toMatch(/100.*200|range/i);
    });

    it('shows stream count from group when available', () => {
      const group = makeGroup({ auto_sync_channel_end: 200, stream_count: 42 });
      const groupStates = [{ channel_group: 1 }];
      render(
        <AutoSyncBasic
          group={group}
          groupStates={groupStates}
          groupConflicts={{}}
          onApplyGroupChange={vi.fn()}
        />
      );
      expect(screen.getByTestId('text').textContent).toMatch(/42/);
    });
  });

  // ── Overlap and conflict warnings ──────────────────────────────────────────
  describe('warnings', () => {
    it('does not render warning icon when no conflicts or overlaps', () => {
      renderComponent({}, { groupConflicts: {} });
      expect(
        screen.queryByTestId('icon-alert-triangle')
      ).not.toBeInTheDocument();
    });

    it('renders warning icon when computeRangeOverlapsFor returns overlaps', () => {
      vi.mocked(computeRangeOverlapsFor).mockReturnValue([
        { name: 'Other Group', start: 150, end: 160 },
      ]);
      renderComponent();
      expect(screen.getByTestId('icon-alert-triangle')).toBeInTheDocument();
    });

    it('renders warning icon when group has a channel conflict', () => {
      renderComponent(
        {},
        { groupConflicts: { 1: { hasChannelConflict: true } } }
      );
      expect(screen.getByTestId('icon-alert-triangle')).toBeInTheDocument();
    });

    it('passes overlap group name to tooltip', () => {
      vi.mocked(computeRangeOverlapsFor).mockReturnValue([
        { name: 'News Group', start: 150, end: 160 },
      ]);
      renderComponent();

      const tooltip = screen
        .getAllByTestId('tooltip')
        .find((t) => t.getAttribute('data-label')?.includes('News Group'));
      expect(tooltip).toBeDefined();
    });

    it('passes channel conflict message to tooltip', () => {
      renderComponent(
        {},
        { groupConflicts: { 1: { hasChannelConflict: true } } }
      );

      const tooltip = screen
        .getAllByTestId('tooltip')
        .find((t) =>
          t.getAttribute('data-label')?.toLowerCase().includes('channel')
        );
      expect(tooltip).toBeDefined();
    });

    it('includes both conflict and overlap info in tooltip when both present', () => {
      vi.mocked(computeRangeOverlapsFor).mockReturnValue([
        { name: 'Overlap Group', start: 110, end: 120 },
      ]);
      renderComponent(
        {},
        { groupConflicts: { 1: { hasChannelConflict: true } } }
      );

      const tooltip = screen.getAllByTestId('tooltip').find((t) => {
        const label = t.getAttribute('data-label')?.toLowerCase();
        return label?.includes('channel') && label.includes('overlap group');
      });
      expect(tooltip).toBeDefined();
    });

    it('calls computeRangeOverlapsFor with the group and groupStates', () => {
      const group = makeGroup();
      const groupStates = [makeGroup({ channel_group: 2, name: 'B' })];
      render(
        <AutoSyncBasic
          group={group}
          groupStates={groupStates}
          groupConflicts={{}}
          onApplyGroupChange={vi.fn()}
        />
      );
      expect(computeRangeOverlapsFor).toHaveBeenCalledWith(group, groupStates);
    });
  });
});
