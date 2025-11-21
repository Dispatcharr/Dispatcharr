import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useFormik } from 'formik';
import * as Yup from 'yup';
import useChannelsStore from '../../store/channels';
import API from '../../api';
import useStreamProfilesStore from '../../store/streamProfiles';
import useStreamsStore from '../../store/streams';
import { useChannelLogoSelection } from '../../hooks/useSmartLogos';
import LazyLogo from '../LazyLogo';
import ChannelGroupForm from './ChannelGroup';
import usePlaylistsStore from '../../store/playlists';
import logo from '../../images/logo.png';
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
import { ListOrdered, SquarePlus, SquareX, X } from 'lucide-react';
import useEPGsStore from '../../store/epgs';
import { Dropzone } from '@mantine/dropzone';
import { notifications } from '@mantine/notifications';
import { FixedSizeList as List } from 'react-window';

const ChannelsForm = ({ channel = null, isOpen, onClose }) => {
  const theme = useMantineTheme();

  const listRef = useRef(null);
  const logoListRef = useRef(null);
  const groupListRef = useRef(null);

  const channelGroups = useChannelsStore((s) => s.channelGroups);
  const { logos, ensureLogosLoaded } = useChannelLogoSelection();
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
      });

      setChannelStreams(channel.streams || []);
    } else {
      formik.resetForm();
      setTvgFilter('');
      setLogoFilter('');
    }
  }, [channel, tvgsById, channelGroups]);

  // Memoize logo options to prevent infinite re-renders during background loading
  const logoOptions = useMemo(() => {
    return [{ id: '0', name: 'Default' }].concat(Object.values(logos));
  }, [logos]); // Only depend on logos object

  const renderLogoOption = ({ option, checked }) => {
    return (
      <Center style={{ width: '100%' }}>
        <img src={logos[option.value].cache_url} width="30" />
      </Center>
    );
  };

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
              label="Channel Name"
              value={formik.values.name}
              onChange={formik.handleChange}
              error={formik.errors.name ? formik.touched.name : ''}
              size="xs"
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
          </Stack>

          <Divider size="sm" orientation="vertical" />

          <Stack justify="flex-start" style={{ flex: 1 }}>
            <Group justify="space-between">
              <Popover
                opened={logoPopoverOpened}
                onChange={(opened) => {
                  setLogoPopoverOpened(opened);
                  if (opened) {
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
                    label="Logo"
                    readOnly
                    value={logos[formik.values.logo_id]?.name || 'Default'}
                    onClick={() => setLogoPopoverOpened(true)}
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
                  </Group>

                  <ScrollArea style={{ height: 200 }}>
                    <List
                      height={200} // Set max height for visible items
                      itemCount={filteredLogos.length}
                      itemSize={20} // Adjust row height for each item
                      width="100%"
                      ref={logoListRef}
                    >
                      {({ index, style }) => (
                        <div style={style}>
                          <Center>
                            <img
                              src={filteredLogos[index].cache_url || logo}
                              height="20"
                              style={{ maxWidth: 80 }}
                              onClick={() => {
                                formik.setFieldValue(
                                  'logo_id',
                                  filteredLogos[index].id
                                );
                              }}
                            />
                          </Center>
                        </div>
                      )}
                    </List>
                  </ScrollArea>
                </Popover.Dropdown>
              </Popover>

              <LazyLogo
                logoId={formik.values.logo_id}
                alt="channel logo"
                style={{ height: 40 }}
              />
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
                    </Group>
                  }
                  readOnly
                  value={
                    formik.values.epg_data_id
                      ? tvgsById[formik.values.epg_data_id].name
                      : 'Dummy'
                  }
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
                  />
                </Group>

                <ScrollArea style={{ height: 200 }}>
                  <List
                    height={200} // Set max height for visible items
                    itemCount={filteredTvgs.length}
                    itemSize={40} // Adjust row height for each item
                    width="100%"
                    ref={listRef}
                  >
                    {({ index, style }) => (
                      <div style={style}>
                        <Button
                          key={filteredTvgs[index].id}
                          variant="subtle"
                          color="gray"
                          fullWidth
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
                            }
                            setEpgPopoverOpened(false);
                          }}
                        >
                          {filteredTvgs[index].tvg_id}
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
  );
};

export default ChannelsForm;
