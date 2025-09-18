import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useFormik } from 'formik';
import * as Yup from 'yup';
import useChannelsStore from '../../store/channels';
import API from '../../api';
import useStreamProfilesStore from '../../store/streamProfiles';
import useStreamsStore from '../../store/streams';
import ChannelGroupForm from './ChannelGroup';
import usePlaylistsStore from '../../store/playlists';
import logo from '../../images/logo.png';
import { useChannelLogoSelection } from '../../hooks/useSmartLogos';
import useLogosStore from '../../store/logos';
import LazyLogo from '../LazyLogo';
import {
  Box,
  Button,
  Modal,
  TextInput,
  NativeSelect,
  Text,
  Group,
  ActionIcon,
  Center,
  Grid,
  Flex,
  Select,
  Divider,
  Stack,
  useMantineTheme,
  Popover,
  ScrollArea,
  Tooltip,
  NumberInput,
  Image,
  UnstyledButton,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { ListOrdered, SquarePlus, SquareX, X, Zap } from 'lucide-react';
import useEPGsStore from '../../store/epgs';
import { Dropzone } from '@mantine/dropzone';
import { FixedSizeList as List } from 'react-window';
import { USER_LEVELS, USER_LEVEL_LABELS } from '../../constants';

const ChannelForm = ({ channel = null, isOpen, onClose }) => {
  const theme = useMantineTheme();

  const listRef = useRef(null);
  const logoListRef = useRef(null);
  const groupListRef = useRef(null);

  const channelGroups = useChannelsStore((s) => s.channelGroups);
  const canEditChannelGroup = useChannelsStore((s) => s.canEditChannelGroup);

  const {
    logos: channelLogos,
    ensureLogosLoaded,
    isLoading: logosLoading,
  } = useChannelLogoSelection();

  // Import the full logos store for duplicate checking
  const allLogos = useLogosStore((s) => s.logos);

  // Ensure logos are loaded when component mounts
  useEffect(() => {
    ensureLogosLoaded();
  }, [ensureLogosLoaded]);
  const streams = useStreamsStore((state) => state.streams);
  const streamProfiles = useStreamProfilesStore((s) => s.profiles);
  const playlists = usePlaylistsStore((s) => s.playlists);
  const epgs = useEPGsStore((s) => s.epgs);
  const tvgs = useEPGsStore((s) => s.tvgs);
  const tvgsById = useEPGsStore((s) => s.tvgsById);

  const [logoPreview, setLogoPreview] = useState(null);
  const [channelStreams, setChannelStreams] = useState([]);
  const [channelGroupModelOpen, setChannelGroupModalOpen] = useState(false);
  const [epgPopoverOpened, setEpgPopoverOpened] = useState(false);
  const [logoPopoverOpened, setLogoPopoverOpened] = useState(false);
  const [selectedEPG, setSelectedEPG] = useState('');
  const [tvgFilter, setTvgFilter] = useState('');
  const [logoFilter, setLogoFilter] = useState('');

  const [groupPopoverOpened, setGroupPopoverOpened] = useState(false);
  const [groupFilter, setGroupFilter] = useState('');
  const [autoMatchLoading, setAutoMatchLoading] = useState(false);
  const groupOptions = Object.values(channelGroups);

  const addStream = (stream) => {
    const streamSet = new Set(channelStreams);
    streamSet.add(stream);
    setChannelStreams(Array.from(streamSet));
  };

  const removeStream = (stream) => {
    const streamSet = new Set(channelStreams);
    streamSet.delete(stream);
    setChannelStreams(Array.from(streamSet));
  };

  const handleLogoChange = async (files) => {
    if (files.length === 1) {
      const file = files[0];

      // Validate file size on frontend first
      if (file.size > 5 * 1024 * 1024) {
        // 5MB
        notifications.show({
          title: 'Error',
          message: 'File too large. Maximum size is 5MB.',
          color: 'red',
        });
        return;
      }

      try {
        const retval = await API.uploadLogo(file);
        // Note: API.uploadLogo already adds the logo to the store, no need to fetch
        setLogoPreview(retval.cache_url);
        formik.setFieldValue('logo_id', retval.id);
      } catch (error) {
        console.error('Logo upload failed:', error);
        // Error notification is already handled in API.uploadLogo
      }
    } else {
      setLogoPreview(null);
    }
  };

  const handleAutoMatchEpg = async () => {
    // Only attempt auto-match for existing channels (editing mode)
    if (!channel || !channel.id) {
      notifications.show({
        title: 'Info',
        message: 'Auto-match is only available when editing existing channels.',
        color: 'blue',
      });
      return;
    }

    setAutoMatchLoading(true);
    try {
      const response = await API.matchChannelEpg(channel.id);

      if (response.matched) {
        // Update the form with the new EPG data
        if (response.channel && response.channel.epg_data_id) {
          formik.setFieldValue('epg_data_id', response.channel.epg_data_id);
        }

        notifications.show({
          title: 'Success',
          message: response.message,
          color: 'green',
        });
      } else {
        notifications.show({
          title: 'No Match Found',
          message: response.message,
          color: 'orange',
        });
      }
    } catch (error) {
      notifications.show({
        title: 'Error',
        message: 'Failed to auto-match EPG data',
        color: 'red',
      });
      console.error('Auto-match error:', error);
    } finally {
      setAutoMatchLoading(false);
    }
  };

  const handleSetNameFromEpg = () => {
    const epgDataId = formik.values.epg_data_id;
    if (!epgDataId) {
      notifications.show({
        title: 'No EPG Selected',
        message: 'Please select an EPG source first.',
        color: 'orange',
      });
      return;
    }

    const tvg = tvgsById[epgDataId];
    if (tvg && tvg.name) {
      formik.setFieldValue('name', tvg.name);
      notifications.show({
        title: 'Success',
        message: `Channel name set to "${tvg.name}"`,
        color: 'green',
      });
    } else {
      notifications.show({
        title: 'No Name Available',
        message: 'No name found in the selected EPG data.',
        color: 'orange',
      });
    }
  };

  const handleSetLogoFromEpg = async () => {
    const epgDataId = formik.values.epg_data_id;
    if (!epgDataId) {
      notifications.show({
        title: 'No EPG Selected',
        message: 'Please select an EPG source first.',
        color: 'orange',
      });
      return;
    }

    const tvg = tvgsById[epgDataId];
    if (!tvg || !tvg.icon_url) {
      notifications.show({
        title: 'No EPG Icon',
        message: 'EPG data does not have an icon URL.',
        color: 'orange',
      });
      return;
    }

    try {
      // Try to find a logo that matches the EPG icon URL - check ALL logos to avoid duplicates
      let matchingLogo = Object.values(allLogos).find(
        (logo) => logo.url === tvg.icon_url
      );

      if (matchingLogo) {
        formik.setFieldValue('logo_id', matchingLogo.id);
        notifications.show({
          title: 'Success',
          message: `Logo set to "${matchingLogo.name}"`,
          color: 'green',
        });
      } else {
        // Logo doesn't exist - create it
        notifications.show({
          id: 'creating-logo',
          title: 'Creating Logo',
          message: `Creating new logo from EPG icon URL...`,
          loading: true,
        });

        try {
          const newLogoData = {
            name: tvg.name || `Logo for ${tvg.icon_url}`,
            url: tvg.icon_url,
          };

          // Create logo by calling the Logo API directly
          const newLogo = await API.createLogo(newLogoData);

          formik.setFieldValue('logo_id', newLogo.id);

          notifications.update({
            id: 'creating-logo',
            title: 'Success',
            message: `Created and assigned new logo "${newLogo.name}"`,
            loading: false,
            color: 'green',
            autoClose: 5000,
          });
        } catch (createError) {
          notifications.update({
            id: 'creating-logo',
            title: 'Error',
            message: 'Failed to create logo from EPG icon URL',
            loading: false,
            color: 'red',
            autoClose: 5000,
          });
          throw createError;
        }
      }
    } catch (error) {
      notifications.show({
        title: 'Error',
        message: 'Failed to set logo from EPG data',
        color: 'red',
      });
      console.error('Set logo from EPG error:', error);
    }
  };

  const formik = useFormik({
    initialValues: {
      name: '',
      channel_number: '', // Change from 0 to empty string for consistency
      channel_group_id:
        Object.keys(channelGroups).length > 0
          ? Object.keys(channelGroups)[0]
          : '',
      stream_profile_id: '0',
      tvg_id: '',
      tvc_guide_stationid: '',
      epg_data_id: '',
      logo_id: '',
      user_level: '0',
    },
    validationSchema: Yup.object({
      name: Yup.string().required('Name is required'),
      channel_group_id: Yup.string().required('Channel group is required'),
    }),
    onSubmit: async (values, { setSubmitting }) => {
      let response;

      try {
        const formattedValues = { ...values };

        // Convert empty or "0" stream_profile_id to null for the API
        if (
          !formattedValues.stream_profile_id ||
          formattedValues.stream_profile_id === '0'
        ) {
          formattedValues.stream_profile_id = null;
        }

        // Ensure tvg_id is properly included (no empty strings)
        formattedValues.tvg_id = formattedValues.tvg_id || null;

        // Ensure tvc_guide_stationid is properly included (no empty strings)
        formattedValues.tvc_guide_stationid =
          formattedValues.tvc_guide_stationid || null;

        if (channel) {
          // If there's an EPG to set, use our enhanced endpoint
          if (values.epg_data_id !== (channel.epg_data_id ?? '')) {
            // Use the special endpoint to set EPG and trigger refresh
            const epgResponse = await API.setChannelEPG(
              channel.id,
              values.epg_data_id
            );

            // Remove epg_data_id from values since we've handled it separately
            const { epg_data_id, ...otherValues } = formattedValues;

            // Update other channel fields if needed
            if (Object.keys(otherValues).length > 0) {
              response = await API.updateChannel({
                id: channel.id,
                ...otherValues,
                streams: channelStreams.map((stream) => stream.id),
              });
            }
          } else {
            // No EPG change, regular update
            response = await API.updateChannel({
              id: channel.id,
              ...formattedValues,
              streams: channelStreams.map((stream) => stream.id),
            });
          }
        } else {
          // New channel creation - use the standard method
          response = await API.addChannel({
            ...formattedValues,
            streams: channelStreams.map((stream) => stream.id),
          });
        }
      } catch (error) {
        console.error('Error saving channel:', error);
      }

      formik.resetForm();
      API.requeryChannels();

      // Refresh channel profiles to update the membership information
      useChannelsStore.getState().fetchChannelProfiles();

      setSubmitting(false);
      setTvgFilter('');
      setLogoFilter('');
      onClose();
    },
  });

  useEffect(() => {
    if (channel) {
      if (channel.epg_data_id) {
        const epgSource = epgs[tvgsById[channel.epg_data_id]?.epg_source];
        setSelectedEPG(epgSource ? `${epgSource.id}` : '');
      }

      formik.setValues({
        name: channel.name || '',
        channel_number:
          channel.channel_number !== null ? channel.channel_number : '',
        channel_group_id: channel.channel_group_id
          ? `${channel.channel_group_id}`
          : '',
        stream_profile_id: channel.stream_profile_id
          ? `${channel.stream_profile_id}`
          : '0',
        tvg_id: channel.tvg_id || '',
        tvc_guide_stationid: channel.tvc_guide_stationid || '',
        epg_data_id: channel.epg_data_id ?? '',
        logo_id: channel.logo_id ? `${channel.logo_id}` : '',
        user_level: `${channel.user_level}`,
      });

      setChannelStreams(channel.streams || []);
    } else {
      formik.resetForm();
      setTvgFilter('');
      setLogoFilter('');
      setChannelStreams([]); // Ensure streams are cleared when adding a new channel
    }
  }, [channel, tvgsById, channelGroups]);

  // Memoize logo options to prevent infinite re-renders during background loading
  const logoOptions = useMemo(() => {
    const options = [{ id: '0', name: 'Default' }].concat(
      Object.values(channelLogos)
    );
    return options;
  }, [channelLogos]); // Only depend on channelLogos object

  // Update the handler for when channel group modal is closed
  const handleChannelGroupModalClose = (newGroup) => {
    setChannelGroupModalOpen(false);

    // If a new group was created and returned, update the form with it
    if (newGroup && newGroup.id) {
      // Preserve all current form values while updating just the channel_group_id
      formik.setValues({
        ...formik.values,
        channel_group_id: `${newGroup.id}`,
      });
    }
  };

  if (!isOpen) {
    return <></>;
  }

  const filteredTvgs = tvgs
    .filter((tvg) => tvg.epg_source == selectedEPG)
    .filter(
      (tvg) =>
        tvg.name.toLowerCase().includes(tvgFilter.toLowerCase()) ||
        tvg.tvg_id.toLowerCase().includes(tvgFilter.toLowerCase())
    );

  const filteredLogos = logoOptions.filter((logo) =>
    logo.name.toLowerCase().includes(logoFilter.toLowerCase())
  );

  const filteredGroups = groupOptions.filter((group) =>
    group.name.toLowerCase().includes(groupFilter.toLowerCase())
  );

  return (
    <>
      <Modal
        opened={isOpen}
        onClose={onClose}
        size={1000}
        title={
          <Group gap="5">
            <ListOrdered size="20" />
            <Text>Channels</Text>
          </Group>
        }
        styles={{ content: { '--mantine-color-body': '#27272A' } }}
      >
        <form onSubmit={formik.handleSubmit}>
          <Group justify="space-between" align="top">
            <Stack gap="5" style={{ flex: 1 }}>
              <TextInput
                id="name"
                name="name"
                label={
                  <Group gap="xs">
                    <span>Channel Name</span>
                    {formik.values.epg_data_id && (
                      <Button
                        size="xs"
                        variant="transparent"
                        onClick={handleSetNameFromEpg}
                        title="Set channel name from EPG data"
                        p={0}
                        h="auto"
                      >
                        Use EPG Name
                      </Button>
                    )}
                  </Group>
                }
                value={formik.values.name}
                onChange={formik.handleChange}
                error={formik.errors.name ? formik.touched.name : ''}
                size="xs"
                style={{ flex: 1 }}
              />

              <Flex gap="sm">
                <Popover
                  opened={groupPopoverOpened}
                  onChange={setGroupPopoverOpened}
                  // position="bottom-start"
                  withArrow
                >
                  <Popover.Target>
                    <TextInput
                      id="channel_group_id"
                      name="channel_group_id"
                      label="Channel Group"
                      readOnly
                      value={
                        channelGroups[formik.values.channel_group_id]
                          ? channelGroups[formik.values.channel_group_id].name
                          : ''
                      }
                      onClick={() => setGroupPopoverOpened(true)}
                      size="xs"
                    />
                  </Popover.Target>

                  <Popover.Dropdown onMouseDown={(e) => e.stopPropagation()}>
                    <Group>
                      <TextInput
                        placeholder="Filter"
                        value={groupFilter}
                        onChange={(event) =>
                          setGroupFilter(event.currentTarget.value)
                        }
                        mb="xs"
                        size="xs"
                      />
                    </Group>

                    <ScrollArea style={{ height: 200 }}>
                      <List
                        height={200} // Set max height for visible items
                        itemCount={filteredGroups.length}
                        itemSize={20} // Adjust row height for each item
                        width={200}
                        ref={groupListRef}
                      >
                        {({ index, style }) => (
                          <Box
                            style={{ ...style, height: 20, overflow: 'hidden' }}
                          >
                            <Tooltip
                              openDelay={500}
                              label={filteredGroups[index].name}
                              size="xs"
                            >
                              <UnstyledButton
                                onClick={() => {
                                  formik.setFieldValue(
                                    'channel_group_id',
                                    filteredGroups[index].id
                                  );
                                  setGroupPopoverOpened(false);
                                }}
                              >
                                <Text
                                  size="xs"
                                  style={{
                                    whiteSpace: 'nowrap',
                                    overflow: 'hidden',
                                    textOverflow: 'ellipsis',
                                  }}
                                >
                                  {filteredGroups[index].name}
                                </Text>
                              </UnstyledButton>
                            </Tooltip>
                          </Box>
                        )}
                      </List>
                    </ScrollArea>
                  </Popover.Dropdown>
                </Popover>

                {/* <Select
                  id="channel_group_id"
                  name="channel_group_id"
                  label="Channel Group"
                  value={formik.values.channel_group_id}
                  searchable
                  onChange={(value) => {
                    formik.setFieldValue('channel_group_id', value); // Update Formik's state with the new value
                  }}
                  error={
                    formik.errors.channel_group_id
                      ? formik.touched.channel_group_id
                      : ''
                  }
                  data={Object.values(channelGroups).map((option, index) => ({
                    value: `${option.id}`,
                    label: option.name,
                  }))}
                  size="xs"
                  style={{ flex: 1 }}
                /> */}
                <Flex align="flex-end">
                  <ActionIcon
                    color={theme.tailwind.green[5]}
                    onClick={() => setChannelGroupModalOpen(true)}
                    title="Create new group"
                    size="small"
                    variant="transparent"
                    style={{ marginBottom: 5 }}
                  >
                    <SquarePlus size="20" />
                  </ActionIcon>
                </Flex>
              </Flex>

              <Select
                id="stream_profile_id"
                label="Stream Profile"
                name="stream_profile_id"
                value={formik.values.stream_profile_id}
                onChange={(value) => {
                  formik.setFieldValue('stream_profile_id', value); // Update Formik's state with the new value
                }}
                error={
                  formik.errors.stream_profile_id
                    ? formik.touched.stream_profile_id
                    : ''
                }
                data={[{ value: '0', label: '(use default)' }].concat(
                  streamProfiles.map((option) => ({
                    value: `${option.id}`,
                    label: option.name,
                  }))
                )}
                size="xs"
              />

              <Select
                label="User Level Access"
                data={Object.entries(USER_LEVELS).map(([, value]) => {
                  return {
                    label: USER_LEVEL_LABELS[value],
                    value: `${value}`,
                  };
                })}
                value={formik.values.user_level}
                onChange={(value) => {
                  formik.setFieldValue('user_level', value);
                }}
                error={
                  formik.errors.user_level ? formik.touched.user_level : ''
                }
              />
            </Stack>

            <Divider size="sm" orientation="vertical" />

            <Stack justify="flex-start" style={{ flex: 1 }}>
              <Group justify="space-between">
                <Popover
                  opened={logoPopoverOpened}
                  onChange={(opened) => {
                    setLogoPopoverOpened(opened);
                    // Load all logos when popover is opened
                    if (opened) {
                      console.log(
                        'Popover opened, calling ensureLogosLoaded...'
                      );
                      ensureLogosLoaded();
                    }
                  }}
                  // position="bottom-start"
                  withArrow
                >
                  <Popover.Target>
                    <TextInput
                      id="logo_id"
                      name="logo_id"
                      label={
                        <Group gap="xs">
                          <span>Logo</span>
                          {formik.values.epg_data_id && (
                            <Button
                              size="xs"
                              variant="transparent"
                              onClick={handleSetLogoFromEpg}
                              title="Find matching logo based on EPG icon URL"
                              p={0}
                              h="auto"
                            >
                              Use EPG Logo
                            </Button>
                          )}
                        </Group>
                      }
                      readOnly
                      value={
                        channelLogos[formik.values.logo_id]?.name || 'Default'
                      }
                      onClick={() => {
                        console.log(
                          'Logo input clicked, setting popover opened to true'
                        );
                        setLogoPopoverOpened(true);
                      }}
                      size="xs"
                    />
                  </Popover.Target>

                  <Popover.Dropdown onMouseDown={(e) => e.stopPropagation()}>
                    <Group>
                      <TextInput
                        placeholder="Filter"
                        value={logoFilter}
                        onChange={(event) =>
                          setLogoFilter(event.currentTarget.value)
                        }
                        mb="xs"
                        size="xs"
                      />
                      {logosLoading && (
                        <Text size="xs" c="dimmed">
                          Loading...
                        </Text>
                      )}
                    </Group>

                    <ScrollArea style={{ height: 200 }}>
                      {filteredLogos.length === 0 ? (
                        <Center style={{ height: 200 }}>
                          <Text size="sm" c="dimmed">
                            {logoFilter
                              ? 'No logos match your filter'
                              : 'No logos available'}
                          </Text>
                        </Center>
                      ) : (
                        <List
                          height={200} // Set max height for visible items
                          itemCount={filteredLogos.length}
                          itemSize={55} // Increased row height for logo + text
                          style={{ width: '100%' }}
                          ref={logoListRef}
                        >
                          {({ index, style }) => (
                            <div
                              style={{
                                ...style,
                                cursor: 'pointer',
                                padding: '5px',
                                borderRadius: '4px',
                              }}
                              onClick={() => {
                                formik.setFieldValue(
                                  'logo_id',
                                  filteredLogos[index].id
                                );
                                setLogoPopoverOpened(false);
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
                                style={{ flexDirection: 'column', gap: '2px' }}
                              >
                                <img
                                  src={filteredLogos[index].cache_url || logo}
                                  height="30"
                                  style={{ maxWidth: 80, objectFit: 'contain' }}
                                  alt={filteredLogos[index].name || 'Logo'}
                                  onError={(e) => {
                                    // Fallback to default logo if image fails to load
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
                                  {filteredLogos[index].name || 'Default'}
                                </Text>
                              </Center>
                            </div>
                          )}
                        </List>
                      )}
                    </ScrollArea>
                  </Popover.Dropdown>
                </Popover>

                <Stack gap="xs" align="center">
                  <LazyLogo
                    logoId={formik.values.logo_id}
                    alt="channel logo"
                    style={{ height: 40 }}
                  />
                </Stack>
              </Group>

              <Group>
                <Divider size="xs" style={{ flex: 1 }} />
                <Text size="xs" c="dimmed">
                  OR
                </Text>
                <Divider size="xs" style={{ flex: 1 }} />
              </Group>

              <Stack>
                <Text size="sm">Upload Logo</Text>
                <Dropzone
                  onDrop={handleLogoChange}
                  onReject={(files) => console.log('rejected files', files)}
                  maxSize={5 * 1024 ** 2}
                >
                  <Group
                    justify="center"
                    gap="xl"
                    mih={40}
                    style={{ pointerEvents: 'none' }}
                  >
                    <Text size="sm" inline>
                      Drag images here or click to select files
                    </Text>
                  </Group>
                </Dropzone>

                <Center></Center>
              </Stack>
            </Stack>

            <Divider size="sm" orientation="vertical" />

            <Stack gap="5" style={{ flex: 1 }} justify="flex-start">
              <NumberInput
                id="channel_number"
                name="channel_number"
                label="Channel # (blank to auto-assign)"
                value={formik.values.channel_number}
                onChange={(value) =>
                  formik.setFieldValue('channel_number', value)
                }
                error={
                  formik.errors.channel_number
                    ? formik.touched.channel_number
                    : ''
                }
                size="xs"
                step={0.1} // Add step prop to allow decimal inputs
                precision={1} // Specify decimal precision
                removeTrailingZeros // Optional: remove trailing zeros for cleaner display
              />

              <TextInput
                id="tvg_id"
                name="tvg_id"
                label="TVG-ID"
                value={formik.values.tvg_id}
                onChange={formik.handleChange}
                error={formik.errors.tvg_id ? formik.touched.tvg_id : ''}
                size="xs"
              />

              <TextInput
                id="tvc_guide_stationid"
                name="tvc_guide_stationid"
                label="Gracenote StationId"
                value={formik.values.tvc_guide_stationid}
                onChange={formik.handleChange}
                error={
                  formik.errors.tvc_guide_stationid
                    ? formik.touched.tvc_guide_stationid
                    : ''
                }
                size="xs"
              />

              <Popover
                opened={epgPopoverOpened}
                onChange={setEpgPopoverOpened}
                // position="bottom-start"
                withArrow
              >
                <Popover.Target>
                  <TextInput
                    id="epg_data_id"
                    name="epg_data_id"
                    label={
                      <Group style={{ width: '100%' }}>
                        <Box>EPG</Box>
                        <Button
                          size="xs"
                          variant="transparent"
                          onClick={() =>
                            formik.setFieldValue('epg_data_id', null)
                          }
                        >
                          Use Dummy
                        </Button>
                        <Button
                          size="xs"
                          variant="transparent"
                          color="blue"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleAutoMatchEpg();
                          }}
                          disabled={!channel || !channel.id}
                          loading={autoMatchLoading}
                          title={
                            !channel || !channel.id
                              ? 'Auto-match is only available for existing channels'
                              : 'Automatically match EPG data'
                          }
                          leftSection={<Zap size="14" />}
                        >
                          Auto Match
                        </Button>
                      </Group>
                    }
                    readOnly
                    value={(() => {
                      const tvg = tvgsById[formik.values.epg_data_id];
                      const epgSource = tvg && epgs[tvg.epg_source];
                      const tvgLabel = tvg ? tvg.name || tvg.id : '';
                      if (epgSource && tvgLabel) {
                        return `${epgSource.name} - ${tvgLabel}`;
                      } else if (tvgLabel) {
                        return tvgLabel;
                      } else {
                        return 'Dummy';
                      }
                    })()}
                    onClick={() => setEpgPopoverOpened(true)}
                    size="xs"
                    rightSection={
                      <Tooltip label="Use dummy EPG">
                        <ActionIcon
                          // color={theme.tailwind.green[5]}
                          color="white"
                          onClick={(e) => {
                            e.stopPropagation();
                            formik.setFieldValue('epg_data_id', null);
                          }}
                          title="Create new group"
                          size="small"
                          variant="transparent"
                        >
                          <X size="20" />
                        </ActionIcon>
                      </Tooltip>
                    }
                  />
                </Popover.Target>

                <Popover.Dropdown onMouseDown={(e) => e.stopPropagation()}>
                  <Group>
                    <Select
                      label="Source"
                      value={selectedEPG}
                      onChange={setSelectedEPG}
                      data={Object.values(epgs).map((epg) => ({
                        value: `${epg.id}`,
                        label: epg.name,
                      }))}
                      size="xs"
                      mb="xs"
                    />

                    {/* Filter Input */}
                    <TextInput
                      label="Filter"
                      value={tvgFilter}
                      onChange={(event) =>
                        setTvgFilter(event.currentTarget.value)
                      }
                      mb="xs"
                      size="xs"
                      autoFocus
                    />
                  </Group>

                  <ScrollArea style={{ height: 200 }}>
                    <List
                      height={200} // Set max height for visible items
                      itemCount={filteredTvgs.length}
                      itemSize={40} // Adjust row height for each item
                      style={{ width: '100%' }}
                      ref={listRef}
                    >
                      {({ index, style }) => (
                        <div style={style}>
                          <Button
                            key={filteredTvgs[index].id}
                            variant="subtle"
                            color="gray"
                            style={{ width: '100%' }}
                            justify="left"
                            size="xs"
                            onClick={() => {
                              if (filteredTvgs[index].id == '0') {
                                formik.setFieldValue('epg_data_id', null);
                              } else {
                                formik.setFieldValue(
                                  'epg_data_id',
                                  filteredTvgs[index].id
                                );
                                // Also update selectedEPG to match the EPG source of the selected tvg
                                if (filteredTvgs[index].epg_source) {
                                  setSelectedEPG(
                                    `${filteredTvgs[index].epg_source}`
                                  );
                                }
                              }
                              setEpgPopoverOpened(false);
                            }}
                          >
                            {filteredTvgs[index].name &&
                            filteredTvgs[index].tvg_id
                              ? `${filteredTvgs[index].name} (${filteredTvgs[index].tvg_id})`
                              : filteredTvgs[index].name ||
                                filteredTvgs[index].tvg_id}
                          </Button>
                        </div>
                      )}
                    </List>
                  </ScrollArea>
                </Popover.Dropdown>
              </Popover>
            </Stack>
          </Group>

          <Flex mih={50} gap="xs" justify="flex-end" align="flex-end">
            <Button
              type="submit"
              variant="default"
              disabled={formik.isSubmitting}
            >
              Submit
            </Button>
          </Flex>
        </form>
      </Modal>

      <ChannelGroupForm
        isOpen={channelGroupModelOpen}
        onClose={handleChannelGroupModalClose}
      />
    </>
  );
};

export default ChannelForm;
