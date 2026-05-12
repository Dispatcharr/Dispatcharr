// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from 'vitest';

// Mock API.bulkUpdateChannels so we can assert on the body shape the
// helper sends. We're testing routing logic, not network behavior.
vi.mock('../../../api.js', () => ({
  default: {
    bulkUpdateChannels: vi.fn(async (body) => ({ ok: true, body })),
    updateChannels: vi.fn(),
  },
}));

import { updateChannelsWithOverrideRouting } from '../ChannelBatchUtils.js';
import API from '../../../api.js';

describe('updateChannelsWithOverrideRouting (manual finding #4)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('routes override-able fields to override.X for auto-created channels', async () => {
    // User-reported: bulk-edit "name" on auto-channels lost the change
    // on next sync because it wrote Channel.name (raw) instead of
    // override.name. The Pencil indicator never appeared because no
    // override row was created.
    const channelsById = {
      1: { id: 1, auto_created: true },
      2: { id: 2, auto_created: true },
    };
    await updateChannelsWithOverrideRouting(
      [1, 2],
      { name: 'BulkRename' },
      channelsById
    );

    expect(API.bulkUpdateChannels).toHaveBeenCalledTimes(1);
    const body = API.bulkUpdateChannels.mock.calls[0][0];
    expect(body).toEqual([
      { id: 1, override: { name: 'BulkRename' } },
      { id: 2, override: { name: 'BulkRename' } },
    ]);
  });

  it('keeps raw Channel.X writes for manual channels (auto_created=false)', async () => {
    const channelsById = {
      1: { id: 1, auto_created: false },
    };
    await updateChannelsWithOverrideRouting(
      [1],
      { name: 'ManualRename' },
      channelsById
    );
    const body = API.bulkUpdateChannels.mock.calls[0][0];
    expect(body).toEqual([{ id: 1, name: 'ManualRename' }]);
  });

  it('splits a mixed selection: auto-created → override, manual → raw', async () => {
    const channelsById = {
      1: { id: 1, auto_created: true },
      2: { id: 2, auto_created: false },
      3: { id: 3, auto_created: true },
    };
    await updateChannelsWithOverrideRouting(
      [1, 2, 3],
      { name: 'Mixed', tvg_id: 'mixed.tvg' },
      channelsById
    );
    const body = API.bulkUpdateChannels.mock.calls[0][0];
    expect(body).toEqual([
      { id: 1, override: { name: 'Mixed', tvg_id: 'mixed.tvg' } },
      { id: 2, name: 'Mixed', tvg_id: 'mixed.tvg' },
      { id: 3, override: { name: 'Mixed', tvg_id: 'mixed.tvg' } },
    ]);
  });

  it('always-raw fields (hidden_from_output, user_level, is_adult) bypass override routing', async () => {
    // hidden_from_output is a status flag, not a value override - it goes to
    // Channel.hidden_from_output directly even on auto-created channels.
    const channelsById = {
      1: { id: 1, auto_created: true },
    };
    await updateChannelsWithOverrideRouting(
      [1],
      { hidden_from_output: true, name: 'Renamed' },
      channelsById
    );
    const body = API.bulkUpdateChannels.mock.calls[0][0];
    expect(body).toEqual([
      { id: 1, hidden_from_output: true, override: { name: 'Renamed' } },
    ]);
  });

  it('falls back to raw when channelsById lookup is missing the row', async () => {
    // Defensive: if the channel store doesn't have the row (paginated
    // off, recent creation), default behavior should not crash and
    // should not silently drop the change.
    await updateChannelsWithOverrideRouting(
      [99],
      { name: 'Defensive' },
      {} // empty lookup
    );
    const body = API.bulkUpdateChannels.mock.calls[0][0];
    expect(body).toEqual([{ id: 99, name: 'Defensive' }]);
  });
});
