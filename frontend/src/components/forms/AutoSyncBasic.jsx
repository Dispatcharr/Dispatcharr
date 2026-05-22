// Inline Start/End range inputs for Fixed and Provider modes. Start
// writes to auto_sync_channel_start (Fixed) or
// custom_properties.channel_numbering_fallback (Provider); End always
// writes to auto_sync_channel_end. Next Available shows a one-line
// explanation because a range contradicts pack-anywhere semantics.
import { Flex, NumberInput, Stack, Text, Tooltip } from '@mantine/core';
import { AlertTriangle } from 'lucide-react';
import React from 'react';
import {
  clampChannelNumber,
  computeRangeOverlapsFor,
} from '../../utils/forms/AutoSyncBasicUtils.js';

const AutoSyncBasic = ({
  group,
  groupStates,
  groupConflicts,
  onApplyGroupChange,
}) => {
  const mode = group.custom_properties?.channel_numbering_mode || 'fixed';
  if (mode === 'next_available') {
    return (
      <Text size="xs" c="dimmed">
        Channels receive the lowest available numbers starting at 1.
      </Text>
    );
  }
  const startValue =
    mode === 'provider'
      ? (group.custom_properties?.channel_numbering_fallback ?? 1)
      : (group.auto_sync_channel_start ?? 1);
  const endValue = group.auto_sync_channel_end;
  // Caps pathological pasted values like "1e308" at the input layer.
  const updateStart = (value) => {
    const normalized =
      value === '' || value === null || value === undefined
        ? 1
        : clampChannelNumber(value);
    if (mode === 'provider') {
      onApplyGroupChange({
        ...group,
        custom_properties: {
          ...(group.custom_properties || {}),
          channel_numbering_fallback: normalized,
        },
      });
    } else {
      // If End is set and the new Start exceeds it, drop End so the user
      // is not left holding an invalid range silently.
      const next = { ...group, auto_sync_channel_start: normalized };
      if (
        endValue !== null &&
        endValue !== undefined &&
        normalized > endValue
      ) {
        next.auto_sync_channel_end = null;
      }
      onApplyGroupChange(next);
    }
    // Sweep effect picks up the state change and dispatches the scan.
  };
  const updateEnd = (value) => {
    const normalized =
      value === '' || value === null || value === undefined
        ? null
        : clampChannelNumber(value);
    onApplyGroupChange({
      ...group,
      auto_sync_channel_end: normalized,
    });
  };

  const streamCount =
    typeof group.stream_count === 'number' ? group.stream_count : null;
  const metaParts = [];
  if (endValue) {
    metaParts.push(`Range: ${Math.max(endValue - startValue + 1, 0)}`);
  }
  if (streamCount !== null) {
    metaParts.push(`Streams: ${streamCount}`);
  }
  const metaText = metaParts.join(' · ');

  const conflict = groupConflicts[group.channel_group];
  const hasChannelConflict = !!conflict?.hasChannelConflict;
  const overlaps = computeRangeOverlapsFor(group, groupStates);

  // Channel-level conflicts get a generic Channels-page pointer (count
  // can be large); range-level overlaps stay specific to the modal.
  const tooltipSections = [];
  if (hasChannelConflict) {
    tooltipSections.push(
      'Range conflicts with configured channels.\nView the Channels page to inspect.'
    );
  }
  if (overlaps.length > 0) {
    const overlapLines = overlaps
      .map((o) => `${o.name} (${o.start}-${o.end})`)
      .join('\n  ');
    tooltipSections.push(
      overlaps.length === 1
        ? `Range overlaps with: ${overlaps[0].name} (${overlaps[0].start}-${overlaps[0].end})`
        : `Range overlaps with:\n  ${overlapLines}`
    );
  }
  const showWarning = tooltipSections.length > 0;
  const tooltipBody = tooltipSections.join('\n\n');

  return (
    <Stack gap={4}>
      <Flex gap="xs" align="flex-start">
        <Tooltip
          label={
            mode === 'provider'
              ? 'Fallback channel number used when a stream has no provider-supplied number.'
              : 'First channel number assigned to this group.'
          }
          withArrow
          multiline
          w={260}
        >
          <NumberInput
            label="Start #"
            value={startValue}
            onChange={updateStart}
            min={1}
            step={1}
            size="xs"
            precision={0}
            style={{ flex: 1 }}
          />
        </Tooltip>
        <Tooltip
          label="Optional upper bound. Streams exceeding the range are skipped and reported after sync."
          withArrow
          multiline
          w={260}
        >
          <NumberInput
            label="End # (optional)"
            placeholder="Unlimited"
            value={endValue ?? ''}
            onChange={updateEnd}
            min={startValue || 1}
            step={1}
            size="xs"
            precision={0}
            style={{ flex: 1 }}
          />
        </Tooltip>
      </Flex>
      <Flex
        gap="xs"
        align="center"
        justify="space-between"
        style={{ minHeight: 18 }}
      >
        <Text size="xs" c="dimmed">
          {metaText}
        </Text>
        {showWarning && (
          <Tooltip
            label={tooltipBody}
            withArrow
            multiline
            w={280}
            styles={{ tooltip: { whiteSpace: 'pre-line' } }}
          >
            <AlertTriangle
              size={14}
              color="var(--mantine-color-yellow-6)"
              aria-label="Range conflict warning"
            />
          </Tooltip>
        )}
      </Flex>
    </Stack>
  );
};

export default AutoSyncBasic;
