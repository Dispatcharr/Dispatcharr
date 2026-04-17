import React, { useEffect, useMemo, useState } from 'react';
import {
  Accordion,
  AccordionControl,
  AccordionItem,
  AccordionPanel,
  ActionIcon,
  Box,
  Button,
  Checkbox,
  Divider,
  Group,
  Modal,
  NumberInput,
  Paper,
  Popover,
  PopoverDropdown,
  PopoverTarget,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
} from '@mantine/core';
import { Info } from 'lucide-react';
import { useForm } from '@mantine/form';
import useEPGsStore from '../../store/epgs';
import { showNotification } from '../../utils/notificationUtils.js';
import {
  addEPG,
  addNormalizedGroups,
  applyTemplates,
  buildCustomProperties,
  buildTimePlaceholders,
  getDummyEpgFormInitialValues,
  getTimezones,
  matchPattern,
  updateEPG,
  validateCustomNameSource,
  validateCustomStreamIndex,
  validateCustomTitlePattern,
} from '../../utils/forms/DummyEpgUtils.js';

// Helper component for labels with info popover
const LabelWithInfo = ({ label, info, required }) => (
  <Group spacing={4} align="center">
    <Text size="sm" fw={500}>
      {label}
      {required && (
        <Text component="span" c="red" ml={4}>
          *
        </Text>
      )}
    </Text>
    <Popover width={300} position="top" withArrow shadow="md">
      <PopoverTarget>
        <ActionIcon size="xs" variant="subtle" color="gray">
          <Info size={14} />
        </ActionIcon>
      </PopoverTarget>
      <PopoverDropdown>
        <Text size="xs">{info}</Text>
      </PopoverDropdown>
    </Popover>
  </Group>
);

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
  const [subtitleTemplate, setSubtitleTemplate] = useState('');
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
    initialValues: getDummyEpgFormInitialValues(),
    validate: {
      name: (value) => (value?.trim() ? null : 'Name is required'),
      'custom_properties.title_pattern': (value) => {
        return validateCustomTitlePattern(value);
      },
      'custom_properties.name_source': (value) => {
        return validateCustomNameSource(value);
      },
      'custom_properties.stream_index': (value, values) => {
        return validateCustomStreamIndex(values, value);
      },
    },
  });

  const patternValidation = useMemo(() => {
    const title = matchPattern(
      titlePattern,
      sampleTitle,
      'Title pattern error'
    );
    const time = matchPattern(timePattern, sampleTitle, 'Time pattern error');
    const date = matchPattern(datePattern, sampleTitle, 'Date pattern error');

    const errors = [title.error, time.error, date.error]
      .filter(Boolean)
      .join('; ');

    const timePlaceholders = buildTimePlaceholders(
      time.groups,
      date.groups,
      form.values.custom_properties?.timezone || 'UTC',
      form.values.custom_properties?.output_timezone,
      form.values.custom_properties?.program_duration
    );

    const allGroups = addNormalizedGroups({
      ...title.groups,
      ...time.groups,
      ...date.groups,
      ...timePlaceholders,
    });

    const hasMatch = title.matched || time.matched;

    return {
      titleMatch: title.matched,
      timeMatch: time.matched,
      dateMatch: date.matched,
      titleGroups: title.groups,
      timeGroups: time.groups,
      dateGroups: date.groups,
      calculatedPlaceholders: time.matched ? timePlaceholders : {},
      error: errors || null,
      ...applyTemplates(
        {
          titleTemplate,
          subtitleTemplate,
          descriptionTemplate,
          upcomingTitleTemplate,
          upcomingDescriptionTemplate,
          endedTitleTemplate,
          endedDescriptionTemplate,
          channelLogoUrl,
          programPosterUrl,
        },
        allGroups,
        hasMatch
      ),
    };
  }, [
    titlePattern,
    timePattern,
    datePattern,
    sampleTitle,
    titleTemplate,
    subtitleTemplate,
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
        custom_properties: buildCustomProperties(custom),
      });
      applyCustomState(custom);
    } else {
      form.reset();
      applyCustomState(); // called with no args — all setters receive ''
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [epg]);

  // Fetch available timezones from the API
  useEffect(() => {
    const fetchTimezones = async () => {
      try {
        setLoadingTimezones(true);
        const response = await getTimezones();

        // Convert timezone list to Select options format
        const options = response.timezones.map((tz) => ({
          value: tz,
          label: tz,
        }));

        setTimezoneOptions(options);
      } catch (error) {
        console.error('Failed to load timezones:', error);
        showNotification({
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

  const applyCustomState = (custom = {}) => {
    setTitlePattern(custom.title_pattern || '');
    setTimePattern(custom.time_pattern || '');
    setDatePattern(custom.date_pattern || '');
    setSampleTitle(custom.sample_title || '');
    setTitleTemplate(custom.title_template || '');
    setSubtitleTemplate(custom.subtitle_template || '');
    setDescriptionTemplate(custom.description_template || '');
    setUpcomingTitleTemplate(custom.upcoming_title_template || '');
    setUpcomingDescriptionTemplate(custom.upcoming_description_template || '');
    setEndedTitleTemplate(custom.ended_title_template || '');
    setEndedDescriptionTemplate(custom.ended_description_template || '');
    setFallbackTitleTemplate(custom.fallback_title_template || '');
    setFallbackDescriptionTemplate(custom.fallback_description_template || '');
    setChannelLogoUrl(custom.channel_logo_url || '');
    setProgramPosterUrl(custom.program_poster_url || '');
  };

  // Function to import settings from an existing dummy EPG
  const handleImportFromTemplate = (templateId) => {
    const template = dummyEpgs.find((e) => e.id === parseInt(templateId));
    if (!template) return;

    const custom = template.custom_properties || {};
    form.setValues({
      name: `${template.name} (Copy)`,
      is_active: template.is_active ?? true,
      source_type: 'dummy',
      custom_properties: buildCustomProperties(custom),
    });
    applyCustomState(custom);

    showNotification({
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
          showNotification({
            title: 'Error',
            message: 'Invalid EPG data. Please close and reopen this form.',
            color: 'red',
          });
          return;
        }

        await updateEPG(values, epg);
        showNotification({
          title: 'Success',
          message: 'Dummy EPG source updated successfully',
          color: 'green',
        });
      } else {
        await addEPG(values);
        showNotification({
          title: 'Success',
          message: 'Dummy EPG source created successfully',
          color: 'green',
        });
      }
      onClose();
    } catch (error) {
      showNotification({
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

          {/* Accordion for organized sections */}
          <Accordion defaultValue="patterns" variant="separated">
            <AccordionItem value="patterns">
              <AccordionControl>Pattern Configuration</AccordionControl>
              <AccordionPanel>
                <Stack spacing="md">
                  <Text size="sm" c="dimmed">
                    Define regex patterns to extract information from channel
                    titles or stream names. Use named capture groups like
                    (?&lt;groupname&gt;pattern).
                  </Text>

                  <Select
                    label={
                      <LabelWithInfo
                        label="Name Source"
                        info="Choose whether to parse the channel name or a stream name assigned to the channel"
                        required
                      />
                    }
                    required
                    withAsterisk={false}
                    data={[
                      { value: 'channel', label: 'Channel Name' },
                      { value: 'stream', label: 'Stream Name' },
                    ]}
                    {...form.getInputProps('custom_properties.name_source')}
                  />

                  {form.values.custom_properties?.name_source === 'stream' && (
                    <NumberInput
                      label={
                        <LabelWithInfo
                          label="Stream Index"
                          info="Which stream to use (1 = first stream, 2 = second stream, etc.)"
                        />
                      }
                      placeholder="1"
                      min={1}
                      max={100}
                      {...form.getInputProps('custom_properties.stream_index')}
                    />
                  )}

                  <TextInput
                    id="title_pattern"
                    name="title_pattern"
                    label={
                      <LabelWithInfo
                        label="Title Pattern"
                        info="Regex pattern to extract title information (e.g., team names, league). Example: (?<league>\w+) \d+: (?<team1>.*) VS (?<team2>.*)"
                        required
                      />
                    }
                    placeholder="(?<league>\w+) \d+: (?<team1>.*) VS (?<team2>.*)"
                    required
                    withAsterisk={false}
                    value={titlePattern}
                    onChange={(e) => {
                      const value = e.target.value;
                      setTitlePattern(value);
                      form.setFieldValue(
                        'custom_properties.title_pattern',
                        value
                      );
                    }}
                    error={form.errors['custom_properties.title_pattern']}
                  />

                  <TextInput
                    id="time_pattern"
                    name="time_pattern"
                    label={
                      <LabelWithInfo
                        label="Time Pattern (Optional)"
                        info="Extract time from channel titles. Required groups: 'hour' (1-12 or 0-23), 'minute' (0-59), 'ampm' (AM/PM - optional for 24-hour). Examples: @ (?<hour>\d+):(?<minute>\d+)(?<ampm>AM|PM) for '8:30PM' OR @ (?<hour>\d{1,2}):(?<minute>\d{2}) for '20:30'"
                      />
                    }
                    placeholder="@ (?<hour>\d+):(?<minute>\d+)(?<ampm>AM|PM)"
                    value={timePattern}
                    onChange={(e) => {
                      const value = e.target.value;
                      setTimePattern(value);
                      form.setFieldValue(
                        'custom_properties.time_pattern',
                        value
                      );
                    }}
                  />

                  <TextInput
                    id="date_pattern"
                    name="date_pattern"
                    label={
                      <LabelWithInfo
                        label="Date Pattern (Optional)"
                        info="Extract date from channel titles. Groups: 'month' (name or number), 'day', 'year' (optional, defaults to current year). Examples: @ (?<month>\w+) (?<day>\d+) for 'Oct 17' OR (?<month>\d+)/(?<day>\d+)/(?<year>\d+) for '10/17/2025'"
                      />
                    }
                    placeholder="@ (?<month>\w+) (?<day>\d+)"
                    value={datePattern}
                    onChange={(e) => {
                      const value = e.target.value;
                      setDatePattern(value);
                      form.setFieldValue(
                        'custom_properties.date_pattern',
                        value
                      );
                    }}
                  />
                </Stack>
              </AccordionPanel>
            </AccordionItem>

            <AccordionItem value="templates">
              <AccordionControl>Output Templates</AccordionControl>
              <AccordionPanel>
                <Stack spacing="md">
                  <Text size="sm" c="dimmed">
                    Use extracted groups from your patterns to format EPG titles
                    and descriptions. Reference groups using {'{groupname}'}{' '}
                    syntax. For cleaner URLs, use {'{groupname_normalize}'} to
                    get alphanumeric-only lowercase versions.
                  </Text>

                  <TextInput
                    id="title_template"
                    name="title_template"
                    label={
                      <LabelWithInfo
                        label="Title Template"
                        info="Format the EPG title using extracted groups. Use {starttime} (12-hour: '10 PM'), {starttime24} (24-hour: '22:00'), {endtime} (12-hour end), {endtime24} (24-hour end), {date} (YYYY-MM-DD), {month}, {day}, or {year}. Date/time placeholders respect Output Timezone settings. Example: {league} - {team1} vs {team2} ({starttime}-{endtime})"
                      />
                    }
                    placeholder="{league} - {team1} vs {team2}"
                    value={titleTemplate}
                    onChange={(e) => {
                      const value = e.target.value;
                      setTitleTemplate(value);
                      form.setFieldValue(
                        'custom_properties.title_template',
                        value
                      );
                    }}
                  />

                  <TextInput
                    id="subtitle_template"
                    name="subtitle_template"
                    label={
                      <LabelWithInfo
                        label="Subtitle Template (Optional)"
                        info="Format the EPG subtitle using extracted groups. Use {starttime} (12-hour), {starttime24} (24-hour), {endtime} (12-hour end), {endtime24} (24-hour end), {date} (YYYY-MM-DD), {month}, {day}, or {year}. Example: {starttime} - {endtime}"
                      />
                    }
                    placeholder="{starttime} - {endtime}"
                    value={subtitleTemplate}
                    onChange={(e) => {
                      const value = e.target.value;
                      setSubtitleTemplate(value);
                      form.setFieldValue(
                        'custom_properties.subtitle_template',
                        value
                      );
                    }}
                  />

                  <Textarea
                    id="description_template"
                    name="description_template"
                    label={
                      <LabelWithInfo
                        label="Description Template"
                        info="Format the EPG description using extracted groups. Use {starttime} (12-hour), {starttime24} (24-hour), {endtime} (12-hour end), {endtime24} (24-hour end), {date} (YYYY-MM-DD), {month}, {day}, or {year}. Date/time placeholders respect Output Timezone settings. Example: Watch {team1} take on {team2} on {date} from {starttime} to {endtime}!"
                      />
                    }
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
                </Stack>
              </AccordionPanel>
            </AccordionItem>

            <AccordionItem value="upcoming-ended">
              <AccordionControl>Upcoming/Ended Templates</AccordionControl>
              <AccordionPanel>
                <Stack spacing="md">
                  <Text size="sm" c="dimmed">
                    Customize how programs appear before and after the event. If
                    left empty, will use the main title/description with
                    "Upcoming:" or "Ended:" prefix.
                  </Text>

                  <TextInput
                    id="upcoming_title_template"
                    name="upcoming_title_template"
                    label={
                      <LabelWithInfo
                        label="Upcoming Title Template"
                        info="Title for programs before the event starts. Use {starttime} (12-hour), {starttime24} (24-hour), {endtime} (12-hour end), {endtime24} (24-hour end), {date} (YYYY-MM-DD), {month}, {day}, or {year}. Date/time placeholders respect Output Timezone settings. Example: {team1} vs {team2} starting at {starttime}."
                      />
                    }
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
                    label={
                      <LabelWithInfo
                        label="Upcoming Description Template"
                        info="Description for programs before the event. Use {starttime} (12-hour), {starttime24} (24-hour), {endtime} (12-hour end), {endtime24} (24-hour end), {date} (YYYY-MM-DD), {month}, {day}, or {year}. Date/time placeholders respect Output Timezone settings. Example: Upcoming: Watch the {league} match up where the {team1} take on the {team2} on {date} from {starttime} to {endtime}!"
                      />
                    }
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
                    label={
                      <LabelWithInfo
                        label="Ended Title Template"
                        info="Title for programs after the event has ended. Use {starttime} (12-hour), {starttime24} (24-hour), {endtime} (12-hour end), {endtime24} (24-hour end), {date} (YYYY-MM-DD), {month}, {day}, or {year}. Date/time placeholders respect Output Timezone settings. Example: {team1} vs {team2} started at {starttime}."
                      />
                    }
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
                    label={
                      <LabelWithInfo
                        label="Ended Description Template"
                        info="Description for programs after the event. Use {starttime} (12-hour), {starttime24} (24-hour), {endtime} (12-hour end), {endtime24} (24-hour end), {date} (YYYY-MM-DD), {month}, {day}, or {year}. Date/time placeholders respect Output Timezone settings. Example: The {league} match between {team1} and {team2} on {date} ran from {starttime} to {endtime}."
                      />
                    }
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
                </Stack>
              </AccordionPanel>
            </AccordionItem>

            <AccordionItem value="fallback">
              <AccordionControl>Fallback Templates</AccordionControl>
              <AccordionPanel>
                <Stack spacing="md">
                  <Text size="sm" c="dimmed">
                    When patterns don't match the channel/stream name, use these
                    custom fallback templates instead of the default placeholder
                    messages. Leave empty to use the built-in humorous fallback
                    descriptions.
                  </Text>

                  <TextInput
                    id="fallback_title_template"
                    name="fallback_title_template"
                    label={
                      <LabelWithInfo
                        label="Fallback Title Template"
                        info="Custom title when patterns don't match. If empty, uses the channel/stream name."
                      />
                    }
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
                    label={
                      <LabelWithInfo
                        label="Fallback Description Template"
                        info="Custom description when patterns don't match. If empty, uses built-in placeholder messages."
                      />
                    }
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
                </Stack>
              </AccordionPanel>
            </AccordionItem>

            <AccordionItem value="settings">
              <AccordionControl>EPG Settings</AccordionControl>
              <AccordionPanel>
                <Stack spacing="md">
                  <Select
                    label={
                      <LabelWithInfo
                        label="Event Timezone"
                        info="The timezone of the event times in your channel titles. DST (Daylight Saving Time) is handled automatically! All timezones supported by pytz are available."
                      />
                    }
                    placeholder={
                      loadingTimezones
                        ? 'Loading timezones...'
                        : 'Select timezone'
                    }
                    data={timezoneOptions}
                    searchable
                    disabled={loadingTimezones}
                    {...form.getInputProps('custom_properties.timezone')}
                  />

                  <Select
                    label={
                      <LabelWithInfo
                        label="Output Timezone (Optional)"
                        info="Display times in a different timezone than the event timezone. Leave empty to use the event timezone. Example: Event at 10 PM ET displayed as 9 PM CT."
                      />
                    }
                    placeholder="Same as event timezone"
                    data={timezoneOptions}
                    searchable
                    clearable
                    disabled={loadingTimezones}
                    {...form.getInputProps('custom_properties.output_timezone')}
                  />

                  <NumberInput
                    label={
                      <LabelWithInfo
                        label="Program Duration (minutes)"
                        info="Default duration for each program"
                      />
                    }
                    placeholder="180"
                    min={1}
                    max={1440}
                    {...form.getInputProps(
                      'custom_properties.program_duration'
                    )}
                  />

                  <TextInput
                    label={
                      <LabelWithInfo
                        label="Categories (Optional)"
                        info="EPG categories for these programs. Use commas to separate multiple (e.g., Sports, Live, HD). Note: Only added to the main event, not upcoming/ended filler programs."
                      />
                    }
                    placeholder="Sports, Live"
                    {...form.getInputProps('custom_properties.category')}
                  />

                  <TextInput
                    label={
                      <LabelWithInfo
                        label="Channel Logo URL (Optional)"
                        info="Build a URL for the channel logo using regex groups. Example: https://example.com/logos/{league_normalize}/{team1_normalize}.png. Use {groupname_normalize} for cleaner URLs (alphanumeric-only, lowercase). This will be used as the channel <icon> in the EPG output."
                      />
                    }
                    placeholder="https://example.com/logos/{league_normalize}/{team1_normalize}.png"
                    value={channelLogoUrl}
                    onChange={(e) => {
                      const value = e.target.value;
                      setChannelLogoUrl(value);
                      form.setFieldValue(
                        'custom_properties.channel_logo_url',
                        value
                      );
                    }}
                  />

                  <TextInput
                    label={
                      <LabelWithInfo
                        label="Program Poster URL (Optional)"
                        info="Build a URL for the program poster/icon using regex groups. Example: https://example.com/posters/{team1_normalize}-vs-{team2_normalize}.jpg. Use {groupname_normalize} for cleaner URLs (alphanumeric-only, lowercase). This will be used as the program <icon> in the EPG output."
                      />
                    }
                    placeholder="https://example.com/posters/{team1_normalize}-vs-{team2_normalize}.jpg"
                    value={programPosterUrl}
                    onChange={(e) => {
                      const value = e.target.value;
                      setProgramPosterUrl(value);
                      form.setFieldValue(
                        'custom_properties.program_poster_url',
                        value
                      );
                    }}
                  />

                  <Checkbox
                    label={
                      <LabelWithInfo
                        label="Include Date Tag"
                        info="Include the <date> tag in EPG output with the program's start date (YYYY-MM-DD format). Added to all programs."
                      />
                    }
                    {...form.getInputProps('custom_properties.include_date', {
                      type: 'checkbox',
                    })}
                  />

                  <Checkbox
                    label={
                      <LabelWithInfo
                        label="Include Live Tag"
                        info="Mark programs as live content with the <live /> tag in EPG output. Note: Only added to the main event, not upcoming/ended filler programs."
                      />
                    }
                    {...form.getInputProps('custom_properties.include_live', {
                      type: 'checkbox',
                    })}
                  />

                  <Checkbox
                    label={
                      <LabelWithInfo
                        label="Include New Tag"
                        info="Mark programs as new content with the <new /> tag in EPG output. Note: Only added to the main event, not upcoming/ended filler programs."
                      />
                    }
                    {...form.getInputProps('custom_properties.include_new', {
                      type: 'checkbox',
                    })}
                  />
                </Stack>
              </AccordionPanel>
            </AccordionItem>
          </Accordion>

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
            label={
              <LabelWithInfo
                label={`Sample ${form.values.custom_properties?.name_source === 'stream' ? 'Stream' : 'Channel'} Name`}
                info={`Enter a sample ${form.values.custom_properties?.name_source === 'stream' ? 'stream name' : 'channel name'} to test pattern matching and see the formatted output`}
              />
            }
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

                    {subtitleTemplate && (
                      <>
                        <Text size="xs" c="dimmed" mt="xs">
                          EPG Subtitle:
                        </Text>
                        <Text size="sm" fw={500}>
                          {patternValidation.formattedSubtitle ||
                            '(no matching groups)'}
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
                      !subtitleTemplate &&
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
