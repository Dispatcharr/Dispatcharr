/**
 * Cron Expression Builder Modal
 *
 * Provides an easy interface to build cron expressions with:
 * - Quick preset buttons for common schedules
 * - Simple hour/minute/day selectors
 * - Preview of next run times
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  Badge,
  Button,
  Code,
  Divider,
  Group,
  Modal,
  NumberInput,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Tabs,
  TabsList,
  TabsPanel,
  TabsTab,
  Text,
  TextInput,
} from '@mantine/core';
import { Calendar, Clock } from 'lucide-react';
import {
  buildCron,
  CRON_FIELDS,
  DAYS_OF_WEEK,
  FREQUENCY_OPTIONS,
  parseCronPreset,
  PRESETS,
  updateCronPart,
} from '../../utils/forms/CronBuilderUtils.js';

const CronPartInput = ({ field, cron, onChange }) => (
  <TextInput
    label={field.label}
    placeholder={field.placeholder}
    value={cron.split(' ')[field.index] || '*'}
    onChange={(e) =>
      onChange(updateCronPart(cron, field.index, e.currentTarget.value))
    }
  />
);

const Preset = ({ onClick, preset }) => (
  <Button
    variant="light"
    size="xs"
    onClick={onClick}
    style={{
      height: '75px',
      padding: '8px',
    }}
    styles={{
      root: {
        display: 'flex',
        flexDirection: 'column',
      },
      inner: {
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        width: '100%',
        height: '100%',
      },
      label: {
        width: '100%',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
      },
    }}
  >
    <div
      style={{
        textAlign: 'left',
        width: '100%',
        flex: '1 1 auto',
      }}
    >
      <Text size="xs" fw={500} mb={2}>
        {preset.label}
      </Text>
      <Text size="xs" c="dimmed" lineClamp={1}>
        {preset.description}
      </Text>
    </div>
    <Badge
      size="sm"
      variant="dot"
      color="gray"
      style={{
        flex: '0 0 auto',
      }}
    >
      {preset.value}
    </Badge>
  </Button>
);

export default function CronBuilder({
  opened,
  onClose,
  onApply,
  currentValue = '',
}) {
  const [mode, setMode] = useState('simple'); // 'simple' or 'advanced'
  const [frequency, setFrequency] = useState('daily');
  const [hour, setHour] = useState(3);
  const [minute, setMinute] = useState(0);
  const [dayOfWeek, setDayOfWeek] = useState('*');
  const [dayOfMonth, setDayOfMonth] = useState(1);
  const [manualCron, setManualCron] = useState('* * * * *');

  // Initialize manualCron from currentValue when modal opens
  useEffect(() => {
    if (opened && currentValue) {
      setManualCron(currentValue);
    }
  }, [opened, currentValue]);

  // Update generated cron when inputs change
  const generatedCron = useMemo(
    () => buildCron(frequency, minute, hour, dayOfWeek, dayOfMonth),
    [frequency, minute, hour, dayOfWeek, dayOfMonth]
  );

  const handlePresetClick = (cron) => {
    const parsed = parseCronPreset(cron);
    setFrequency(parsed.frequency);
    setMinute(parsed.minute);
    setHour(parsed.hour);
    setDayOfWeek(parsed.dayOfWeek);
    setDayOfMonth(parsed.dayOfMonth);
    setManualCron(cron);
  };

  const handleApply = () => {
    const cronToApply = mode === 'advanced' ? manualCron : generatedCron;
    onApply(cronToApply);
    onClose();
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title="Cron Expression Builder"
      size="xl"
    >
      <Stack gap="md">
        <Tabs value={mode} onChange={setMode}>
          <TabsList grow>
            <TabsTab value="simple">Simple</TabsTab>
            <TabsTab value="advanced">Advanced</TabsTab>
          </TabsList>

          <TabsPanel value="simple" pt="md">
            <Stack gap="md">
              {/* Quick Presets */}
              <div>
                <Text size="sm" fw={500} mb="xs">
                  Quick Presets
                </Text>
                <SimpleGrid cols={3} spacing="xs">
                  {PRESETS.map((preset) => (
                    <Preset
                      key={preset.value}
                      onClick={() => handlePresetClick(preset.value)}
                      preset={preset}
                    />
                  ))}
                </SimpleGrid>
              </div>

              <Divider label="OR Build Custom" labelPosition="center" />

              {/* Custom Builder */}
              <div>
                <Text size="sm" fw={500} mb="xs">
                  Custom Schedule
                </Text>
                <SimpleGrid cols={2} spacing="sm">
                  <Select
                    label="Frequency"
                    data={FREQUENCY_OPTIONS}
                    value={frequency}
                    onChange={setFrequency}
                    leftSection={<Calendar size={16} />}
                  />

                  {frequency !== 'hourly' && (
                    <NumberInput
                      label="Hour (0-23)"
                      value={hour}
                      onChange={setHour}
                      min={0}
                      max={23}
                      leftSection={<Clock size={16} />}
                    />
                  )}

                  <NumberInput
                    label="Minute (0-59)"
                    value={minute}
                    onChange={setMinute}
                    min={0}
                    max={59}
                    leftSection={<Clock size={16} />}
                  />

                  {frequency === 'weekly' && (
                    <Select
                      label="Day of Week"
                      data={DAYS_OF_WEEK}
                      value={dayOfWeek}
                      onChange={setDayOfWeek}
                    />
                  )}

                  {frequency === 'monthly' && (
                    <NumberInput
                      label="Day of Month (1-31)"
                      value={dayOfMonth}
                      onChange={setDayOfMonth}
                      min={1}
                      max={31}
                    />
                  )}
                </SimpleGrid>
              </div>
            </Stack>
          </TabsPanel>

          <TabsPanel value="advanced" pt="md">
            <Stack gap="sm">
              <Text size="sm" c="dimmed">
                Build advanced cron expressions with comma-separated values
                (e.g., <Code>2,4,16</Code>), ranges (e.g., <Code>9-17</Code>),
                or steps (e.g., <Code>*/15</Code>).
              </Text>

              <SimpleGrid cols={2} spacing="sm">
                {CRON_FIELDS.slice(0, 4).map((field) => (
                  <CronPartInput
                    key={field.index}
                    field={field}
                    cron={manualCron}
                    onChange={setManualCron}
                  />
                ))}
              </SimpleGrid>

              <CronPartInput
                field={CRON_FIELDS[4]}
                cron={manualCron}
                onChange={setManualCron}
              />

              <Text size="xs" c="dimmed">
                Examples: <Code>0 4,10,16 * * *</Code> at 4 AM, 10 AM, and 4 PM
                &bull; <Code>0 9-17 * * 1-5</Code> hourly 9 AM-5 PM Mon-Fri
                &bull; <Code>*/15 * * * *</Code> every 15 minutes
              </Text>
            </Stack>
          </TabsPanel>
        </Tabs>

        {/* Generated Expression */}
        <Paper withBorder p="md" bg="dark.6">
          <Group gap="xs">
            <Text size="sm" fw={500}>
              Expression:
            </Text>
            <Badge size="lg" variant="filled" color="blue">
              {mode === 'advanced' ? manualCron : generatedCron}
            </Badge>
          </Group>
        </Paper>

        {/* Actions */}
        <Group justify="flex-end" gap="sm">
          <Button variant="subtle" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={handleApply}>Apply Expression</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
