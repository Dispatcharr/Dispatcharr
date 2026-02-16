/**
 * Cron Expression Builder Modal
 *
 * Provides an easy interface to build cron expressions with:
 * - Quick preset buttons for common schedules
 * - Simple hour/minute/day selectors
 * - Preview of next run times
 */
import React, { useState, useEffect } from 'react';
import {
  Modal,
  Button,
  Group,
  Stack,
  Select,
  NumberInput,
  Text,
  Badge,
  SimpleGrid,
  Divider,
  TextInput,
  Paper,
  Tabs,
  Code,
} from '@mantine/core';
import { Clock, Calendar } from 'lucide-react';

const PRESETS = [
  {
    label: 'Every hour',
    value: '0 * * * *',
    description: 'At the start of every hour',
  },
  {
    label: 'Every 6 hours',
    value: '0 */6 * * *',
    description: 'Every 6 hours starting at midnight',
  },
  {
    label: 'Every 12 hours',
    value: '0 */12 * * *',
    description: 'Twice daily at midnight and noon',
  },
  {
    label: 'Daily at midnight',
    value: '0 0 * * *',
    description: 'Once per day at 12:00 AM',
  },
  {
    label: 'Daily at 3 AM',
    value: '0 3 * * *',
    description: 'Once per day at 3:00 AM',
  },
  {
    label: 'Daily at noon',
    value: '0 12 * * *',
    description: 'Once per day at 12:00 PM',
  },
  {
    label: 'Weekly (Sunday midnight)',
    value: '0 0 * * 0',
    description: 'Once per week on Sunday',
  },
  {
    label: 'Weekly (Monday 3 AM)',
    value: '0 3 * * 1',
    description: 'Once per week on Monday',
  },
  {
    label: 'Monthly (1st at 2:30 AM)',
    value: '30 2 1 * *',
    description: 'First day of each month',
  },
];

const DAYS_OF_WEEK = [
  { value: '*', label: 'Every day' },
  { value: '0', label: 'Sunday' },
  { value: '1', label: 'Monday' },
  { value: '2', label: 'Tuesday' },
  { value: '3', label: 'Wednesday' },
  { value: '4', label: 'Thursday' },
  { value: '5', label: 'Friday' },
  { value: '6', label: 'Saturday' },
];

const FREQUENCY_OPTIONS = [
  { value: 'hourly', label: 'Hourly' },
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'monthly', label: 'Monthly' },
];

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
  const [generatedCron, setGeneratedCron] = useState('0 3 * * *');
  const [manualCron, setManualCron] = useState('* * * * *');

  // Initialize manualCron from currentValue when modal opens
  useEffect(() => {
    if (opened && currentValue) {
      setManualCron(currentValue);
    }
  }, [opened, currentValue]);

  // Update generated cron when inputs change
  useEffect(() => {
    let cron = '';
    switch (frequency) {
      case 'hourly':
        cron = `${minute} * * * *`;
        break;
      case 'daily':
        cron = `${minute} ${hour} * * *`;
        break;
      case 'weekly':
        cron = `${minute} ${hour} * * ${dayOfWeek === '*' ? '0' : dayOfWeek}`;
        break;
      case 'monthly':
        cron = `${minute} ${hour} ${dayOfMonth} * *`;
        break;
    }
    setGeneratedCron(cron);
  }, [frequency, hour, minute, dayOfWeek, dayOfMonth]);

  const handlePresetClick = (cron) => {
    setGeneratedCron(cron);
    setManualCron(cron);

    // Parse the cron expression and update form fields
    const parts = cron.split(' ');
    if (parts.length === 5) {
      const [min, hr, day, _month, weekday] = parts;

      setMinute(parseInt(min) || 0);

      // Determine frequency based on pattern
      if (hr === '*') {
        setFrequency('hourly');
      } else if (day !== '*' && day !== '1') {
        // Has specific day of month
        setFrequency('monthly');
        setHour(parseInt(hr.replace('*/', '').replace('*', '0')) || 0);
        setDayOfMonth(parseInt(day) || 1);
      } else if (weekday !== '*') {
        // Has specific day of week
        setFrequency('weekly');
        setHour(parseInt(hr.replace('*/', '').replace('*', '0')) || 0);
        setDayOfWeek(weekday);
      } else if (day === '1') {
        // Monthly on 1st
        setFrequency('monthly');
        setHour(parseInt(hr.replace('*/', '').replace('*', '0')) || 0);
        setDayOfMonth(1);
      } else {
        // Daily
        setFrequency('daily');
        setHour(parseInt(hr.replace('*/', '').replace('*', '0')) || 0);
      }
    }
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
          <Tabs.List grow>
            <Tabs.Tab value="simple">Simple</Tabs.Tab>
            <Tabs.Tab value="advanced">Advanced</Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="simple" pt="md">
            <Stack gap="md">
              {/* Quick Presets */}
              <div>
                <Text size="sm" fw={500} mb="xs">
                  Quick Presets
                </Text>
                <SimpleGrid cols={3} spacing="xs">
                  {PRESETS.map((preset) => (
                    <Button
                      key={preset.value}
                      variant="light"
                      size="xs"
                      onClick={() => handlePresetClick(preset.value)}
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
          </Tabs.Panel>

          <Tabs.Panel value="advanced" pt="md">
            <Stack gap="sm">
              <Text size="sm" c="dimmed">
                Build advanced cron expressions with comma-separated values
                (e.g., <Code>2,4,16</Code>), ranges (e.g., <Code>9-17</Code>),
                or steps (e.g., <Code>*/15</Code>).
              </Text>

              <SimpleGrid cols={2} spacing="sm">
                <TextInput
                  label="Minute (0-59)"
                  placeholder="*, 0, */15, 0,15,30,45"
                  value={manualCron.split(' ')[0] || '*'}
                  onChange={(e) => {
                    const parts =
                      manualCron.split(' ').length >= 5
                        ? manualCron.split(' ')
                        : ['*', '*', '*', '*', '*'];
                    parts[0] = e.currentTarget.value || '*';
                    setManualCron(parts.join(' '));
                  }}
                />

                <TextInput
                  label="Hour (0-23)"
                  placeholder="*, 0, 9-17, */6, 2,4,16"
                  value={manualCron.split(' ')[1] || '*'}
                  onChange={(e) => {
                    const parts =
                      manualCron.split(' ').length >= 5
                        ? manualCron.split(' ')
                        : ['*', '*', '*', '*', '*'];
                    parts[1] = e.currentTarget.value || '*';
                    setManualCron(parts.join(' '));
                  }}
                />

                <TextInput
                  label="Day of Month (1-31)"
                  placeholder="*, 1, 1-15, */2, 1,15"
                  value={manualCron.split(' ')[2] || '*'}
                  onChange={(e) => {
                    const parts =
                      manualCron.split(' ').length >= 5
                        ? manualCron.split(' ')
                        : ['*', '*', '*', '*', '*'];
                    parts[2] = e.currentTarget.value || '*';
                    setManualCron(parts.join(' '));
                  }}
                />

                <TextInput
                  label="Month (1-12)"
                  placeholder="*, 1, 1-6, */3, 6,12"
                  value={manualCron.split(' ')[3] || '*'}
                  onChange={(e) => {
                    const parts =
                      manualCron.split(' ').length >= 5
                        ? manualCron.split(' ')
                        : ['*', '*', '*', '*', '*'];
                    parts[3] = e.currentTarget.value || '*';
                    setManualCron(parts.join(' '));
                  }}
                />
              </SimpleGrid>

              <TextInput
                label="Day of Week (0-6, Sun-Sat)"
                placeholder="*, 0, 1-5, 0,6"
                value={manualCron.split(' ')[4] || '*'}
                onChange={(e) => {
                  const parts =
                    manualCron.split(' ').length >= 5
                      ? manualCron.split(' ')
                      : ['*', '*', '*', '*', '*'];
                  parts[4] = e.currentTarget.value || '*';
                  setManualCron(parts.join(' '));
                }}
              />

              <Text size="xs" c="dimmed">
                Examples: <Code>0 4,10,16 * * *</Code> at 4 AM, 10 AM, and 4 PM
                &bull; <Code>0 9-17 * * 1-5</Code> hourly 9 AM-5 PM Mon-Fri
                &bull; <Code>*/15 * * * *</Code> every 15 minutes
              </Text>
            </Stack>
          </Tabs.Panel>
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
