import React, { useEffect, useMemo, useState } from 'react';
import {
  Box,
  Button,
  Checkbox,
  Divider,
  Group,
  Modal,
  NumberInput,
  Paper,
  Select,
  Stack,
  Text,
  TextInput,
  Textarea,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { notifications } from '@mantine/notifications';
import API from '../../api';
import useEPGsStore from '../../store/epgs';
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import timezone from 'dayjs/plugin/timezone';

// Extend dayjs with timezone support
dayjs.extend(utc);
dayjs.extend(timezone);

const DummyEPGForm = ({ epg, isOpen, onClose }) => {
  // Get all EPGs from the store
  const epgs = useEPGsStore((state) => state.epgs);

  // Filter for dummy EPG sources only
  const dummyEpgs = useMemo(() => {
    return Object.values(epgs)
      .filter((e) => e.source_type === 'dummy')
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [epgs]);

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
  const [fallbackTitleTemplate, setFallbackTitleTemplate] = useState('');
  const [fallbackDescriptionTemplate, setFallbackDescriptionTemplate] =
    useState('');
  const [channelLogoUrl, setChannelLogoUrl] = useState('');
  const [programPosterUrl, setProgramPosterUrl] = useState('');
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
        fallback_title_template: '',
        fallback_description_template: '',
        channel_logo_url: '',
        program_poster_url: '',
        name_source: 'channel',
        stream_index: 1,
        category: '',
        include_date: true,
        include_live: false,
        include_new: false,
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
      calculatedPlaceholders: {},
      formattedTitle: '',
      formattedDescription: '',
      formattedUpcomingTitle: '',
      formattedUpcomingDescription: '',
      formattedEndedTitle: '',
      formattedEndedDescription: '',
      formattedChannelLogoUrl: '',
      formattedProgramPosterUrl: '',
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

    // Add normalized versions of all groups for cleaner URLs
    // These remove all non-alphanumeric characters and convert to lowercase
    Object.keys(allGroups).forEach((key) => {
      const value = allGroups[key];
      if (value) {
        // Remove all non-alphanumeric characters (except spaces temporarily)
        // then replace spaces with nothing, and convert to lowercase
        const normalized = String(value)
          .replace(/[^a-zA-Z0-9\s]/g, '')
          .replace(/\s+/g, '')
          .toLowerCase();
        allGroups[`${key}_normalize`] = normalized;
      }
    });

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

        // Determine the base date to use
        let baseDate = dayjs().tz(sourceTimezone);

        // If date was extracted from pattern, use that instead of today
        if (result.dateGroups.month && result.dateGroups.day) {
          const monthValue = result.dateGroups.month;
          let extractedMonth;

          // Parse month - can be numeric (1-12) or text (Jan, January, Oct, October, etc.)
          if (/^\d+$/.test(monthValue)) {
            // Numeric month
            extractedMonth = parseInt(monthValue);
          } else {
            // Text month - convert to number (1-12)
            const monthLower = monthValue.toLowerCase();
            const monthNames = [
              'january',
              'february',
              'march',
              'april',
              'may',
              'june',
              'july',
              'august',
              'september',
              'october',
              'november',
              'december',
            ];
            const monthAbbr = [
              'jan',
              'feb',
              'mar',
              'apr',
              'may',
              'jun',
              'jul',
              'aug',
              'sep',
              'oct',
              'nov',
              'dec',
            ];

            // Try full month names first
            let monthIndex = monthNames.findIndex((m) => m === monthLower);
            if (monthIndex === -1) {
              // Try abbreviated month names
              monthIndex = monthAbbr.findIndex((m) => m === monthLower);
            }

            if (monthIndex !== -1) {
              extractedMonth = monthIndex + 1; // Convert 0-indexed to 1-12
            } else {
              // If we can't parse it, default to current month
              extractedMonth = dayjs().month() + 1;
            }
          }

          const extractedDay = parseInt(result.dateGroups.day);
          const extractedYear = result.dateGroups.year
            ? parseInt(result.dateGroups.year)
            : dayjs().year(); // Default to current year if not provided

          // Validate that we have valid numeric values
          if (
            !isNaN(extractedMonth) &&
            !isNaN(extractedDay) &&
            !isNaN(extractedYear) &&
            extractedMonth >= 1 &&
            extractedMonth <= 12 &&
            extractedDay >= 1 &&
            extractedDay <= 31
          ) {
            // Create a specific date string and parse it in the source timezone
            // This ensures DST is calculated correctly for the target date
            const dateString = `${extractedYear}-${extractedMonth.toString().padStart(2, '0')}-${extractedDay.toString().padStart(2, '0')}`;
            baseDate = dayjs.tz(dateString, sourceTimezone);
          }
        }

        if (outputTimezone && outputTimezone !== sourceTimezone) {
          // Create a date in the source timezone with extracted or current date
          // Set the time on the date, which will use the DST rules for that specific date
          const sourceDate = baseDate
            .set('hour', hour24)
            .set('minute', minute)
            .set('second', 0);

          // Convert to output timezone
          const outputDate = sourceDate.tz(outputTimezone);

          // Update hour and minute to the converted values
          hour24 = outputDate.hour();
          const convertedMinute = outputDate.minute();

          // Add date placeholders based on the OUTPUT timezone
          // This ensures {date}, {month}, {day}, {year} reflect the converted timezone
          allGroups.date = outputDate.format('YYYY-MM-DD');
          allGroups.month = outputDate.month() + 1; // dayjs months are 0-indexed
          allGroups.day = outputDate.date();
          allGroups.year = outputDate.year();

          // Format 24-hour start time string with converted time
          if (convertedMinute > 0) {
            allGroups.starttime24 = `${hour24.toString().padStart(2, '0')}:${convertedMinute.toString().padStart(2, '0')}`;
          } else {
            allGroups.starttime24 = `${hour24.toString().padStart(2, '0')}:00`;
          }

          // Convert to 12-hour format with converted time
          const ampmDisplay = hour24 < 12 ? 'AM' : 'PM';
          let hour12 = hour24;
          if (hour24 === 0) {
            hour12 = 12;
          } else if (hour24 > 12) {
            hour12 = hour24 - 12;
          }

          // Format 12-hour start time string with converted time
          if (convertedMinute > 0) {
            allGroups.starttime = `${hour12}:${convertedMinute.toString().padStart(2, '0')} ${ampmDisplay}`;
          } else {
            allGroups.starttime = `${hour12} ${ampmDisplay}`;
          }

          // Format long versions that always include minutes
          allGroups.starttime_long = `${hour12}:${convertedMinute.toString().padStart(2, '0')} ${ampmDisplay}`;
          allGroups.starttime24_long = `${hour24.toString().padStart(2, '0')}:${convertedMinute.toString().padStart(2, '0')}`;
        } else {
          // No timezone conversion - use original logic
          // Add date placeholders based on the source timezone
          const sourceDate = baseDate
            .set('hour', hour24)
            .set('minute', minute)
            .set('second', 0);

          allGroups.date = sourceDate.format('YYYY-MM-DD');
          allGroups.month = sourceDate.month() + 1; // dayjs months are 0-indexed
          allGroups.day = sourceDate.date();
          allGroups.year = sourceDate.year();

          // Format 24-hour start time string
          if (minute > 0) {
            allGroups.starttime24 = `${hour24.toString().padStart(2, '0')}:${minute.toString().padStart(2, '0')}`;
          } else {
            allGroups.starttime24 = `${hour24.toString().padStart(2, '0')}:00`;
          }

          // Convert to 12-hour format
          const ampmDisplay = hour24 < 12 ? 'AM' : 'PM';
          let hour12 = hour24;
          if (hour24 === 0) {
            hour12 = 12;
          } else if (hour24 > 12) {
            hour12 = hour24 - 12;
          }

          // Format 12-hour start time string
          if (minute > 0) {
            allGroups.starttime = `${hour12}:${minute.toString().padStart(2, '0')} ${ampmDisplay}`;
          } else {
            allGroups.starttime = `${hour12} ${ampmDisplay}`;
          }

          // Format long version that always includes minutes
          allGroups.starttime_long = `${hour12}:${minute.toString().padStart(2, '0')} ${ampmDisplay}`;
        }

        // Calculate end time based on program duration
        const programDuration =
          form.values.custom_properties?.program_duration || 180;

        // Calculate end time by adding duration to start time
        const startMinutes = hour24 * 60 + minute;
        const endMinutes = startMinutes + programDuration;

        let endHour24 = Math.floor(endMinutes / 60) % 24; // Wrap around 24 hours
        const endMinute = endMinutes % 60;

        // Format 24-hour end time string
        if (endMinute > 0) {
          allGroups.endtime24 = `${endHour24.toString().padStart(2, '0')}:${endMinute.toString().padStart(2, '0')}`;
        } else {
          allGroups.endtime24 = `${endHour24.toString().padStart(2, '0')}:00`;
        }

        // Convert to 12-hour format for endtime
        const endAmpmDisplay = endHour24 < 12 ? 'AM' : 'PM';
        let endHour12 = endHour24;
        if (endHour24 === 0) {
          endHour12 = 12;
        } else if (endHour24 > 12) {
          endHour12 = endHour24 - 12;
        }

        // Format 12-hour end time string
        if (endMinute > 0) {
          allGroups.endtime = `${endHour12}:${endMinute.toString().padStart(2, '0')} ${endAmpmDisplay}`;
        } else {
          allGroups.endtime = `${endHour12} ${endAmpmDisplay}`;
        }

        // Format long version that always includes minutes
        allGroups.endtime_long = `${endHour12}:${endMinute.toString().padStart(2, '0')} ${endAmpmDisplay}`;

        // Store calculated placeholders for display in preview
        result.calculatedPlaceholders = {
          starttime: allGroups.starttime,
          starttime24: allGroups.starttime24,
          starttime_long: allGroups.starttime_long,
          endtime: allGroups.endtime,
          endtime24: allGroups.endtime24,
          endtime_long: allGroups.endtime_long,
          date: allGroups.date,
          month: allGroups.month,
          day: allGroups.day,
          year: allGroups.year,
        };
      } catch (e) {
        // If parsing fails, leave starttime/endtime as placeholders
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

    // Format channel logo URL
    if (channelLogoUrl && (result.titleMatch || result.timeMatch)) {
      result.formattedChannelLogoUrl = channelLogoUrl.replace(
        /\{(\w+)\}/g,
        (match, key) => {
          const value = allGroups[key];
          // URL encode the value to handle spaces and special characters
          return value ? encodeURIComponent(String(value)) : match;
        }
      );
    }

    // Format program poster URL
    if (programPosterUrl && (result.titleMatch || result.timeMatch)) {
      result.formattedProgramPosterUrl = programPosterUrl.replace(
        /\{(\w+)\}/g,
        (match, key) => {
          const value = allGroups[key];
          // URL encode the value to handle spaces and special characters
          return value ? encodeURIComponent(String(value)) : match;
        }
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
    channelLogoUrl,
    programPosterUrl,
    form.values.custom_properties?.timezone,
    form.values.custom_properties?.output_timezone,
    form.values.custom_properties?.program_duration,
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
          fallback_title_template: custom.fallback_title_template || '',
          fallback_description_template:
            custom.fallback_description_template || '',
          channel_logo_url: custom.channel_logo_url || '',
          program_poster_url: custom.program_poster_url || '',
          name_source: custom.name_source || 'channel',
          stream_index: custom.stream_index || 1,
          category: custom.category || '',
          include_date: custom.include_date ?? true,
          include_live: custom.include_live ?? false,
          include_new: custom.include_new ?? false,
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
      setFallbackTitleTemplate(custom.fallback_title_template || '');
      setFallbackDescriptionTemplate(
        custom.fallback_description_template || ''
      );
      setChannelLogoUrl(custom.channel_logo_url || '');
      setProgramPosterUrl(custom.program_poster_url || '');
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
      setFallbackTitleTemplate('');
      setFallbackDescriptionTemplate('');
      setChannelLogoUrl('');
      setProgramPosterUrl('');
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

  // Function to import settings from an existing dummy EPG
  const handleImportFromTemplate = (templateId) => {
    const template = dummyEpgs.find((e) => e.id === parseInt(templateId));
    if (!template) return;

    const custom = template.custom_properties || {};

    // Update form values
    form.setValues({
      name: `${template.name} (Copy)`,
      is_active: template.is_active ?? true,
      source_type: 'dummy',
      custom_properties: {
        title_pattern: custom.title_pattern || '',
        time_pattern: custom.time_pattern || '',
        date_pattern: custom.date_pattern || '',
        timezone:
          custom.timezone || custom.timezone_offset?.toString() || 'US/Eastern',
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
        fallback_title_template: custom.fallback_title_template || '',
        fallback_description_template:
          custom.fallback_description_template || '',
        channel_logo_url: custom.channel_logo_url || '',
        program_poster_url: custom.program_poster_url || '',
        name_source: custom.name_source || 'channel',
        stream_index: custom.stream_index || 1,
        category: custom.category || '',
        include_date: custom.include_date ?? true,
        include_live: custom.include_live ?? false,
        include_new: custom.include_new ?? false,
      },
    });

    // Update all individual state variables to match
    setTitlePattern(custom.title_pattern || '');
    setTimePattern(custom.time_pattern || '');
    setDatePattern(custom.date_pattern || '');
    setSampleTitle(custom.sample_title || '');
    setTitleTemplate(custom.title_template || '');
    setDescriptionTemplate(custom.description_template || '');
    setUpcomingTitleTemplate(custom.upcoming_title_template || '');
    setUpcomingDescriptionTemplate(custom.upcoming_description_template || '');
    setEndedTitleTemplate(custom.ended_title_template || '');
    setEndedDescriptionTemplate(custom.ended_description_template || '');
    setFallbackTitleTemplate(custom.fallback_title_template || '');
    setFallbackDescriptionTemplate(custom.fallback_description_template || '');
    setChannelLogoUrl(custom.channel_logo_url || '');
    setProgramPosterUrl(custom.program_poster_url || '');

    notifications.show({
      title: 'Template Imported',
      message: `Settings imported from "${template.name}". Don't forget to change the name!`,
      color: 'blue',
    });
  };

  const handleSubmit = async (values) => {
    try {
      if (epg?.id) {
        // Validate that we have a valid EPG object before updating
        if (!epg || typeof epg !== 'object' || !epg.id) {
          notifications.show({
            title: 'Error',
            message: 'Invalid EPG data. Please close and reopen this form.',
            color: 'red',
          });
          return;
        }

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
          {/* Import from Existing - Only show when creating new */}
          {!epg && dummyEpgs.length > 0 && (
            <Paper withBorder p="md" bg="dark.6">
              <Stack spacing="xs">
                <Group justify="space-between" align="center">
                  <Text size="sm" fw={500}>
                    Import from Existing
                  </Text>
                  <Text size="xs" c="dimmed">
                    Use an existing dummy EPG as a template
                  </Text>
                </Group>
                <Select
                  placeholder="Select a template to copy settings from..."
                  data={dummyEpgs.map((e) => ({
                    value: e.id.toString(),
                    label: e.name,
                  }))}
                  onChange={handleImportFromTemplate}
                  clearable
                  searchable
                />
              </Stack>
            </Paper>
          )}

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
            descriptions. Reference groups using {'{groupname}'} syntax. For
            cleaner URLs, use {'{groupname_normalize}'} to get alphanumeric-only
            lowercase versions.
          </Text>

          <TextInput
            id="title_template"
            name="title_template"
            label="Title Template"
            description="Format the EPG title using extracted groups. Use {starttime} (12-hour: '10 PM'), {starttime24} (24-hour: '22:00'), {endtime} (12-hour end), {endtime24} (24-hour end), {date} (YYYY-MM-DD), {month}, {day}, or {year}. Date/time placeholders respect Output Timezone settings. Example: {league} - {team1} vs {team2} ({starttime}-{endtime})"
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
            description="Format the EPG description using extracted groups. Use {starttime} (12-hour), {starttime24} (24-hour), {endtime} (12-hour end), {endtime24} (24-hour end), {date} (YYYY-MM-DD), {month}, {day}, or {year}. Date/time placeholders respect Output Timezone settings. Example: Watch {team1} take on {team2} on {date} from {starttime} to {endtime}!"
            placeholder="Watch {team1} take on {team2} in this exciting {league} matchup from {starttime} to {endtime}!"
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
            description="Title for programs before the event starts. Use {starttime} (12-hour), {starttime24} (24-hour), {endtime} (12-hour end), {endtime24} (24-hour end), {date} (YYYY-MM-DD), {month}, {day}, or {year}. Date/time placeholders respect Output Timezone settings. Example: {team1} vs {team2} starting at {starttime}."
            placeholder="{team1} vs {team2} starting at {starttime}."
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
            description="Description for programs before the event. Use {starttime} (12-hour), {starttime24} (24-hour), {endtime} (12-hour end), {endtime24} (24-hour end), {date} (YYYY-MM-DD), {month}, {day}, or {year}. Date/time placeholders respect Output Timezone settings. Example: Upcoming: Watch the {league} match up where the {team1} take on the {team2} on {date} from {starttime} to {endtime}!"
            placeholder="Upcoming: Watch the {league} match up where the {team1} take on the {team2} from {starttime} to {endtime}!"
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
            description="Title for programs after the event has ended. Use {starttime} (12-hour), {starttime24} (24-hour), {endtime} (12-hour end), {endtime24} (24-hour end), {date} (YYYY-MM-DD), {month}, {day}, or {year}. Date/time placeholders respect Output Timezone settings. Example: {team1} vs {team2} started at {starttime}."
            placeholder="{team1} vs {team2} started at {starttime}."
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
            description="Description for programs after the event. Use {starttime} (12-hour), {starttime24} (24-hour), {endtime} (12-hour end), {endtime24} (24-hour end), {date} (YYYY-MM-DD), {month}, {day}, or {year}. Date/time placeholders respect Output Timezone settings. Example: The {league} match between {team1} and {team2} on {date} ran from {starttime} to {endtime}."
            placeholder="The {league} match between {team1} and {team2} ran from {starttime} to {endtime}."
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

          {/* Fallback Templates */}
          <Divider
            label="Fallback Templates (Optional)"
            labelPosition="center"
          />

          <Text size="sm" c="dimmed">
            When patterns don't match the channel/stream name, use these custom
            fallback templates instead of the default placeholder messages.
            Leave empty to use the built-in humorous fallback descriptions.
          </Text>

          <TextInput
            id="fallback_title_template"
            name="fallback_title_template"
            label="Fallback Title Template"
            description="Custom title when patterns don't match. If empty, uses the channel/stream name."
            placeholder="No EPG data available"
            value={fallbackTitleTemplate}
            onChange={(e) => {
              const value = e.target.value;
              setFallbackTitleTemplate(value);
              form.setFieldValue(
                'custom_properties.fallback_title_template',
                value
              );
            }}
          />

          <Textarea
            id="fallback_description_template"
            name="fallback_description_template"
            label="Fallback Description Template"
            description="Custom description when patterns don't match. If empty, uses built-in placeholder messages."
            placeholder="EPG information is currently unavailable for this channel."
            minRows={2}
            value={fallbackDescriptionTemplate}
            onChange={(e) => {
              const value = e.target.value;
              setFallbackDescriptionTemplate(value);
              form.setFieldValue(
                'custom_properties.fallback_description_template',
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

          <TextInput
            label="Channel Logo URL (Optional)"
            description="Build a URL for the channel logo using regex groups. Example: https://example.com/logos/{league_normalize}/{team1_normalize}.png. Use {groupname_normalize} for cleaner URLs (alphanumeric-only, lowercase). This will be used as the channel <icon> in the EPG output."
            placeholder="https://example.com/logos/{league_normalize}/{team1_normalize}.png"
            value={channelLogoUrl}
            onChange={(e) => {
              const value = e.target.value;
              setChannelLogoUrl(value);
              form.setFieldValue('custom_properties.channel_logo_url', value);
            }}
          />

          <TextInput
            label="Program Poster URL (Optional)"
            description="Build a URL for the program poster/icon using regex groups. Example: https://example.com/posters/{team1_normalize}-vs-{team2_normalize}.jpg. Use {groupname_normalize} for cleaner URLs (alphanumeric-only, lowercase). This will be used as the program <icon> in the EPG output."
            placeholder="https://example.com/posters/{team1_normalize}-vs-{team2_normalize}.jpg"
            value={programPosterUrl}
            onChange={(e) => {
              const value = e.target.value;
              setProgramPosterUrl(value);
              form.setFieldValue('custom_properties.program_poster_url', value);
            }}
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

          <Checkbox
            label="Include New Tag"
            description="Mark programs as new content with the <new /> tag in EPG output. Note: Only added to the main event, not upcoming/ended filler programs."
            {...form.getInputProps('custom_properties.include_new', {
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

                {/* Show calculated time placeholders when time is extracted */}
                {patternValidation.timeMatch &&
                  Object.keys(patternValidation.calculatedPlaceholders || {})
                    .length > 0 && (
                    <Box mt="xs">
                      <Text size="sm" fw={500} mb={4}>
                        Available Time Placeholders:
                      </Text>
                      <Group spacing="xs" style={{ flexWrap: 'wrap' }}>
                        {Object.entries(
                          patternValidation.calculatedPlaceholders
                        ).map(([key, value]) => (
                          <Box
                            key={key}
                            px="xs"
                            py={2}
                            style={{
                              backgroundColor: 'var(--mantine-color-green-6)',
                              borderRadius: 'var(--mantine-radius-sm)',
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '4px',
                            }}
                          >
                            <Text size="xs" c="dark.9">
                              {'{' + key + '}'}:
                            </Text>
                            <Text size="xs" fw={600} c="dark.9">
                              {value}
                            </Text>
                          </Box>
                        ))}
                      </Group>
                    </Box>
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

                    {channelLogoUrl && (
                      <>
                        <Text size="xs" c="dimmed" mt="md">
                          Channel Logo URL:
                        </Text>
                        <Text
                          size="sm"
                          fw={500}
                          style={{ wordBreak: 'break-all' }}
                        >
                          {patternValidation.formattedChannelLogoUrl ||
                            '(no matching groups)'}
                        </Text>
                      </>
                    )}

                    {programPosterUrl && (
                      <>
                        <Text size="xs" c="dimmed" mt="xs">
                          Program Poster URL:
                        </Text>
                        <Text
                          size="sm"
                          fw={500}
                          style={{ wordBreak: 'break-all' }}
                        >
                          {patternValidation.formattedProgramPosterUrl ||
                            '(no matching groups)'}
                        </Text>
                      </>
                    )}

                    {!titleTemplate &&
                      !descriptionTemplate &&
                      !upcomingTitleTemplate &&
                      !upcomingDescriptionTemplate &&
                      !endedTitleTemplate &&
                      !endedDescriptionTemplate &&
                      !channelLogoUrl &&
                      !programPosterUrl && (
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
