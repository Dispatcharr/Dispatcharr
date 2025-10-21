import React, { useEffect, useMemo, useState } from 'react';
import {
  Box,
  Button,
  Checkbox,
  Divider,
  Group,
  Modal,
  NumberInput,
  Select,
  Stack,
  Text,
  TextInput,
  Textarea,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { notifications } from '@mantine/notifications';
import API from '../../api';
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import timezone from 'dayjs/plugin/timezone';

// Extend dayjs with timezone support
dayjs.extend(utc);
dayjs.extend(timezone);

const DummyEPGForm = ({ epg, isOpen, onClose }) => {
  // Separate state for each field to prevent focus loss
  const [titlePattern, setTitlePattern] = useState('');
  const [timePattern, setTimePattern] = useState('');
  const [datePattern, setDatePattern] = useState('');
  const [sampleTitle, setSampleTitle] = useState('');
  const [titleTemplate, setTitleTemplate] = useState('');
  const [descriptionTemplate, setDescriptionTemplate] = useState('');
  const [upcomingTitleTemplate, setUpcomingTitleTemplate] = useState('');
  const [upcomingDescriptionTemplate, setUpcomingDescriptionTemplate] =
    useState('');
  const [endedTitleTemplate, setEndedTitleTemplate] = useState('');
  const [endedDescriptionTemplate, setEndedDescriptionTemplate] = useState('');
  const [timezoneOptions, setTimezoneOptions] = useState([]);
  const [loadingTimezones, setLoadingTimezones] = useState(true);

  const form = useForm({
    initialValues: {
      name: '',
      is_active: true,
      source_type: 'dummy',
      custom_properties: {
        title_pattern: '',
        time_pattern: '',
        date_pattern: '',
        timezone: 'US/Eastern',
        output_timezone: '',
        program_duration: 180,
        sample_title: '',
        title_template: '',
        description_template: '',
        upcoming_title_template: '',
        upcoming_description_template: '',
        ended_title_template: '',
        ended_description_template: '',
        name_source: 'channel',
        stream_index: 1,
        category: '',
        include_date: true,
        include_live: false,
      },
    },
    validate: {
      name: (value) => (value?.trim() ? null : 'Name is required'),
      'custom_properties.title_pattern': (value) => {
        if (!value?.trim()) return 'Title pattern is required';
        try {
          new RegExp(value);
          return null;
        } catch (e) {
          return `Invalid regex: ${e.message}`;
        }
      },
      'custom_properties.name_source': (value) => {
        if (!value) return 'Name source is required';
        return null;
      },
      'custom_properties.stream_index': (value, values) => {
        if (values.custom_properties?.name_source === 'stream') {
          if (!value || value < 1) {
            return 'Stream index must be at least 1';
          }
        }
        return null;
      },
    },
  });

  // Real-time pattern validation with useMemo to prevent re-renders
  const patternValidation = useMemo(() => {
    const result = {
      titleMatch: false,
      timeMatch: false,
      dateMatch: false,
      titleGroups: {},
      timeGroups: {},
      dateGroups: {},
      formattedTitle: '',
      formattedDescription: '',
      formattedUpcomingTitle: '',
      formattedUpcomingDescription: '',
      formattedEndedTitle: '',
      formattedEndedDescription: '',
      error: null,
    };

    // Validate title pattern
    if (titlePattern && sampleTitle) {
      try {
        const titleRegex = new RegExp(titlePattern);
        const titleMatch = sampleTitle.match(titleRegex);

        if (titleMatch) {
          result.titleMatch = true;
          result.titleGroups = titleMatch.groups || {};
        }
      } catch (e) {
        result.error = `Title pattern error: ${e.message}`;
      }
    }

    // Validate time pattern
    if (timePattern && sampleTitle) {
      try {
        const timeRegex = new RegExp(timePattern);
        const timeMatch = sampleTitle.match(timeRegex);

        if (timeMatch) {
          result.timeMatch = true;
          result.timeGroups = timeMatch.groups || {};
        }
      } catch (e) {
        result.error = result.error
          ? `${result.error}; Time pattern error: ${e.message}`
          : `Time pattern error: ${e.message}`;
      }
    }

    // Validate date pattern
    if (datePattern && sampleTitle) {
      try {
        const dateRegex = new RegExp(datePattern);
        const dateMatch = sampleTitle.match(dateRegex);

        if (dateMatch) {
          result.dateMatch = true;
          result.dateGroups = dateMatch.groups || {};
        }
      } catch (e) {
        result.error = result.error
          ? `${result.error}; Date pattern error: ${e.message}`
          : `Date pattern error: ${e.message}`;
      }
    }

    // Merge all groups for template formatting
    const allGroups = {
      ...result.titleGroups,
      ...result.timeGroups,
      ...result.dateGroups,
    };

    // Calculate formatted time strings if time was extracted
    if (result.timeGroups.hour) {
      try {
        let hour24 = parseInt(result.timeGroups.hour);
        const minute = result.timeGroups.minute
          ? parseInt(result.timeGroups.minute)
          : 0;
        const ampm = result.timeGroups.ampm?.toLowerCase();

        // Convert to 24-hour if AM/PM present
        if (ampm === 'pm' && hour24 !== 12) {
          hour24 += 12;
        } else if (ampm === 'am' && hour24 === 12) {
          hour24 = 0;
        }

        // Apply timezone conversion if output_timezone is set
        const sourceTimezone = form.values.custom_properties?.timezone || 'UTC';
        const outputTimezone = form.values.custom_properties?.output_timezone;

        if (outputTimezone && outputTimezone !== sourceTimezone) {
          // Create a date in the source timezone
          const sourceDate = dayjs()
            .tz(sourceTimezone)
            .set('hour', hour24)
            .set('minute', minute)
            .set('second', 0);

          // Convert to output timezone
          const outputDate = sourceDate.tz(outputTimezone);

          // Update hour and minute to the converted values
          hour24 = outputDate.hour();
          const convertedMinute = outputDate.minute();

          // Format 24-hour time string with converted time
          if (convertedMinute > 0) {
            allGroups.time24 = `${hour24.toString().padStart(2, '0')}:${convertedMinute.toString().padStart(2, '0')}`;
          } else {
            allGroups.time24 = `${hour24.toString().padStart(2, '0')}:00`;
          }

          // Convert to 12-hour format with converted time
          const ampmDisplay = hour24 < 12 ? 'AM' : 'PM';
          let hour12 = hour24;
          if (hour24 === 0) {
            hour12 = 12;
          } else if (hour24 > 12) {
            hour12 = hour24 - 12;
          }

          // Format 12-hour time string with converted time
          if (convertedMinute > 0) {
            allGroups.time = `${hour12}:${convertedMinute.toString().padStart(2, '0')} ${ampmDisplay}`;
          } else {
            allGroups.time = `${hour12} ${ampmDisplay}`;
          }
        } else {
          // No timezone conversion - use original logic
          // Format 24-hour time string
          if (minute > 0) {
            allGroups.time24 = `${hour24.toString().padStart(2, '0')}:${minute.toString().padStart(2, '0')}`;
          } else {
            allGroups.time24 = `${hour24.toString().padStart(2, '0')}:00`;
          }

          // Convert to 12-hour format
          const ampmDisplay = hour24 < 12 ? 'AM' : 'PM';
          let hour12 = hour24;
          if (hour24 === 0) {
            hour12 = 12;
          } else if (hour24 > 12) {
            hour12 = hour24 - 12;
          }

          // Format 12-hour time string
          if (minute > 0) {
            allGroups.time = `${hour12}:${minute.toString().padStart(2, '0')} ${ampmDisplay}`;
          } else {
            allGroups.time = `${hour12} ${ampmDisplay}`;
          }
        }
      } catch (e) {
        // If parsing fails, leave time/time24 as placeholders
        console.error('Error formatting time:', e);
      }
    }

    // Format title template
    if (titleTemplate && (result.titleMatch || result.timeMatch)) {
      result.formattedTitle = titleTemplate.replace(
        /\{(\w+)\}/g,
        (match, key) => allGroups[key] || match
      );
    }

    // Format description template
    if (descriptionTemplate && (result.titleMatch || result.timeMatch)) {
      result.formattedDescription = descriptionTemplate.replace(
        /\{(\w+)\}/g,
        (match, key) => allGroups[key] || match
      );
    }

    // Format upcoming title template
    if (upcomingTitleTemplate && (result.titleMatch || result.timeMatch)) {
      result.formattedUpcomingTitle = upcomingTitleTemplate.replace(
        /\{(\w+)\}/g,
        (match, key) => allGroups[key] || match
      );
    }

    // Format upcoming description template
    if (
      upcomingDescriptionTemplate &&
      (result.titleMatch || result.timeMatch)
    ) {
      result.formattedUpcomingDescription = upcomingDescriptionTemplate.replace(
        /\{(\w+)\}/g,
        (match, key) => allGroups[key] || match
      );
    }

    // Format ended title template
    if (endedTitleTemplate && (result.titleMatch || result.timeMatch)) {
      result.formattedEndedTitle = endedTitleTemplate.replace(
        /\{(\w+)\}/g,
        (match, key) => allGroups[key] || match
      );
    }

    // Format ended description template
    if (endedDescriptionTemplate && (result.titleMatch || result.timeMatch)) {
      result.formattedEndedDescription = endedDescriptionTemplate.replace(
        /\{(\w+)\}/g,
        (match, key) => allGroups[key] || match
      );
    }

    return result;
  }, [
    titlePattern,
    timePattern,
    datePattern,
    sampleTitle,
    titleTemplate,
    descriptionTemplate,
    upcomingTitleTemplate,
    upcomingDescriptionTemplate,
    endedTitleTemplate,
    endedDescriptionTemplate,
    form.values.custom_properties?.timezone,
    form.values.custom_properties?.output_timezone,
  ]);

  useEffect(() => {
    if (epg) {
      const custom = epg.custom_properties || {};

      form.setValues({
        name: epg.name || '',
        is_active: epg.is_active ?? true,
        source_type: 'dummy',
        custom_properties: {
          title_pattern: custom.title_pattern || '',
          time_pattern: custom.time_pattern || '',
          date_pattern: custom.date_pattern || '',
          timezone:
            custom.timezone ||
            custom.timezone_offset?.toString() ||
            'US/Eastern',
          output_timezone: custom.output_timezone || '',
          program_duration: custom.program_duration || 180,
          sample_title: custom.sample_title || '',
          title_template: custom.title_template || '',
          description_template: custom.description_template || '',
          upcoming_title_template: custom.upcoming_title_template || '',
          upcoming_description_template:
            custom.upcoming_description_template || '',
          ended_title_template: custom.ended_title_template || '',
          ended_description_template: custom.ended_description_template || '',
          name_source: custom.name_source || 'channel',
          stream_index: custom.stream_index || 1,
          category: custom.category || '',
          include_date: custom.include_date ?? true,
          include_live: custom.include_live ?? false,
        },
      });

      // Set controlled state
      setTitlePattern(custom.title_pattern || '');
      setTimePattern(custom.time_pattern || '');
      setDatePattern(custom.date_pattern || '');
      setSampleTitle(custom.sample_title || '');
      setTitleTemplate(custom.title_template || '');
      setDescriptionTemplate(custom.description_template || '');
      setUpcomingTitleTemplate(custom.upcoming_title_template || '');
      setUpcomingDescriptionTemplate(
        custom.upcoming_description_template || ''
      );
      setEndedTitleTemplate(custom.ended_title_template || '');
      setEndedDescriptionTemplate(custom.ended_description_template || '');
    } else {
      form.reset();
      setTitlePattern('');
      setTimePattern('');
      setDatePattern('');
      setSampleTitle('');
      setTitleTemplate('');
      setDescriptionTemplate('');
      setUpcomingTitleTemplate('');
      setUpcomingDescriptionTemplate('');
      setEndedTitleTemplate('');
      setEndedDescriptionTemplate('');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [epg]);

  // Fetch available timezones from the API
  useEffect(() => {
    const fetchTimezones = async () => {
      try {
        setLoadingTimezones(true);
        const response = await API.getTimezones();

        // Convert timezone list to Select options format
        const options = response.timezones.map((tz) => ({
          value: tz,
          label: tz,
        }));

        setTimezoneOptions(options);
      } catch (error) {
        console.error('Failed to load timezones:', error);
        notifications.show({
          title: 'Warning',
          message: 'Failed to load timezone list. Using default options.',
          color: 'yellow',
        });
        // Fallback to a minimal list
        setTimezoneOptions([
          { value: 'UTC', label: 'UTC' },
          { value: 'US/Eastern', label: 'US/Eastern' },
          { value: 'US/Central', label: 'US/Central' },
          { value: 'US/Pacific', label: 'US/Pacific' },
        ]);
      } finally {
        setLoadingTimezones(false);
      }
    };

    fetchTimezones();
  }, []);

  const handleSubmit = async (values) => {
    try {
      if (epg?.id) {
        await API.updateEPG({ ...values, id: epg.id });
        notifications.show({
          title: 'Success',
          message: 'Dummy EPG source updated successfully',
          color: 'green',
        });
      } else {
        await API.addEPG(values);
        notifications.show({
          title: 'Success',
          message: 'Dummy EPG source created successfully',
          color: 'green',
        });
      }
      onClose();
    } catch (error) {
      notifications.show({
        title: 'Error',
        message: error.message || 'Failed to save dummy EPG source',
        color: 'red',
      });
    }
  };

  return (
    <Modal
      opened={isOpen}
      onClose={onClose}
      title={epg ? 'Edit Dummy EPG Source' : 'Create Dummy EPG Source'}
      size="xl"
    >
      <form onSubmit={form.onSubmit(handleSubmit)}>
        <Stack spacing="md">
          {/* Basic Settings */}
          <TextInput
            label="Name"
            placeholder="My Sports EPG"
            required
            {...form.getInputProps('name')}
          />

          {/* Pattern Configuration */}
          <Divider label="Pattern Configuration" labelPosition="center" />

          <Text size="sm" c="dimmed">
            Define regex patterns to extract information from channel titles or
            stream names. Use named capture groups like
            (?&lt;groupname&gt;pattern).
          </Text>

          <Select
            label="Name Source"
            description="Choose whether to parse the channel name or a stream name assigned to the channel"
            required
            data={[
              { value: 'channel', label: 'Channel Name' },
              { value: 'stream', label: 'Stream Name' },
            ]}
            {...form.getInputProps('custom_properties.name_source')}
          />

          {form.values.custom_properties?.name_source === 'stream' && (
            <NumberInput
              label="Stream Index"
              description="Which stream to use (1 = first stream, 2 = second stream, etc.)"
              placeholder="1"
              min={1}
              max={100}
              {...form.getInputProps('custom_properties.stream_index')}
            />
          )}

          <TextInput
            id="title_pattern"
            name="title_pattern"
            label="Title Pattern"
            description="Regex pattern to extract title information (e.g., team names, league). Example: (?<league>\w+) \d+: (?<team1>.*) VS (?<team2>.*)"
            placeholder="(?<league>\w+) \d+: (?<team1>.*) VS (?<team2>.*)"
            required
            value={titlePattern}
            onChange={(e) => {
              const value = e.target.value;
              setTitlePattern(value);
              form.setFieldValue('custom_properties.title_pattern', value);
            }}
            error={form.errors['custom_properties.title_pattern']}
          />

          <TextInput
            id="time_pattern"
            name="time_pattern"
            label="Time Pattern (Optional)"
            description="Extract time from channel titles. Required groups: 'hour' (1-12 or 0-23), 'minute' (0-59), 'ampm' (AM/PM - optional for 24-hour). Examples: @ (?<hour>\d+):(?<minute>\d+)(?<ampm>AM|PM) for '8:30PM' OR @ (?<hour>\d{1,2}):(?<minute>\d{2}) for '20:30'"
            placeholder="@ (?<hour>\d+):(?<minute>\d+)(?<ampm>AM|PM)"
            value={timePattern}
            onChange={(e) => {
              const value = e.target.value;
              setTimePattern(value);
              form.setFieldValue('custom_properties.time_pattern', value);
            }}
          />

          <TextInput
            id="date_pattern"
            name="date_pattern"
            label="Date Pattern (Optional)"
            description="Extract date from channel titles. Groups: 'month' (name or number), 'day', 'year' (optional, defaults to current year). Examples: @ (?<month>\w+) (?<day>\d+) for 'Oct 17' OR (?<month>\d+)/(?<day>\d+)/(?<year>\d+) for '10/17/2025'"
            placeholder="@ (?<month>\w+) (?<day>\d+)"
            value={datePattern}
            onChange={(e) => {
              const value = e.target.value;
              setDatePattern(value);
              form.setFieldValue('custom_properties.date_pattern', value);
            }}
          />

          {/* Output Templates */}
          <Divider label="Output Templates (Optional)" labelPosition="center" />

          <Text size="sm" c="dimmed">
            Use extracted groups from your patterns to format EPG titles and
            descriptions. Reference groups using {'{groupname}'} syntax.
          </Text>

          <TextInput
            id="title_template"
            name="title_template"
            label="Title Template"
            description="Format the EPG title using extracted groups. Use {time} (12-hour: '10 PM') or {time24} (24-hour: '22:00'). Example: {league} - {team1} vs {team2} @ {time}"
            placeholder="{league} - {team1} vs {team2}"
            value={titleTemplate}
            onChange={(e) => {
              const value = e.target.value;
              setTitleTemplate(value);
              form.setFieldValue('custom_properties.title_template', value);
            }}
          />

          <Textarea
            id="description_template"
            name="description_template"
            label="Description Template"
            description="Format the EPG description using extracted groups. Use {time} (12-hour) or {time24} (24-hour). Example: Watch {team1} take on {team2} at {time}!"
            placeholder="Watch {team1} take on {team2} in this exciting {league} matchup at {time}!"
            minRows={2}
            value={descriptionTemplate}
            onChange={(e) => {
              const value = e.target.value;
              setDescriptionTemplate(value);
              form.setFieldValue(
                'custom_properties.description_template',
                value
              );
            }}
          />

          {/* Upcoming/Ended Templates */}
          <Divider
            label="Upcoming/Ended Templates (Optional)"
            labelPosition="center"
          />

          <Text size="sm" c="dimmed">
            Customize how programs appear before and after the event. If left
            empty, will use the main title/description with "Upcoming:" or
            "Ended:" prefix.
          </Text>

          <TextInput
            id="upcoming_title_template"
            name="upcoming_title_template"
            label="Upcoming Title Template"
            description="Title for programs before the event starts. Use {time} (12-hour) or {time24} (24-hour). Example: {team1} vs {team2} starting at {time}."
            placeholder="{team1} vs {team2} starting at {time}."
            value={upcomingTitleTemplate}
            onChange={(e) => {
              const value = e.target.value;
              setUpcomingTitleTemplate(value);
              form.setFieldValue(
                'custom_properties.upcoming_title_template',
                value
              );
            }}
          />

          <Textarea
            id="upcoming_description_template"
            name="upcoming_description_template"
            label="Upcoming Description Template"
            description="Description for programs before the event. Use {time} (12-hour) or {time24} (24-hour). Example: Upcoming: Watch the {league} match up where the {team1} take on the {team2} at {time}!"
            placeholder="Upcoming: Watch the {league} match up where the {team1} take on the {team2} at {time}!"
            minRows={2}
            value={upcomingDescriptionTemplate}
            onChange={(e) => {
              const value = e.target.value;
              setUpcomingDescriptionTemplate(value);
              form.setFieldValue(
                'custom_properties.upcoming_description_template',
                value
              );
            }}
          />

          <TextInput
            id="ended_title_template"
            name="ended_title_template"
            label="Ended Title Template"
            description="Title for programs after the event has ended. Use {time} (12-hour) or {time24} (24-hour). Example: {team1} vs {team2} started at {time}."
            placeholder="{team1} vs {team2} started at {time}."
            value={endedTitleTemplate}
            onChange={(e) => {
              const value = e.target.value;
              setEndedTitleTemplate(value);
              form.setFieldValue(
                'custom_properties.ended_title_template',
                value
              );
            }}
          />

          <Textarea
            id="ended_description_template"
            name="ended_description_template"
            label="Ended Description Template"
            description="Description for programs after the event. Use {time} (12-hour) or {time24} (24-hour). Example: The {league} match between {team1} and {team2} started at {time}."
            placeholder="The {league} match between {team1} and {team2} started at {time}."
            minRows={2}
            value={endedDescriptionTemplate}
            onChange={(e) => {
              const value = e.target.value;
              setEndedDescriptionTemplate(value);
              form.setFieldValue(
                'custom_properties.ended_description_template',
                value
              );
            }}
          />

          {/* EPG Settings */}
          <Divider label="EPG Settings" labelPosition="center" />

          <Select
            label="Event Timezone"
            description="The timezone of the event times in your channel titles. DST (Daylight Saving Time) is handled automatically! All timezones supported by pytz are available."
            placeholder={
              loadingTimezones ? 'Loading timezones...' : 'Select timezone'
            }
            data={timezoneOptions}
            searchable
            disabled={loadingTimezones}
            {...form.getInputProps('custom_properties.timezone')}
          />

          <Select
            label="Output Timezone (Optional)"
            description="Display times in a different timezone than the event timezone. Leave empty to use the event timezone. Example: Event at 10 PM ET displayed as 9 PM CT."
            placeholder="Same as event timezone"
            data={timezoneOptions}
            searchable
            clearable
            disabled={loadingTimezones}
            {...form.getInputProps('custom_properties.output_timezone')}
          />

          <NumberInput
            label="Program Duration (minutes)"
            description="Default duration for each program"
            placeholder="180"
            min={1}
            max={1440}
            {...form.getInputProps('custom_properties.program_duration')}
          />

          <TextInput
            label="Categories (Optional)"
            description="EPG categories for these programs. Use commas to separate multiple (e.g., Sports, Live, HD). Note: Only added to the main event, not upcoming/ended filler programs."
            placeholder="Sports, Live"
            {...form.getInputProps('custom_properties.category')}
          />

          <Checkbox
            label="Include Date Tag"
            description="Include the <date> tag in EPG output with the program's start date (YYYY-MM-DD format). Added to all programs."
            {...form.getInputProps('custom_properties.include_date', {
              type: 'checkbox',
            })}
          />

          <Checkbox
            label="Include Live Tag"
            description="Mark programs as live content with the <live /> tag in EPG output. Note: Only added to the main event, not upcoming/ended filler programs."
            {...form.getInputProps('custom_properties.include_live', {
              type: 'checkbox',
            })}
          />

          {/* Testing & Preview */}
          <Divider label="Test Your Configuration" labelPosition="center" />

          <Text size="sm" c="dimmed">
            Test your patterns and templates with a sample{' '}
            {form.values.custom_properties?.name_source === 'stream'
              ? 'stream name'
              : 'channel name'}{' '}
            to preview the output.
          </Text>

          <TextInput
            id="sample_title"
            name="sample_title"
            label={`Sample ${form.values.custom_properties?.name_source === 'stream' ? 'Stream' : 'Channel'} Name`}
            description={`Enter a sample ${form.values.custom_properties?.name_source === 'stream' ? 'stream name' : 'channel name'} to test pattern matching and see the formatted output`}
            placeholder="League 01: Team 1 VS Team 2 @ Oct 17 8:00PM ET"
            value={sampleTitle}
            onChange={(e) => {
              const value = e.target.value;
              setSampleTitle(value);
              form.setFieldValue('custom_properties.sample_title', value);
            }}
          />

          {/* Pattern validation preview */}
          {sampleTitle && (titlePattern || timePattern || datePattern) && (
            <Box
              p="md"
              style={{
                backgroundColor: 'var(--mantine-color-dark-6)',
                borderRadius: 'var(--mantine-radius-default)',
                border: patternValidation.error
                  ? '1px solid var(--mantine-color-red-5)'
                  : '1px solid var(--mantine-color-dark-4)',
              }}
            >
              <Stack spacing="xs">
                {patternValidation.error && (
                  <Text size="sm" c="red">
                    {patternValidation.error}
                  </Text>
                )}

                {patternValidation.titleMatch && (
                  <Box>
                    <Text size="sm" fw={500} mb={4}>
                      Title Pattern Matched!
                    </Text>
                    <Group spacing="xs" style={{ flexWrap: 'wrap' }}>
                      {Object.entries(patternValidation.titleGroups).map(
                        ([key, value]) => (
                          <Box
                            key={key}
                            px="xs"
                            py={2}
                            style={{
                              backgroundColor: 'var(--mantine-color-blue-6)',
                              borderRadius: 'var(--mantine-radius-sm)',
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '4px',
                            }}
                          >
                            <Text size="xs" c="dark.9">
                              {key}:
                            </Text>
                            <Text size="xs" fw={600} c="dark.9">
                              {value}
                            </Text>
                          </Box>
                        )
                      )}
                    </Group>
                  </Box>
                )}

                {!patternValidation.titleMatch &&
                  titlePattern &&
                  !patternValidation.error && (
                    <Text size="sm" c="yellow">
                      Title pattern did not match the sample title
                    </Text>
                  )}

                {patternValidation.timeMatch && (
                  <Box mt="xs">
                    <Text size="sm" fw={500} mb={4}>
                      Time Pattern Matched!
                    </Text>
                    <Group spacing="xs" style={{ flexWrap: 'wrap' }}>
                      {Object.entries(patternValidation.timeGroups).map(
                        ([key, value]) => (
                          <Box
                            key={key}
                            px="xs"
                            py={2}
                            style={{
                              backgroundColor: 'var(--mantine-color-blue-6)',
                              borderRadius: 'var(--mantine-radius-sm)',
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '4px',
                            }}
                          >
                            <Text size="xs" c="dark.9">
                              {key}:
                            </Text>
                            <Text size="xs" fw={600} c="dark.9">
                              {value}
                            </Text>
                          </Box>
                        )
                      )}
                    </Group>
                  </Box>
                )}

                {!patternValidation.timeMatch &&
                  timePattern &&
                  !patternValidation.error && (
                    <Text size="sm" c="yellow">
                      Time pattern did not match the sample title
                    </Text>
                  )}

                {patternValidation.dateMatch && (
                  <Box mt="xs">
                    <Text size="sm" fw={500} mb={4}>
                      Date Pattern Matched!
                    </Text>
                    <Group spacing="xs" style={{ flexWrap: 'wrap' }}>
                      {Object.entries(patternValidation.dateGroups).map(
                        ([key, value]) => (
                          <Box
                            key={key}
                            px="xs"
                            py={2}
                            style={{
                              backgroundColor: 'var(--mantine-color-blue-6)',
                              borderRadius: 'var(--mantine-radius-sm)',
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '4px',
                            }}
                          >
                            <Text size="xs" c="dark.9">
                              {key}:
                            </Text>
                            <Text size="xs" fw={600} c="dark.9">
                              {value}
                            </Text>
                          </Box>
                        )
                      )}
                    </Group>
                  </Box>
                )}

                {!patternValidation.dateMatch &&
                  datePattern &&
                  !patternValidation.error && (
                    <Text size="sm" c="yellow">
                      Date pattern did not match the sample title
                    </Text>
                  )}

                {/* Output Preview */}
                {(patternValidation.titleMatch ||
                  patternValidation.timeMatch ||
                  patternValidation.dateMatch) && (
                  <>
                    <Divider label="Formatted Output Preview" mt="md" />

                    {form.values.custom_properties?.output_timezone && (
                      <Text size="xs" c="blue" mb="xs">
                        ✓ Times are shown converted from{' '}
                        {form.values.custom_properties?.timezone || 'UTC'} to{' '}
                        {form.values.custom_properties?.output_timezone}
                      </Text>
                    )}

                    {titleTemplate && (
                      <>
                        <Text size="xs" c="dimmed">
                          EPG Title:
                        </Text>
                        <Text size="sm" fw={500}>
                          {patternValidation.formattedTitle ||
                            '(no template provided)'}
                        </Text>
                      </>
                    )}

                    {descriptionTemplate && (
                      <>
                        <Text size="xs" c="dimmed" mt="xs">
                          EPG Description:
                        </Text>
                        <Text size="sm" fw={500}>
                          {patternValidation.formattedDescription ||
                            '(no matching groups)'}
                        </Text>
                      </>
                    )}

                    {upcomingTitleTemplate && (
                      <>
                        <Text size="xs" c="dimmed" mt="md">
                          Upcoming Title (before event):
                        </Text>
                        <Text size="sm" fw={500}>
                          {patternValidation.formattedUpcomingTitle ||
                            '(no matching groups)'}
                        </Text>
                      </>
                    )}

                    {upcomingDescriptionTemplate && (
                      <>
                        <Text size="xs" c="dimmed" mt="xs">
                          Upcoming Description (before event):
                        </Text>
                        <Text size="sm" fw={500}>
                          {patternValidation.formattedUpcomingDescription ||
                            '(no matching groups)'}
                        </Text>
                      </>
                    )}

                    {endedTitleTemplate && (
                      <>
                        <Text size="xs" c="dimmed" mt="md">
                          Ended Title (after event):
                        </Text>
                        <Text size="sm" fw={500}>
                          {patternValidation.formattedEndedTitle ||
                            '(no matching groups)'}
                        </Text>
                      </>
                    )}

                    {endedDescriptionTemplate && (
                      <>
                        <Text size="xs" c="dimmed" mt="xs">
                          Ended Description (after event):
                        </Text>
                        <Text size="sm" fw={500}>
                          {patternValidation.formattedEndedDescription ||
                            '(no matching groups)'}
                        </Text>
                      </>
                    )}

                    {!titleTemplate &&
                      !descriptionTemplate &&
                      !upcomingTitleTemplate &&
                      !upcomingDescriptionTemplate &&
                      !endedTitleTemplate &&
                      !endedDescriptionTemplate && (
                        <Text size="xs" c="dimmed" fs="italic">
                          Add title or description templates above to see
                          formatted output preview
                        </Text>
                      )}
                  </>
                )}
              </Stack>
            </Box>
          )}

          <Group justify="flex-end" mt="md">
            <Button variant="default" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit">{epg ? 'Update' : 'Create'}</Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
};

export default DummyEPGForm;
