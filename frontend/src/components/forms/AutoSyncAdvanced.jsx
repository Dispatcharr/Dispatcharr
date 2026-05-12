// Shared preview box for include and exclude filters. The marker and
// color reflect whether matched names are kept (teal check) or dropped
// (red x); empty/loading/error states mirror the find preview.
import {
  Box,
  Button,
  Center,
  Checkbox,
  Divider,
  Flex,
  Group,
  MultiSelect,
  Popover,
  PopoverDropdown,
  PopoverTarget,
  ScrollArea,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { getRegexOptions } from '../../utils/forms/LiveGroupFilterUtils.js';
import React from 'react';
import useChannelsStore from '../../store/channels.jsx';
import { FixedSizeList as List } from 'react-window';
import logo from '../../images/logo.png';
import LazyLogo from '../LazyLogo.jsx';
import { RefreshCw } from 'lucide-react';
import { showNotification } from '../../utils/notificationUtils.js';
import {
  formatPreviewSummary,
  getEpgSourceData,
  getEpgSourceValue,
  repackGroupChannels,
} from '../../utils/forms/AutoSyncAdvancedUtils.js';

const RegexPreviewBox = ({ group, kind, regexPreviewState }) => {
  const pattern =
    kind === 'exclude'
      ? group.custom_properties?.name_match_exclude_regex || ''
      : kind === 'include'
        ? group.custom_properties?.name_match_regex || ''
        : group.custom_properties?.name_regex_pattern || '';
  if (!pattern) return null;
  const state = regexPreviewState[group.channel_group] || {};
  const result =
    kind === 'exclude'
      ? state.excludeResult
      : kind === 'include'
        ? state.filterResult
        : state.findResult;
  const loading = state.loading;
  const summaryLabel =
    kind === 'exclude' ? 'exclude' : kind === 'include' ? 'filter' : 'rename';
  const placeholderLabel =
    kind === 'exclude'
      ? 'Exclude preview'
      : kind === 'include'
        ? 'Filter preview'
        : 'Preview';
  const markerChar = kind === 'exclude' ? '✗' : '✓';
  const markerColor = kind === 'exclude' ? 'red.4' : 'teal.4';
  const emptyText =
    kind === 'exclude'
      ? 'No streams matched this pattern (nothing would be excluded).'
      : 'No streams matched this pattern.';
  return (
    <Box
      style={{
        border: '1px solid #3F3F46',
        borderRadius: 6,
        padding: 8,
        backgroundColor: '#1E1E22',
      }}
    >
      <Text size="xs" fw={600} mb={4}>
        {result ? formatPreviewSummary(summaryLabel, result) : placeholderLabel}
      </Text>
      {result?.error && (
        <Text size="xs" c="red.5">
          Invalid regex: {result.error}
        </Text>
      )}
      {loading && !result && (
        <Text size="xs" c="dimmed">
          Scanning streams...
        </Text>
      )}
      {result && !result.error && result.matches?.length === 0 && (
        <Text size="xs" c="dimmed">
          {result.total_in_group === 0
            ? 'No streams in this group yet. Run an M3U refresh first to populate streams.'
            : emptyText}
        </Text>
      )}
      {result?.matches?.map((row, idx) =>
        kind === 'find' ? (
          <Flex
            key={`${row.before}-${idx}`}
            gap="xs"
            align="center"
            style={{ fontFamily: 'monospace' }}
          >
            <Text size="xs" c="dimmed" style={{ flex: 1 }} truncate>
              {row.before}
            </Text>
            <Text size="xs" c="gray.5">
              {' -> '}
            </Text>
            <Text size="xs" c="teal.4" style={{ flex: 1 }} truncate>
              {row.after}
            </Text>
          </Flex>
        ) : (
          <Flex
            key={`${row.name}-${idx}`}
            gap="xs"
            align="center"
            style={{ fontFamily: 'monospace' }}
          >
            <Text size="xs" c={markerColor} style={{ width: 18 }}>
              {markerChar}
            </Text>
            <Text size="xs" c="gray.2" style={{ flex: 1 }} truncate>
              {row.name}
            </Text>
          </Flex>
        )
      )}
    </Box>
  );
};

// Advanced Options form rendered inside the gear modal. A field's
// presence in custom_properties activates it; blanking returns the
// group to default behavior.
const AutoSyncAdvanced = ({
  group,
  epgSources,
  channelGroups,
  streamProfiles,
  regexPreviewState,
  onApplyGroupChange,
  onScheduleRegexPreview,
  onOpenLogoUpload,
  channelLogos,
  playlist,
  logosLoading,
  ensureLogosLoaded,
}) => {
  const cp = group.custom_properties || {};
  const profiles = useChannelsStore((s) => s.profiles);

  const setCp = (patch, clears = []) => {
    const next = { ...cp, ...patch };
    clears.forEach((k) => delete next[k]);
    onApplyGroupChange({ ...group, custom_properties: next });
  };

  // --- Name Transforms ---

  const findValue = cp.name_regex_pattern ?? '';
  const replaceValue = cp.name_replace_pattern ?? '';
  const filterValue = cp.name_match_regex ?? '';
  const excludeValue = cp.name_match_exclude_regex ?? '';
  const updateFind = (val) => {
    if (!val && !replaceValue) {
      setCp({}, ['name_regex_pattern', 'name_replace_pattern']);
    } else {
      setCp({
        name_regex_pattern: val,
        name_replace_pattern: replaceValue,
      });
    }
    onScheduleRegexPreview(
      group,
      getRegexOptions(val, replaceValue, filterValue, excludeValue)
    );
  };
  const updateReplace = (val) => {
    if (!val && !findValue) {
      setCp({}, ['name_regex_pattern', 'name_replace_pattern']);
    } else {
      setCp({
        name_regex_pattern: findValue,
        name_replace_pattern: val,
      });
    }
    onScheduleRegexPreview(
      group,
      getRegexOptions(findValue, val, filterValue, excludeValue)
    );
  };
  const updateFilter = (val) => {
    if (!val) setCp({}, ['name_match_regex']);
    else setCp({ name_match_regex: val });
    onScheduleRegexPreview(
      group,
      getRegexOptions(findValue, replaceValue, val, excludeValue)
    );
  };
  const updateExclude = (val) => {
    if (!val) setCp({}, ['name_match_exclude_regex']);
    else setCp({ name_match_exclude_regex: val });
    onScheduleRegexPreview(
      group,
      getRegexOptions(findValue, replaceValue, filterValue, val)
    );
  };

  // --- EPG ---

  const epgValue = getEpgSourceValue(cp);
  const updateEpg = (value) => {
    const next = { ...cp };
    delete next.custom_epg_id;
    delete next.force_dummy_epg;
    delete next.force_epg_selected;
    if (value === '0') {
      next.force_dummy_epg = true;
    } else if (value) {
      next.custom_epg_id = parseInt(value);
    }
    onApplyGroupChange({ ...group, custom_properties: next });
  };

  // --- Channel Assignment ---

  const groupOverrideValue = cp.group_override
    ? cp.group_override.toString()
    : '';
  const updateGroupOverride = (value) => {
    if (!value) setCp({}, ['group_override']);
    else setCp({ group_override: parseInt(value) });
  };

  const profileValue = cp.channel_profile_ids ?? [];
  const updateProfiles = (value) => {
    if (!value || value.length === 0) {
      setCp({}, ['channel_profile_ids']);
    } else {
      setCp({ channel_profile_ids: value });
    }
  };

  const streamProfileValue = cp.stream_profile_id
    ? cp.stream_profile_id.toString()
    : '';
  const updateStreamProfile = (value) => {
    if (!value) setCp({}, ['stream_profile_id']);
    else setCp({ stream_profile_id: parseInt(value) });
  };

  const sortOrderValue = cp.channel_sort_order ?? '__default__';
  const sortReverseEnabled = cp.channel_sort_order !== undefined;
  const updateSortOrder = (value) => {
    if (!value || value === '__default__') {
      setCp({}, ['channel_sort_order', 'channel_sort_reverse']);
    } else {
      setCp({
        channel_sort_order: value,
        channel_sort_reverse: cp.channel_sort_reverse ?? false,
      });
    }
  };
  const updateSortReverse = (checked) => {
    setCp({ channel_sort_reverse: checked });
  };

  // --- Custom Logo ---

  const logoValue = cp.custom_logo_id;

  return (
    <Stack gap="lg">
      <Stack gap="sm">
        <Divider
          label={
            <Text size="sm" fw={600} c="gray.3">
              Name Transforms
            </Text>
          }
          labelPosition="left"
          size="sm"
          color="gray.6"
        />
        <Tooltip
          label="Apply a regex find/replace to channel names during sync. Leave both empty to skip."
          withArrow
          multiline
          w={280}
          openDelay={500}
        >
          <Box>
            <Flex gap="xs">
              <TextInput
                label="Find (Regex)"
                placeholder="e.g. ^.*? - PPV\\d+ - (.+)$"
                value={findValue}
                onChange={(e) => updateFind(e.currentTarget.value)}
                size="xs"
                style={{ flex: 1 }}
              />
              <TextInput
                label="Replace"
                placeholder="e.g. $1"
                value={replaceValue}
                onChange={(e) => updateReplace(e.currentTarget.value)}
                size="xs"
                style={{ flex: 1 }}
              />
            </Flex>
            {findValue && (
              <RegexPreviewBox
                group={group}
                kind="find"
                regexPreviewState={regexPreviewState}
              />
            )}
          </Box>
        </Tooltip>
        <Flex gap="xs" align="flex-start">
          <Tooltip
            label="Only include channels whose names match the pattern. Leave empty to include all."
            withArrow
            multiline
            w={280}
            openDelay={500}
          >
            <Box style={{ flex: 1 }}>
              <TextInput
                label="Include if name matches (Regex)"
                placeholder="e.g. ^Sports.*"
                value={filterValue}
                onChange={(e) => updateFilter(e.currentTarget.value)}
                size="xs"
              />
              {filterValue && (
                <RegexPreviewBox
                  group={group}
                  kind="include"
                  regexPreviewState={regexPreviewState}
                />
              )}
            </Box>
          </Tooltip>
          <Tooltip
            label="Drop channels whose names match the pattern. Applied after the include filter; useful for removing specific bad streams without rewriting the include pattern."
            withArrow
            multiline
            w={280}
            openDelay={500}
          >
            <Box style={{ flex: 1 }}>
              <TextInput
                label="Exclude if name matches (Regex)"
                placeholder="e.g. TEST|BACKUP"
                value={excludeValue}
                onChange={(e) => updateExclude(e.currentTarget.value)}
                size="xs"
              />
              {excludeValue && (
                <RegexPreviewBox
                  group={group}
                  kind="exclude"
                  regexPreviewState={regexPreviewState}
                />
              )}
            </Box>
          </Tooltip>
        </Flex>
      </Stack>

      <Stack gap="sm">
        <Divider
          label={
            <Text size="sm" fw={600} c="gray.3">
              EPG & Logo
            </Text>
          }
          labelPosition="left"
          size="sm"
          color="gray.6"
        />
        <Flex gap="xs" align="flex-start">
          <Tooltip
            label="Force a specific EPG source. Defaults to auto-matching by tvg_id when blank."
            withArrow
            multiline
            w={280}
            openDelay={500}
          >
            <Select
              label="EPG Source"
              placeholder="Auto-match (default)"
              value={epgValue || null}
              onChange={updateEpg}
              data={getEpgSourceData(epgSources)}
              clearable
              searchable
              size="xs"
              style={{ flex: 1 }}
            />
          </Tooltip>

          <Box style={{ flex: 1 }}>
            <Group justify="space-between">
              <Popover
                opened={group.logoPopoverOpened || false}
                onChange={(opened) => {
                  onApplyGroupChange({ ...group, logoPopoverOpened: opened });
                  if (opened) ensureLogosLoaded();
                }}
                withArrow
              >
                <PopoverTarget>
                  <TextInput
                    label="Custom Logo"
                    placeholder="Stream logo (default)"
                    readOnly
                    value={logoValue ? channelLogos[logoValue]?.name || '' : ''}
                    onClick={() =>
                      onApplyGroupChange({
                        ...group,
                        logoPopoverOpened: true,
                      })
                    }
                    size="xs"
                    style={{ flex: 1 }}
                  />
                </PopoverTarget>
                <PopoverDropdown onMouseDown={(e) => e.stopPropagation()}>
                  <Group>
                    <TextInput
                      placeholder="Filter logos..."
                      size="xs"
                      value={group.logoFilter || ''}
                      onChange={(e) =>
                        onApplyGroupChange({
                          ...group,
                          logoFilter: e.currentTarget.value,
                        })
                      }
                    />
                    {logosLoading && (
                      <Text size="xs" c="dimmed">
                        Loading...
                      </Text>
                    )}
                  </Group>
                  <ScrollArea style={{ height: 200 }}>
                    {(() => {
                      const logoOptions = [
                        { id: '0', name: 'Default' },
                        ...Object.values(channelLogos),
                      ];
                      const filteredLogos = logoOptions.filter((logoItem) =>
                        logoItem.name
                          .toLowerCase()
                          .includes((group.logoFilter || '').toLowerCase())
                      );
                      if (filteredLogos.length === 0) {
                        return (
                          <Center style={{ height: 200 }}>
                            <Text size="sm" c="dimmed">
                              {group.logoFilter
                                ? 'No logos match your filter'
                                : 'No logos available'}
                            </Text>
                          </Center>
                        );
                      }
                      return (
                        <List
                          height={200}
                          itemCount={filteredLogos.length}
                          itemSize={55}
                          style={{ width: '100%' }}
                        >
                          {({ index, style }) => {
                            const logoItem = filteredLogos[index];
                            return (
                              <div
                                style={{
                                  ...style,
                                  cursor: 'pointer',
                                  padding: '5px',
                                  borderRadius: '4px',
                                }}
                                onClick={() => {
                                  const next = { ...cp };
                                  if (logoItem.id === '0' || !logoItem.id) {
                                    delete next.custom_logo_id;
                                  } else {
                                    next.custom_logo_id = logoItem.id;
                                  }
                                  onApplyGroupChange({
                                    ...group,
                                    custom_properties: next,
                                    logoPopoverOpened: false,
                                  });
                                }}
                                onMouseEnter={(e) => {
                                  e.currentTarget.style.backgroundColor =
                                    'rgb(68, 68, 68)';
                                }}
                                onMouseLeave={(e) => {
                                  e.currentTarget.style.backgroundColor =
                                    'transparent';
                                }}
                              >
                                <Center
                                  style={{
                                    flexDirection: 'column',
                                    gap: '2px',
                                  }}
                                >
                                  <img
                                    src={logoItem.cache_url || logo}
                                    height="30"
                                    style={{
                                      maxWidth: 80,
                                      objectFit: 'contain',
                                    }}
                                    alt={logoItem.name || 'Logo'}
                                    onError={(e) => {
                                      if (e.target.src !== logo) {
                                        e.target.src = logo;
                                      }
                                    }}
                                  />
                                  <Text
                                    size="xs"
                                    c="dimmed"
                                    ta="center"
                                    style={{
                                      maxWidth: 80,
                                      overflow: 'hidden',
                                      textOverflow: 'ellipsis',
                                      whiteSpace: 'nowrap',
                                    }}
                                  >
                                    {logoItem.name || 'Default'}
                                  </Text>
                                </Center>
                              </div>
                            );
                          }}
                        </List>
                      );
                    })()}
                  </ScrollArea>
                </PopoverDropdown>
              </Popover>
              {logoValue && (
                <Stack gap="xs" align="center">
                  <LazyLogo
                    logoId={logoValue}
                    alt="custom logo"
                    style={{ height: 40 }}
                  />
                </Stack>
              )}
            </Group>
            <Button
              onClick={() => onOpenLogoUpload(group.channel_group)}
              variant="subtle"
              size="compact-xs"
              mt={4}
            >
              + Upload new logo
            </Button>
          </Box>
        </Flex>
      </Stack>

      <Stack gap="sm">
        <Divider
          label={
            <Text size="sm" fw={600} c="gray.3">
              Channel Assignment
            </Text>
          }
          labelPosition="left"
          size="sm"
          color="gray.6"
        />
        <Flex gap="xs">
          <Tooltip
            label="Send auto-created channels into a different group than their source."
            withArrow
            multiline
            w={280}
            openDelay={500}
          >
            <Select
              label="Override Channel Group"
              placeholder="Source group (default)"
              value={groupOverrideValue || null}
              onChange={updateGroupOverride}
              data={Object.values(channelGroups).map((g) => ({
                value: g.id.toString(),
                label: g.name,
              }))}
              clearable
              searchable
              size="xs"
              style={{ flex: 1 }}
            />
          </Tooltip>
          <Tooltip
            label="Limit auto-created channels to specific channel profiles. Defaults to all profiles when blank."
            withArrow
            multiline
            w={280}
            openDelay={500}
          >
            <MultiSelect
              label="Channel Profiles"
              placeholder="All profiles (default)"
              value={profileValue}
              onChange={updateProfiles}
              data={Object.values(profiles).map((profile) => ({
                value: profile.id.toString(),
                label: profile.name,
              }))}
              clearable
              searchable
              size="xs"
              style={{ flex: 1 }}
            />
          </Tooltip>
        </Flex>
        <Flex gap="xs" align="flex-start">
          <Tooltip
            label="Apply a specific stream profile to channels created by this group."
            withArrow
            multiline
            w={280}
            openDelay={500}
          >
            <Select
              label="Stream Profile"
              placeholder="Account default"
              value={streamProfileValue || null}
              onChange={updateStreamProfile}
              data={streamProfiles.map((profile) => ({
                value: profile.id.toString(),
                label: profile.name,
              }))}
              clearable
              searchable
              size="xs"
              style={{ flex: 1 }}
            />
          </Tooltip>
          <Tooltip
            label="Order channels within the group before assigning numbers."
            withArrow
            multiline
            w={280}
            openDelay={500}
          >
            <Box style={{ flex: 1 }}>
              <Select
                label="Channel Sort Order"
                value={sortOrderValue}
                onChange={updateSortOrder}
                data={[
                  { value: '__default__', label: 'Provider Order (Default)' },
                  { value: 'name', label: 'Name' },
                  { value: 'tvg_id', label: 'TVG ID' },
                  { value: 'updated_at', label: 'Updated At' },
                ]}
                searchable
                size="xs"
              />
              {sortReverseEnabled && (
                <Checkbox
                  label="Reverse sort order"
                  checked={cp.channel_sort_reverse || false}
                  onChange={(event) =>
                    updateSortReverse(event.currentTarget.checked)
                  }
                  size="xs"
                  mt="xs"
                />
              )}
            </Box>
          </Tooltip>
        </Flex>
        <Flex align="center" justify="space-between" gap="md" mt="xs">
          <Tooltip
            label="Visible channels get sequential numbers; hidden channels release theirs. Set a channel number override to preserve channel numbers over time."
            withArrow
            multiline
            w={320}
            openDelay={500}
          >
            <Box style={{ flex: 1, minWidth: 0 }}>
              <Switch
                label="Compact numbering"
                description="Numbers shift on hide/unhide. Pin a number with a channel number override."
                checked={!!cp.compact_numbering}
                onChange={(event) => {
                  if (event.currentTarget.checked) {
                    setCp({ compact_numbering: true });
                  } else {
                    setCp({}, ['compact_numbering']);
                  }
                }}
                size="xs"
              />
            </Box>
          </Tooltip>
          <Tooltip
            label="Re-assign visible channels into the group's current range. Overrides are kept as reservations and not modified."
            withArrow
            multiline
            w={280}
            openDelay={500}
          >
            <Button
              variant="subtle"
              size="compact-xs"
              color="gray"
              leftSection={<RefreshCw size={12} />}
              onClick={async () => {
                const result = await repackGroupChannels(playlist, group);
                if (result) {
                  showNotification({
                    title: 'Channels renumbered',
                    message: `Assigned ${result.assigned}, released ${result.released}${
                      result.failed
                        ? `, ${result.failed} could not fit in the configured range`
                        : ''
                    }.`,
                    color: result.failed ? 'yellow' : 'green',
                    autoClose: 5000,
                  });
                }
              }}
              style={{ flexShrink: 0 }}
            >
              Renumber now
            </Button>
          </Tooltip>
        </Flex>
      </Stack>
    </Stack>
  );
};

export default AutoSyncAdvanced;
