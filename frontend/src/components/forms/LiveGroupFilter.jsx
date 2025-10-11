// Modal.js
import React, { useState, useEffect, forwardRef } from 'react';
import {
  TextInput,
  Button,
  Checkbox,
  Flex,
  Select,
  Stack,
  Group,
  SimpleGrid,
  Text,
  NumberInput,
  Divider,
  Alert,
  Box,
  MultiSelect,
  Tooltip,
} from '@mantine/core';
import { Info } from 'lucide-react';
import useChannelsStore from '../../store/channels';
import useStreamProfilesStore from '../../store/streamProfiles';
import { CircleCheck, CircleX } from 'lucide-react';

// Custom item component for MultiSelect with tooltip
const OptionWithTooltip = forwardRef(
  ({ label, description, ...others }, ref) => (
    <Tooltip label={description} withArrow>
      <div ref={ref} {...others}>
        {label}
      </div>
    </Tooltip>
  )
);

const LiveGroupFilter = ({
  playlist,
  groupStates,
  setGroupStates,
  autoEnableNewGroupsLive,
  setAutoEnableNewGroupsLive,
}) => {
  const channelGroups = useChannelsStore((s) => s.channelGroups);
  const profiles = useChannelsStore((s) => s.profiles);
  const streamProfiles = useStreamProfilesStore((s) => s.profiles);
  const fetchStreamProfiles = useStreamProfilesStore((s) => s.fetchProfiles);
  const [groupFilter, setGroupFilter] = useState('');

  // Fetch stream profiles when component mounts
  useEffect(() => {
    if (streamProfiles.length === 0) {
      fetchStreamProfiles();
    }
  }, [streamProfiles.length, fetchStreamProfiles]);

  useEffect(() => {
    if (Object.keys(channelGroups).length === 0) {
      return;
    }

    setGroupStates(
      playlist.channel_groups.map((group) => {
        // Parse custom_properties if present
        let customProps = {};
        if (group.custom_properties) {
          try {
            customProps =
              typeof group.custom_properties === 'string'
                ? JSON.parse(group.custom_properties)
                : group.custom_properties;
          } catch (e) {
            customProps = {};
          }
        }
        return {
          ...group,
          name: channelGroups[group.channel_group].name,
          auto_channel_sync: group.auto_channel_sync || false,
          auto_sync_channel_start: group.auto_sync_channel_start || 1.0,
          custom_properties: customProps,
          original_enabled: group.enabled,
        };
      })
    );
  }, [playlist, channelGroups]);

  const toggleGroupEnabled = (id) => {
    setGroupStates(
      groupStates.map((state) => ({
        ...state,
        enabled: state.channel_group == id ? !state.enabled : state.enabled,
      }))
    );
  };

  const toggleAutoSync = (id) => {
    setGroupStates(
      groupStates.map((state) => ({
        ...state,
        auto_channel_sync:
          state.channel_group == id
            ? !state.auto_channel_sync
            : state.auto_channel_sync,
      }))
    );
  };

  const updateChannelStart = (id, value) => {
    setGroupStates(
      groupStates.map((state) => ({
        ...state,
        auto_sync_channel_start:
          state.channel_group == id ? value : state.auto_sync_channel_start,
      }))
    );
  };

  // Toggle force_dummy_epg in custom_properties for a group
  const toggleForceDummyEPG = (id) => {
    setGroupStates(
      groupStates.map((state) => {
        if (state.channel_group == id) {
          const customProps = { ...(state.custom_properties || {}) };
          customProps.force_dummy_epg = !customProps.force_dummy_epg;
          return {
            ...state,
            custom_properties: customProps,
          };
        }
        return state;
      })
    );
  };

  const selectAll = () => {
    setGroupStates(
      groupStates.map((state) => ({
        ...state,
        enabled: state.name.toLowerCase().includes(groupFilter.toLowerCase())
          ? true
          : state.enabled,
      }))
    );
  };

  const deselectAll = () => {
    setGroupStates(
      groupStates.map((state) => ({
        ...state,
        enabled: state.name.toLowerCase().includes(groupFilter.toLowerCase())
          ? false
          : state.enabled,
      }))
    );
  };

  return (
    <Stack style={{ paddingTop: 10 }}>
      <Alert icon={<Info size={16} />} color="blue" variant="light">
        <Text size="sm">
          <strong>Auto Channel Sync:</strong> When enabled, channels will be
          automatically created for all streams in the group during M3U updates,
          and removed when streams are no longer present. Set a starting channel
          number for each group to organize your channels.
        </Text>
      </Alert>

      <Checkbox
        label="Automatically enable new groups discovered on future scans"
        checked={autoEnableNewGroupsLive}
        onChange={(event) =>
          setAutoEnableNewGroupsLive(event.currentTarget.checked)
        }
        size="sm"
        description="When disabled, new groups from the M3U source will be created but disabled by default. You can enable them manually later."
      />

      <Flex gap="sm">
        <TextInput
          placeholder="Filter groups..."
          value={groupFilter}
          onChange={(event) => setGroupFilter(event.currentTarget.value)}
          style={{ flex: 1 }}
          size="xs"
        />
        <Button variant="default" size="xs" onClick={selectAll}>
          Select Visible
        </Button>
        <Button variant="default" size="xs" onClick={deselectAll}>
          Deselect Visible
        </Button>
      </Flex>

      <Divider label="Groups & Auto Sync Settings" labelPosition="center" />

      <Box style={{ maxHeight: '50vh', overflowY: 'auto' }}>
        <SimpleGrid
          cols={{ base: 1, sm: 2, md: 3 }}
          spacing="xs"
          verticalSpacing="xs"
        >
          {groupStates
            .filter((group) =>
              group.name.toLowerCase().includes(groupFilter.toLowerCase())
            )
            .sort((a, b) => a.name.localeCompare(b.name))
            .map((group) => (
              <Group
                key={group.channel_group}
                spacing="xs"
                style={{
                  padding: '8px',
                  border: '1px solid #444',
                  borderRadius: '8px',
                  backgroundColor: group.enabled ? '#2A2A2E' : '#1E1E22',
                  flexDirection: 'column',
                  alignItems: 'stretch',
                }}
              >
                {/* Group Enable/Disable Button */}
                <Button
                  color={group.enabled ? 'green' : 'gray'}
                  variant="filled"
                  onClick={() => toggleGroupEnabled(group.channel_group)}
                  radius="md"
                  size="xs"
                  leftSection={
                    group.enabled ? (
                      <CircleCheck size={14} />
                    ) : (
                      <CircleX size={14} />
                    )
                  }
                  fullWidth
                >
                  <Text size="xs" truncate>
                    {group.name}
                  </Text>
                </Button>

                {/* Auto Sync Controls */}
                <Stack spacing="xs" style={{ '--stack-gap': '4px' }}>
                  <Flex align="center" gap="xs">
                    <Checkbox
                      label="Auto Channel Sync"
                      checked={group.auto_channel_sync && group.enabled}
                      disabled={!group.enabled}
                      onChange={() => toggleAutoSync(group.channel_group)}
                      size="xs"
                    />
                  </Flex>

                  {group.auto_channel_sync && group.enabled && (
                    <>
                      <NumberInput
                        label="Start Channel #"
                        value={group.auto_sync_channel_start}
                        onChange={(value) =>
                          updateChannelStart(group.channel_group, value)
                        }
                        min={1}
                        step={1}
                        size="xs"
                        precision={1}
                      />

                      {/* Auto Channel Sync Options Multi-Select */}
                      <MultiSelect
                        label="Advanced Options"
                        placeholder="Select options..."
                        data={[
                          {
                            value: 'force_dummy_epg',
                            label: 'Force Dummy EPG',
                            description:
                              'Assign a dummy EPG to all channels in this group if no EPG is matched',
                          },
                          {
                            value: 'group_override',
                            label: 'Override Channel Group',
                            description:
                              'Override the group assignment for all channels in this group',
                          },
                          {
                            value: 'name_regex',
                            label: 'Channel Name Find & Replace (Regex)',
                            description:
                              'Find and replace part of the channel name using a regex pattern',
                          },
                          {
                            value: 'name_match_regex',
                            label: 'Channel Name Filter (Regex)',
                            description:
                              'Only include channels whose names match this regex pattern',
                          },
                          {
                            value: 'profile_assignment',
                            label: 'Channel Profile Assignment',
                            description:
                              'Specify which channel profiles the auto-synced channels should be added to',
                          },
                          {
                            value: 'channel_sort_order',
                            label: 'Channel Sort Order',
                            description:
                              'Specify the order in which channels are created (name, tvg_id, updated_at)',
                          },
                          {
                            value: 'stream_profile_assignment',
                            label: 'Stream Profile Assignment',
                            description:
                              'Assign a specific stream profile to all channels in this group during auto sync',
                          },
                        ]}
                        itemComponent={OptionWithTooltip}
                        value={(() => {
                          const selectedValues = [];
                          if (group.custom_properties?.force_dummy_epg) {
                            selectedValues.push('force_dummy_epg');
                          }
                          if (
                            group.custom_properties?.group_override !==
                            undefined
                          ) {
                            selectedValues.push('group_override');
                          }
                          if (
                            group.custom_properties?.name_regex_pattern !==
                              undefined ||
                            group.custom_properties?.name_replace_pattern !==
                              undefined
                          ) {
                            selectedValues.push('name_regex');
                          }
                          if (
                            group.custom_properties?.name_match_regex !==
                            undefined
                          ) {
                            selectedValues.push('name_match_regex');
                          }
                          if (
                            group.custom_properties?.channel_profile_ids !==
                            undefined
                          ) {
                            selectedValues.push('profile_assignment');
                          }
                          if (
                            group.custom_properties?.channel_sort_order !==
                            undefined
                          ) {
                            selectedValues.push('channel_sort_order');
                          }
                          if (
                            group.custom_properties?.stream_profile_id !==
                            undefined
                          ) {
                            selectedValues.push('stream_profile_assignment');
                          }
                          return selectedValues;
                        })()}
                        onChange={(values) => {
                          // MultiSelect always returns an array
                          const selectedOptions = values || [];

                          setGroupStates(
                            groupStates.map((state) => {
                              if (state.channel_group === group.channel_group) {
                                let newCustomProps = {
                                  ...(state.custom_properties || {}),
                                };

                                // Handle force_dummy_epg
                                if (
                                  selectedOptions.includes('force_dummy_epg')
                                ) {
                                  newCustomProps.force_dummy_epg = true;
                                } else {
                                  delete newCustomProps.force_dummy_epg;
                                }

                                // Handle group_override
                                if (
                                  selectedOptions.includes('group_override')
                                ) {
                                  if (
                                    newCustomProps.group_override === undefined
                                  ) {
                                    newCustomProps.group_override = null;
                                  }
                                } else {
                                  delete newCustomProps.group_override;
                                }

                                // Handle name_regex
                                if (selectedOptions.includes('name_regex')) {
                                  if (
                                    newCustomProps.name_regex_pattern ===
                                    undefined
                                  ) {
                                    newCustomProps.name_regex_pattern = '';
                                  }
                                  if (
                                    newCustomProps.name_replace_pattern ===
                                    undefined
                                  ) {
                                    newCustomProps.name_replace_pattern = '';
                                  }
                                } else {
                                  delete newCustomProps.name_regex_pattern;
                                  delete newCustomProps.name_replace_pattern;
                                }

                                // Handle name_match_regex
                                if (
                                  selectedOptions.includes('name_match_regex')
                                ) {
                                  if (
                                    newCustomProps.name_match_regex ===
                                    undefined
                                  ) {
                                    newCustomProps.name_match_regex = '';
                                  }
                                } else {
                                  delete newCustomProps.name_match_regex;
                                }

                                // Handle profile_assignment
                                if (
                                  selectedOptions.includes('profile_assignment')
                                ) {
                                  if (
                                    newCustomProps.channel_profile_ids ===
                                    undefined
                                  ) {
                                    newCustomProps.channel_profile_ids = [];
                                  }
                                } else {
                                  delete newCustomProps.channel_profile_ids;
                                }
                                // Handle channel_sort_order
                                if (
                                  selectedOptions.includes('channel_sort_order')
                                ) {
                                  if (
                                    newCustomProps.channel_sort_order ===
                                    undefined
                                  ) {
                                    newCustomProps.channel_sort_order = '';
                                  }
                                  // Keep channel_sort_reverse if it exists
                                  if (
                                    newCustomProps.channel_sort_reverse ===
                                    undefined
                                  ) {
                                    newCustomProps.channel_sort_reverse = false;
                                  }
                                } else {
                                  delete newCustomProps.channel_sort_order;
                                  delete newCustomProps.channel_sort_reverse; // Remove reverse when sort is removed
                                }

                                // Handle stream_profile_assignment
                                if (
                                  selectedOptions.includes(
                                    'stream_profile_assignment'
                                  )
                                ) {
                                  if (
                                    newCustomProps.stream_profile_id ===
                                    undefined
                                  ) {
                                    newCustomProps.stream_profile_id = null;
                                  }
                                } else {
                                  delete newCustomProps.stream_profile_id;
                                }

                                return {
                                  ...state,
                                  custom_properties: newCustomProps,
                                };
                              }
                              return state;
                            })
                          );
                        }}
                        clearable
                        size="xs"
                      />
                      {/* Show only channel_sort_order if selected */}
                      {group.custom_properties?.channel_sort_order !==
                        undefined && (
                        <>
                          <Select
                            label="Channel Sort Order"
                            placeholder="Select sort order..."
                            value={
                              group.custom_properties?.channel_sort_order || ''
                            }
                            onChange={(value) => {
                              setGroupStates(
                                groupStates.map((state) => {
                                  if (
                                    state.channel_group === group.channel_group
                                  ) {
                                    return {
                                      ...state,
                                      custom_properties: {
                                        ...state.custom_properties,
                                        channel_sort_order: value || '',
                                      },
                                    };
                                  }
                                  return state;
                                })
                              );
                            }}
                            data={[
                              {
                                value: '',
                                label: 'Provider Order (Default)',
                              },
                              { value: 'name', label: 'Name' },
                              { value: 'tvg_id', label: 'TVG ID' },
                              {
                                value: 'updated_at',
                                label: 'Updated At',
                              },
                            ]}
                            clearable
                            searchable
                            size="xs"
                          />

                          {/* Add reverse sort checkbox when sort order is selected (including default) */}
                          {group.custom_properties?.channel_sort_order !==
                            undefined && (
                            <Flex align="center" gap="xs" mt="xs">
                              <Checkbox
                                label="Reverse Sort Order"
                                checked={
                                  group.custom_properties
                                    ?.channel_sort_reverse || false
                                }
                                onChange={(event) => {
                                  setGroupStates(
                                    groupStates.map((state) => {
                                      if (
                                        state.channel_group ===
                                        group.channel_group
                                      ) {
                                        return {
                                          ...state,
                                          custom_properties: {
                                            ...state.custom_properties,
                                            channel_sort_reverse:
                                              event.target.checked,
                                          },
                                        };
                                      }
                                      return state;
                                    })
                                  );
                                }}
                                size="xs"
                              />
                            </Flex>
                          )}
                        </>
                      )}

                      {/* Show profile selection only if profile_assignment is selected */}
                      {group.custom_properties?.channel_profile_ids !==
                        undefined && (
                        <Tooltip
                          label="Select which channel profiles the auto-synced channels should be added to. Leave empty to add to all profiles."
                          withArrow
                        >
                          <MultiSelect
                            label="Channel Profiles"
                            placeholder="Select profiles..."
                            value={
                              group.custom_properties?.channel_profile_ids || []
                            }
                            onChange={(value) => {
                              setGroupStates(
                                groupStates.map((state) => {
                                  if (
                                    state.channel_group === group.channel_group
                                  ) {
                                    return {
                                      ...state,
                                      custom_properties: {
                                        ...state.custom_properties,
                                        channel_profile_ids: value || [],
                                      },
                                    };
                                  }
                                  return state;
                                })
                              );
                            }}
                            data={Object.values(profiles).map((profile) => ({
                              value: profile.id.toString(),
                              label: profile.name,
                            }))}
                            clearable
                            searchable
                            size="xs"
                          />
                        </Tooltip>
                      )}

                      {/* Show group select only if group_override is selected */}
                      {group.custom_properties?.group_override !==
                        undefined && (
                        <Tooltip
                          label="Select a group to override the assignment for all channels in this group."
                          withArrow
                        >
                          <Select
                            label="Override Channel Group"
                            placeholder="Choose group..."
                            value={
                              group.custom_properties?.group_override?.toString() ||
                              null
                            }
                            onChange={(value) => {
                              const newValue = value ? parseInt(value) : null;
                              setGroupStates(
                                groupStates.map((state) => {
                                  if (
                                    state.channel_group === group.channel_group
                                  ) {
                                    return {
                                      ...state,
                                      custom_properties: {
                                        ...state.custom_properties,
                                        group_override: newValue,
                                      },
                                    };
                                  }
                                  return state;
                                })
                              );
                            }}
                            data={Object.values(channelGroups).map((g) => ({
                              value: g.id.toString(),
                              label: g.name,
                            }))}
                            clearable
                            searchable
                            size="xs"
                          />
                        </Tooltip>
                      )}

                      {/* Show stream profile select only if stream_profile_assignment is selected */}
                      {group.custom_properties?.stream_profile_id !==
                        undefined && (
                        <Tooltip
                          label="Select a stream profile to assign to all streams in this group during auto sync."
                          withArrow
                        >
                          <Select
                            label="Stream Profile"
                            placeholder="Choose stream profile..."
                            value={
                              group.custom_properties?.stream_profile_id?.toString() ||
                              null
                            }
                            onChange={(value) => {
                              const newValue = value ? parseInt(value) : null;
                              setGroupStates(
                                groupStates.map((state) => {
                                  if (
                                    state.channel_group === group.channel_group
                                  ) {
                                    return {
                                      ...state,
                                      custom_properties: {
                                        ...state.custom_properties,
                                        stream_profile_id: newValue,
                                      },
                                    };
                                  }
                                  return state;
                                })
                              );
                            }}
                            data={streamProfiles.map((profile) => ({
                              value: profile.id.toString(),
                              label: profile.name,
                            }))}
                            clearable
                            searchable
                            size="xs"
                          />
                        </Tooltip>
                      )}

                      {/* Show regex fields only if name_regex is selected */}
                      {(group.custom_properties?.name_regex_pattern !==
                        undefined ||
                        group.custom_properties?.name_replace_pattern !==
                          undefined) && (
                        <>
                          <Tooltip
                            label="Regex pattern to find in the channel name. Example: ^.*? - PPV\\d+ - (.+)$"
                            withArrow
                          >
                            <TextInput
                              label="Channel Name Find (Regex)"
                              placeholder="e.g. ^.*? - PPV\\d+ - (.+)$"
                              value={
                                group.custom_properties?.name_regex_pattern ||
                                ''
                              }
                              onChange={(e) => {
                                const val = e.currentTarget.value;
                                setGroupStates(
                                  groupStates.map((state) =>
                                    state.channel_group === group.channel_group
                                      ? {
                                          ...state,
                                          custom_properties: {
                                            ...state.custom_properties,
                                            name_regex_pattern: val,
                                          },
                                        }
                                      : state
                                  )
                                );
                              }}
                              size="xs"
                            />
                          </Tooltip>
                          <Tooltip
                            label="Replacement pattern for the channel name. Example: $1"
                            withArrow
                          >
                            <TextInput
                              label="Channel Name Replace"
                              placeholder="e.g. $1"
                              value={
                                group.custom_properties?.name_replace_pattern ||
                                ''
                              }
                              onChange={(e) => {
                                const val = e.currentTarget.value;
                                setGroupStates(
                                  groupStates.map((state) =>
                                    state.channel_group === group.channel_group
                                      ? {
                                          ...state,
                                          custom_properties: {
                                            ...state.custom_properties,
                                            name_replace_pattern: val,
                                          },
                                        }
                                      : state
                                  )
                                );
                              }}
                              size="xs"
                            />
                          </Tooltip>
                        </>
                      )}

                      {/* Show name_match_regex field only if selected */}
                      {group.custom_properties?.name_match_regex !==
                        undefined && (
                        <Tooltip
                          label="Only channels whose names match this regex will be included. Example: ^Sports.*"
                          withArrow
                        >
                          <TextInput
                            label="Channel Name Filter (Regex)"
                            placeholder="e.g. ^Sports.*"
                            value={
                              group.custom_properties?.name_match_regex || ''
                            }
                            onChange={(e) => {
                              const val = e.currentTarget.value;
                              setGroupStates(
                                groupStates.map((state) =>
                                  state.channel_group === group.channel_group
                                    ? {
                                        ...state,
                                        custom_properties: {
                                          ...state.custom_properties,
                                          name_match_regex: val,
                                        },
                                      }
                                    : state
                                )
                              );
                            }}
                            size="xs"
                          />
                        </Tooltip>
                      )}
                    </>
                  )}
                </Stack>
              </Group>
            ))}
        </SimpleGrid>
      </Box>
    </Stack>
  );
};

export default LiveGroupFilter;
