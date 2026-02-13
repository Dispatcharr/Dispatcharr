/**
 * Reusable Schedule Input
 *
 * Shows the active scheduling mode with a subtle text link to switch.
 * Interval mode is the default; a small "Use cron schedule" link beneath
 * toggles to cron mode, and vice-versa.
 *
 * For M3U / EPG (default interval NumberInput):
 *   <ScheduleInput
 *     scheduleType={scheduleType}
 *     onScheduleTypeChange={setScheduleType}
 *     intervalValue={form.getValues().refresh_interval}
 *     onIntervalChange={(v) => form.setFieldValue('refresh_interval', v)}
 *     cronValue={form.getValues().cron_expression}
 *     onCronChange={(v) => form.setFieldValue('cron_expression', v)}
 *   />
 *
 * For Backups (custom simple-mode UI via children):
 *   <ScheduleInput
 *     scheduleType={scheduleType}
 *     onScheduleTypeChange={setScheduleType}
 *     cronValue={schedule.cron_expression}
 *     onCronChange={(v) => handleScheduleChange('cron_expression', v)}
 *     switchToCronLabel="Use custom cron schedule"
 *     switchToIntervalLabel="Use simple schedule"
 *   >
 *     ...frequency / time / day selectors...
 *   </ScheduleInput>
 */
import React, { useState, useEffect } from 'react';
import {
  TextInput,
  NumberInput,
  Anchor,
  Stack,
  Text,
  Code,
  Popover,
  ActionIcon,
  Group,
  Divider,
  SimpleGrid,
} from '@mantine/core';
import { Info } from 'lucide-react';
import { validateCronExpression } from '../../utils/cronUtils';
import CronBuilder from './CronBuilder';

export default function ScheduleInput({
  // Schedule type
  scheduleType = 'interval',
  onScheduleTypeChange,

  // Cron
  cronValue = '',
  onCronChange,

  // Default interval input (used when children not provided)
  intervalValue = 0,
  onIntervalChange,
  intervalLabel = 'Refresh Interval (hours)',
  intervalDescription = 'How often to refresh (0 to disable)',
  min = 0,

  // Custom simple-mode content (replaces the default NumberInput)
  children,

  // Link text for toggling
  switchToCronLabel = 'Use cron schedule',
  switchToIntervalLabel = 'Use interval schedule',

  disabled = false,
}) {
  const [cronError, setCronError] = useState(null);
  const [builderOpened, setBuilderOpened] = useState(false);

  // Validate cron whenever it changes
  useEffect(() => {
    if (scheduleType === 'cron' && cronValue) {
      const v = validateCronExpression(cronValue);
      setCronError(v.valid ? null : v.error);
    } else {
      setCronError(null);
    }
  }, [scheduleType, cronValue]);

  const switchToCron = (e) => {
    e.preventDefault();
    onScheduleTypeChange('cron');
  };

  const switchToInterval = (e) => {
    e.preventDefault();
    onScheduleTypeChange('interval');
    onCronChange('');
    setCronError(null);
  };

  const handleCronChange = (val) => {
    onCronChange(val);
    if (val) {
      const v = validateCronExpression(val);
      setCronError(v.valid ? null : v.error);
    } else {
      setCronError(null);
    }
  };

  const handleBuilderApply = (cron) => {
    handleCronChange(cron);
  };

  return (
    <Stack gap="xs">
      {scheduleType === 'cron' ? (
        <Stack gap="xs">
          <TextInput
            label={
              <Group gap="xs">
                Cron Expression
                <Popover width={320} position="top" withArrow shadow="md">
                  <Popover.Target>
                    <ActionIcon variant="subtle" size="xs" color="gray">
                      <Info size={14} />
                    </ActionIcon>
                  </Popover.Target>
                  <Popover.Dropdown p="sm">
                    <Text size="xs" fw={600} mb="xs" c="dimmed">
                      COMMON EXAMPLES
                    </Text>
                    <Stack gap={6}>
                      <Group gap="xs" wrap="nowrap">
                        <Text
                          size="xs"
                          c="dimmed"
                          style={{ minWidth: '140px' }}
                        >
                          Every day at 3 AM:
                        </Text>
                        <Code size="xs">0 3 * * *</Code>
                      </Group>
                      <Group gap="xs" wrap="nowrap">
                        <Text
                          size="xs"
                          c="dimmed"
                          style={{ minWidth: '140px' }}
                        >
                          At 4 AM, 10 AM, 4 PM:
                        </Text>
                        <Code size="xs">0 4,10,16 * * *</Code>
                      </Group>
                      <Group gap="xs" wrap="nowrap">
                        <Text
                          size="xs"
                          c="dimmed"
                          style={{ minWidth: '140px' }}
                        >
                          Sundays at 2 AM:
                        </Text>
                        <Code size="xs">0 2 * * 0</Code>
                      </Group>
                      <Group gap="xs" wrap="nowrap">
                        <Text
                          size="xs"
                          c="dimmed"
                          style={{ minWidth: '140px' }}
                        >
                          1st of month at 2:30 PM:
                        </Text>
                        <Code size="xs">30 14 1 * *</Code>
                      </Group>
                    </Stack>
                  </Popover.Dropdown>
                </Popover>
              </Group>
            }
            placeholder="0 3 * * *"
            description="minute hour day month weekday"
            value={cronValue}
            onChange={(e) => handleCronChange(e.currentTarget.value)}
            error={cronError}
            disabled={disabled}
          />
          {!disabled && (
            <Group gap="sm">
              <Anchor size="xs" onClick={switchToInterval}>
                {switchToIntervalLabel}
              </Anchor>
              <Anchor size="xs" onClick={() => setBuilderOpened(true)}>
                Open Cron Builder
              </Anchor>
            </Group>
          )}
          <CronBuilder
            opened={builderOpened}
            onClose={() => setBuilderOpened(false)}
            onApply={handleBuilderApply}
            currentValue={cronValue}
          />
        </Stack>
      ) : children ? (
        <Stack gap="xs">
          {children}
          {!disabled && (
            <Anchor size="xs" onClick={switchToCron}>
              {switchToCronLabel}
            </Anchor>
          )}
        </Stack>
      ) : (
        <Stack gap="xs">
          <NumberInput
            label={intervalLabel}
            description={intervalDescription}
            value={intervalValue}
            onChange={onIntervalChange}
            min={min}
            disabled={disabled}
            suffix=" hours"
          />
          {!disabled && (
            <Anchor size="xs" onClick={switchToCron}>
              {switchToCronLabel}
            </Anchor>
          )}
        </Stack>
      )}
    </Stack>
  );
}
