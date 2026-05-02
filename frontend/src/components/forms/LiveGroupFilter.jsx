// Modal.js
import React, { forwardRef, useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Center,
  Checkbox,
  Divider,
  Flex,
  Group,
  MultiSelect,
  NumberInput,
  Popover,
  PopoverDropdown,
  PopoverTarget,
  ScrollArea,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { CircleCheck, CircleX, Info } from 'lucide-react';
import useChannelsStore from '../../store/channels';
import useStreamProfilesStore from '../../store/streamProfiles';
import { useChannelLogoSelection } from '../../hooks/useSmartLogos';
import { FixedSizeList as List } from 'react-window';
import LazyLogo from '../LazyLogo';
import LogoForm from './Logo';
import logo from '../../images/logo.png';
import {
  ADVANCED_OPTIONS_CONFIG,
  applyAdvancedOptionsChange,
  getEPGs,
  getEpgSourceData,
  getEpgSourceValue,
  getSelectedAdvancedOptions,
} from '../../utils/forms/LiveGroupFilterUtils.js';

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

const LogoPopover = ({
  group,
  channelLogos,
  logosLoading,
  onPopoverChange,
  onLogoInputClick,
  onFilterChange,
  onLogoSelect,
}) => {
  const renderLogoList = () => {
    const logoOptions = [
      { id: '0', name: 'Default' },
      ...Object.values(channelLogos),
    ];
    const filteredLogos = logoOptions.filter((logo) =>
      logo.name.toLowerCase().includes((group.logoFilter || '').toLowerCase())
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
              onClick={() =>
                onLogoSelect(logoItem.id === '0' ? null : logoItem.id)
              }
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = 'rgb(68, 68, 68)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = 'transparent';
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
  };

  return (
    <Popover
      opened={group.logoPopoverOpened || false}
      onChange={onPopoverChange}
      withArrow
    >
      <PopoverTarget>
        <TextInput
          label="Custom Logo"
          readOnly
          value={
            channelLogos[group.custom_properties?.custom_logo_id]?.name ||
            'Default'
          }
          onClick={onLogoInputClick}
          size="xs"
        />
      </PopoverTarget>

      <PopoverDropdown onMouseDown={(e) => e.stopPropagation()}>
        <Group>
          <TextInput
            placeholder="Filter logos..."
            size="xs"
            value={group.logoFilter || ''}
            onChange={(e) => onFilterChange(e.currentTarget.value)}
          />
          {logosLoading && (
            <Text size="xs" c="dimmed">
              Loading...
            </Text>
          )}
        </Group>

        <ScrollArea style={{ height: 200 }}>{renderLogoList()}</ScrollArea>
      </PopoverDropdown>
    </Popover>
  );
};

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
  const [statusFilter, setStatusFilter] = useState('all');
  const [epgSources, setEpgSources] = useState([]);

  // Logo selection functionality
  const {
    logos: channelLogos,
    ensureLogosLoaded,
    isLoading: logosLoading,
  } = useChannelLogoSelection();
  const [logoModalOpen, setLogoModalOpen] = useState(false);
  const [currentEditingGroupId, setCurrentEditingGroupId] = useState(null);

  // Ensure logos are loaded when component mounts
  useEffect(() => {
    ensureLogosLoaded();
  }, [ensureLogosLoaded]);

  // Fetch stream profiles when component mounts
  useEffect(() => {
    if (streamProfiles.length === 0) {
      fetchStreamProfiles();
    }
  }, [streamProfiles.length, fetchStreamProfiles]);

  // Fetch EPG sources when component mounts
  useEffect(() => {
    const fetchEPGSources = async () => {
      try {
        const sources = await getEPGs();
        setEpgSources(sources || []);
      } catch (error) {
        console.error('Failed to fetch EPG sources:', error);
      }
    };
    fetchEPGSources();
  }, []);

  useEffect(() => {
    if (Object.keys(channelGroups).length === 0) {
      return;
    }

    setGroupStates(
      playlist.channel_groups
        .filter((group) => channelGroups[group.channel_group]) // Filter out groups that don't exist
        .map((group) => {
          // Parse custom_properties if present
          let customProps = {};
          if (group.custom_properties) {
            try {
              customProps =
                typeof group.custom_properties === 'string'
                  ? JSON.parse(group.custom_properties)
                  : group.custom_properties;
            } catch {
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

  const updateGroupState = useCallback(
    (id, updater) => {
      setGroupStates((prev) =>
        prev.map((state) =>
          state.channel_group == id ? { ...state, ...updater(state) } : state
        )
      );
    },
    [setGroupStates]
  );

  const updateCustomProps = useCallback(
    (id, propsUpdater) => {
      updateGroupState(id, (state) => ({
        custom_properties: {
          ...state.custom_properties,
          ...propsUpdater(state.custom_properties || {}),
        },
      }));
    },
    [updateGroupState]
  );

  const toggleGroupEnabled = useCallback(
    (id) => {
      updateGroupState(id, (state) => ({ enabled: !state.enabled }));
    },
    [updateGroupState]
  );

  const toggleAutoSync = useCallback(
    (id) => {
      updateGroupState(id, (state) => ({
        auto_channel_sync: !state.auto_channel_sync,
      }));
    },
    [updateGroupState]
  );

  const updateChannelStart = useCallback(
    (id, value) => {
      updateGroupState(id, () => ({ auto_sync_channel_start: value }));
    },
    [updateGroupState]
  );

  // Handle logo selection from LogoForm
  const handleLogoSuccess = ({ logo }) => {
    if (logo && logo.id && currentEditingGroupId !== null) {
      updateCustomProps(currentEditingGroupId, () => ({
        custom_logo_id: logo.id,
      }));
      ensureLogosLoaded(); // Refresh logos
    }
    setLogoModalOpen(false);
    setCurrentEditingGroupId(null);
  };

  const isVisible = (group) => {
    const matchesText = group.name
      .toLowerCase()
      .includes(groupFilter.toLowerCase());
    const matchesStatus =
      statusFilter === 'all' ||
      (statusFilter === 'enabled' && group.enabled) ||
      (statusFilter === 'disabled' && !group.enabled);
    return matchesText && matchesStatus;
  };

  const selectAll = () => {
    setGroupStates((prev) =>
      prev.map((state) => ({
        ...state,
        enabled: isVisible(state) ? true : state.enabled,
      }))
    );
  };

  const deselectAll = () => {
    setGroupStates((prev) =>
      prev.map((state) => ({
        ...state,
        enabled: isVisible(state) ? false : state.enabled,
      }))
    );
  };

  const handleChangeEpgSource = (group, value) => {
    updateGroupState(group.channel_group, (state) => {
      const newProps = { ...state.custom_properties };
      if (value === '0') {
        // "No EPG (Disabled)" selected
        delete newProps.custom_epg_id;
        delete newProps.force_epg_selected;
        newProps.force_dummy_epg = true;
      } else if (value) {
        // Specific EPG source selected
        newProps.custom_epg_id = parseInt(value);
        delete newProps.force_dummy_epg;
        delete newProps.force_epg_selected;
      } else {
        // Cleared - remove all EPG settings
        delete newProps.custom_epg_id;
        delete newProps.force_dummy_epg;
        delete newProps.force_epg_selected;
      }
      return { custom_properties: newProps };
    });
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

      <Flex gap="sm" align="center">
        <TextInput
          placeholder="Filter groups..."
          value={groupFilter}
          onChange={(event) => setGroupFilter(event.currentTarget.value)}
          style={{ flex: 1 }}
          size="xs"
        />
        <SegmentedControl
          value={statusFilter}
          onChange={setStatusFilter}
          size="xs"
          data={[
            { label: 'All', value: 'all' },
            { label: 'Enabled', value: 'enabled' },
            { label: 'Disabled', value: 'disabled' },
          ]}
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
            .filter((group) => isVisible(group))
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
                <Tooltip
                  label={
                    group.enabled && group.is_stale
                      ? 'This group was not seen in the last M3U refresh and will be deleted after the retention period expires'
                      : ''
                  }
                  disabled={!group.enabled || !group.is_stale}
                  multiline
                  w={220}
                >
                  <Button
                    color={
                      group.enabled
                        ? group.is_stale
                          ? 'orange'
                          : 'green'
                        : 'gray'
                    }
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
                </Tooltip>

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
                      <Tooltip
                        label={
                          <div>
                            <div>
                              <strong>Fixed:</strong> Start at a specific number
                              and increment
                            </div>
                            <div>
                              <strong>Provider:</strong> Use channel numbers
                              from the M3U source
                            </div>
                            <div>
                              <strong>Next Available:</strong> Auto-assign
                              starting from 1, skipping used numbers
                            </div>
                          </div>
                        }
                        withArrow
                        multiline
                        w={280}
                        openDelay={500}
                      >
                        <Select
                          label="Channel Numbering Mode"
                          placeholder="Select mode..."
                          value={
                            group.custom_properties?.channel_numbering_mode ||
                            'fixed'
                          }
                          onChange={(value) => {
                            updateCustomProps(group.channel_group, () => ({
                              channel_numbering_mode: value || 'fixed',
                            }));
                          }}
                          data={[
                            {
                              value: 'fixed',
                              label: 'Fixed Start Number',
                            },
                            {
                              value: 'provider',
                              label: 'Use Provider Number',
                            },
                            {
                              value: 'next_available',
                              label: 'Next Available',
                            },
                          ]}
                          size="xs"
                        />
                      </Tooltip>

                      {(!group.custom_properties?.channel_numbering_mode ||
                        group.custom_properties?.channel_numbering_mode ===
                          'fixed') && (
                        <NumberInput
                          label="Start Channel #"
                          value={group.auto_sync_channel_start}
                          onChange={(value) =>
                            updateChannelStart(group.channel_group, value)
                          }
                          min={1}
                          step={1}
                          size="xs"
                          precision={0}
                        />
                      )}

                      {group.custom_properties?.channel_numbering_mode ===
                        'provider' && (
                        <NumberInput
                          label="Fallback Channel # (if provider # missing)"
                          value={
                            group.custom_properties
                              ?.channel_numbering_fallback || 1
                          }
                          onChange={(value) => {
                            updateCustomProps(group.channel_group, () => ({
                              channel_numbering_fallback: value || 1,
                            }));
                          }}
                          min={1}
                          step={1}
                          size="xs"
                          precision={0}
                        />
                      )}

                      {/* Auto Channel Sync Options Multi-Select */}
                      <MultiSelect
                        label="Advanced Options"
                        placeholder="Select options..."
                        data={ADVANCED_OPTIONS_CONFIG.map(
                          ({ value, label, description }) => ({
                            value,
                            label,
                            description,
                          })
                        )}
                        itemComponent={OptionWithTooltip}
                        value={getSelectedAdvancedOptions(
                          group.custom_properties
                        )}
                        onChange={(newValues) =>
                          updateGroupState(group.channel_group, (state) => ({
                            custom_properties: applyAdvancedOptionsChange(
                              state.custom_properties,
                              newValues
                            ),
                          }))
                        }
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
                              updateCustomProps(group.channel_group, () => ({
                                channel_sort_order: value || '',
                              }));
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
                          <Flex align="center" gap="xs" mt="xs">
                            <Checkbox
                              label="Reverse Sort Order"
                              checked={
                                group.custom_properties?.channel_sort_reverse ||
                                false
                              }
                              onChange={(event) => {
                                updateCustomProps(group.channel_group, () => ({
                                  channel_sort_reverse: event.target.checked,
                                }));
                              }}
                              size="xs"
                            />
                          </Flex>
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
                              updateCustomProps(group.channel_group, () => ({
                                channel_profile_ids: value || [],
                              }));
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
                              updateCustomProps(group.channel_group, () => ({
                                group_override: newValue,
                              }));
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
                              updateCustomProps(group.channel_group, () => ({
                                stream_profile_id: newValue,
                              }));
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
                                updateCustomProps(group.channel_group, () => ({
                                  name_regex_pattern: val,
                                }));
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
                                updateCustomProps(group.channel_group, () => ({
                                  name_replace_pattern: val,
                                }));
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
                              updateCustomProps(group.channel_group, () => ({
                                name_match_regex: val,
                              }));
                            }}
                            size="xs"
                          />
                        </Tooltip>
                      )}

                      {/* Show logo selector only if custom_logo is selected */}
                      {group.custom_properties?.custom_logo_id !==
                        undefined && (
                        <Box>
                          <Group justify="space-between">
                            <LogoPopover
                              group={group}
                              channelLogos={channelLogos}
                              logosLoading={logosLoading}
                              onPopoverChange={(opened) => {
                                updateGroupState(group.channel_group, () => ({
                                  logoPopoverOpened: opened,
                                }));
                                if (opened) ensureLogosLoaded();
                              }}
                              onLogoInputClick={() => {
                                setGroupStates((prev) =>
                                  prev.map((state) => ({
                                    ...state,
                                    logoPopoverOpened:
                                      state.channel_group ===
                                      group.channel_group,
                                  }))
                                );
                              }}
                              onFilterChange={(val) => {
                                updateGroupState(group.channel_group, () => ({
                                  logoFilter: val,
                                }));
                              }}
                              onLogoSelect={(logoId) => {
                                updateCustomProps(group.channel_group, () => ({
                                  custom_logo_id: logoId,
                                }));
                              }}
                            />

                            <Stack gap="xs" align="center">
                              <LazyLogo
                                logoId={group.custom_properties?.custom_logo_id}
                                alt="custom logo"
                                style={{ height: 40 }}
                              />
                            </Stack>
                          </Group>

                          <Button
                            onClick={() => {
                              setCurrentEditingGroupId(group.channel_group);
                              setLogoModalOpen(true);
                            }}
                            fullWidth
                            variant="default"
                            size="xs"
                            mt="xs"
                          >
                            Upload or Create Logo
                          </Button>
                        </Box>
                      )}

                      {/* Show EPG selector when force_epg is selected */}
                      {(group.custom_properties?.custom_epg_id !== undefined ||
                        group.custom_properties?.force_dummy_epg ||
                        group.custom_properties?.force_epg_selected) && (
                        <Tooltip
                          label="Force a specific EPG source for all auto-synced channels in this group. For dummy EPGs, all channels will share the same EPG data. For regular EPG sources (XMLTV, Schedules Direct), channels will be matched by their tvg_id within that source. Select 'No EPG' to disable EPG assignment."
                          withArrow
                        >
                          <Select
                            label="EPG Source"
                            placeholder="No EPG (Disabled)"
                            value={getEpgSourceValue(group)}
                            onChange={(value) => {
                              handleChangeEpgSource(group, value);
                            }}
                            data={getEpgSourceData(epgSources)}
                            clearable
                            searchable
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

      {/* Logo Upload Modal */}
      <LogoForm
        isOpen={logoModalOpen}
        onClose={() => {
          setLogoModalOpen(false);
          setCurrentEditingGroupId(null);
        }}
        onSuccess={handleLogoSuccess}
      />
    </Stack>
  );
};

export default LiveGroupFilter;
