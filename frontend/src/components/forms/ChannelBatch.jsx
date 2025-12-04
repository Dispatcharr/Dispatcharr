import React, { useState, useEffect, useMemo, useRef } from 'react';
import useChannelsStore from '../../store/channels';
import API from '../../api';
import useStreamProfilesStore from '../../store/streamProfiles';
import useEPGsStore from '../../store/epgs';
import ChannelGroupForm from './ChannelGroup';
import {
  Box,
  Button,
  Modal,
  TextInput,
  Text,
  Group,
  ActionIcon,
  Flex,
  Select,
  Stack,
  useMantineTheme,
  Popover,
  ScrollArea,
  Tooltip,
  UnstyledButton,
  Center,
  Divider,
  Checkbox,
  Paper,
} from '@mantine/core';
import { ListOrdered, SquarePlus, SquareX, X } from 'lucide-react';
import { FixedSizeList as List } from 'react-window';
import { useForm } from '@mantine/form';
import { notifications } from '@mantine/notifications';
import { USER_LEVELS, USER_LEVEL_LABELS } from '../../constants';
import { useChannelLogoSelection } from '../../hooks/useSmartLogos';
import LazyLogo from '../LazyLogo';
import logo from '../../images/logo.png';
import ConfirmationDialog from '../ConfirmationDialog';
import useWarningsStore from '../../store/warnings';

const ChannelBatchForm = ({ channelIds, isOpen, onClose }) => {
  const theme = useMantineTheme();

  const groupListRef = useRef(null);
  const logoListRef = useRef(null);

  const channelGroups = useChannelsStore((s) => s.channelGroups);
  const {
    logos: channelLogos,
    ensureLogosLoaded,
    isLoading: logosLoading,
  } = useChannelLogoSelection();

  useEffect(() => {
    ensureLogosLoaded();
  }, [ensureLogosLoaded]);

  const streamProfiles = useStreamProfilesStore((s) => s.profiles);
  const epgs = useEPGsStore((s) => s.epgs);
  const tvgs = useEPGsStore((s) => s.tvgs);
  const fetchEPGs = useEPGsStore((s) => s.fetchEPGs);

  const [channelGroupModelOpen, setChannelGroupModalOpen] = useState(false);
  const [selectedChannelGroup, setSelectedChannelGroup] = useState('-1');
  const [selectedLogoId, setSelectedLogoId] = useState('-1');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [regexFind, setRegexFind] = useState('');
  const [regexReplace, setRegexReplace] = useState('');
  const [selectedDummyEpgId, setSelectedDummyEpgId] = useState(null);

  const [groupPopoverOpened, setGroupPopoverOpened] = useState(false);
  const [groupFilter, setGroupFilter] = useState('');
  const groupOptions = Object.values(channelGroups);

  const [logoPopoverOpened, setLogoPopoverOpened] = useState(false);
  const [logoFilter, setLogoFilter] = useState('');
  // Confirmation dialog states
  const [confirmSetNamesOpen, setConfirmSetNamesOpen] = useState(false);
  const [confirmSetLogosOpen, setConfirmSetLogosOpen] = useState(false);
  const [confirmSetTvgIdsOpen, setConfirmSetTvgIdsOpen] = useState(false);
  const [confirmBatchUpdateOpen, setConfirmBatchUpdateOpen] = useState(false);
  const isWarningSuppressed = useWarningsStore((s) => s.isWarningSuppressed);
  const suppressWarning = useWarningsStore((s) => s.suppressWarning);

  // Fetch EPG sources when modal opens
  useEffect(() => {
    if (isOpen) {
      fetchEPGs();
    }
  }, [isOpen, fetchEPGs]);

  // Get dummy EPG sources
  const dummyEpgSources = useMemo(() => {
    return Object.values(epgs).filter((epg) => epg.source_type === 'dummy');
  }, [epgs]);

  const form = useForm({
    mode: 'uncontrolled',
    initialValues: {
      channel_group: '(no change)',
      logo: '(no change)',
      stream_profile_id: '-1',
      user_level: '-1',
    },
  });

  // Build confirmation message based on selected changes
  const getConfirmationMessage = () => {
    const changes = [];
    const values = form.getValues();

    // Check for regex name changes
    if (regexFind.trim().length > 0) {
      changes.push(
        `• Name Change: Apply regex find "${regexFind}" replace with "${regexReplace || ''}"`
      );
    }

    // Check channel group
    if (selectedChannelGroup && selectedChannelGroup !== '-1') {
      const groupName = channelGroups[selectedChannelGroup]?.name || 'Unknown';
      changes.push(`• Channel Group: ${groupName}`);
    }

    // Check logo
    if (selectedLogoId && selectedLogoId !== '-1') {
      if (selectedLogoId === '0') {
        changes.push(`• Logo: Use Default`);
      } else {
        const logoName = channelLogos[selectedLogoId]?.name || 'Selected Logo';
        changes.push(`• Logo: ${logoName}`);
      }
    }

    // Check stream profile
    if (values.stream_profile_id && values.stream_profile_id !== '-1') {
      if (values.stream_profile_id === '0') {
        changes.push(`• Stream Profile: Use Default`);
      } else {
        const profileName =
          streamProfiles[values.stream_profile_id]?.name || 'Selected Profile';
        changes.push(`• Stream Profile: ${profileName}`);
      }
    }

    // Check user level
    if (values.user_level && values.user_level !== '-1') {
      const userLevelLabel =
        USER_LEVEL_LABELS[values.user_level] || values.user_level;
      changes.push(`• User Level: ${userLevelLabel}`);
    }

    // Check dummy EPG
    if (selectedDummyEpgId) {
      if (selectedDummyEpgId === 'clear') {
        changes.push(`• EPG: Clear Assignment (use default dummy)`);
      } else {
        const epgName = epgs[selectedDummyEpgId]?.name || 'Selected EPG';
        changes.push(`• Dummy EPG: ${epgName}`);
      }
    }

    return changes;
  };

  const handleSubmit = () => {
    const changes = getConfirmationMessage();

    // If no changes detected, show notification
    if (changes.length === 0) {
      notifications.show({
        title: 'No Changes',
        message: 'Please select at least one field to update.',
        color: 'orange',
      });
      return;
    }

    // Skip warning if suppressed
    if (isWarningSuppressed('batch-update-channels')) {
      return onSubmit();
    }

    setConfirmBatchUpdateOpen(true);
  };

  const onSubmit = async () => {
    setConfirmBatchUpdateOpen(false);
    setIsSubmitting(true);

    const values = {
      ...form.getValues(),
    }; // Handle channel group ID - convert to integer if it exists
    if (selectedChannelGroup && selectedChannelGroup !== '-1') {
      values.channel_group_id = parseInt(selectedChannelGroup);
    } else {
      delete values.channel_group_id;
    }

    if (selectedLogoId && selectedLogoId !== '-1') {
      if (selectedLogoId === '0') {
        values.logo_id = null;
      } else {
        values.logo_id = parseInt(selectedLogoId);
      }
    }
    delete values.logo;

    // Handle stream profile ID - convert special values
    if (!values.stream_profile_id || values.stream_profile_id === '-1') {
      delete values.stream_profile_id;
    } else if (
      values.stream_profile_id === '0' ||
      values.stream_profile_id === 0
    ) {
      values.stream_profile_id = null; // Convert "use default" to null
    }

    if (values.user_level == '-1') {
      delete values.user_level;
    }

    // Remove the channel_group field from form values as we use channel_group_id
    delete values.channel_group;

    try {
      const applyRegex = regexFind.trim().length > 0;

      // First, handle standard field updates (name, group, logo, etc.)
      if (applyRegex) {
        // Build per-channel updates to apply unique names via regex
        let flags = 'g';
        let re;
        try {
          re = new RegExp(regexFind, flags);
        } catch (e) {
          console.error('Invalid regex:', e);
          setIsSubmitting(false);
          return;
        }

        const channelsMap = useChannelsStore.getState().channels;
        const updates = channelIds.map((id) => {
          const ch = channelsMap[id];
          const currentName = ch?.name ?? '';
          const newName = currentName.replace(re, regexReplace ?? '');
          const update = { id };
          if (newName !== currentName && newName.trim().length > 0) {
            update.name = newName;
          }
          // Merge base values (group/profile/user_level) if present
          Object.assign(update, values);
          return update;
        });

        await API.bulkUpdateChannels(updates);
      } else if (Object.keys(values).length > 0) {
        await API.updateChannels(channelIds, values);
      }

      // Then, handle EPG assignment if a dummy EPG was selected
      if (selectedDummyEpgId) {
        if (selectedDummyEpgId === 'clear') {
          // Clear EPG assignments
          const associations = channelIds.map((id) => ({
            channel_id: id,
            epg_data_id: null,
          }));
          await API.batchSetEPG(associations);
        } else {
          // Assign the selected dummy EPG
          const selectedEpg = epgs[selectedDummyEpgId];
          if (selectedEpg && selectedEpg.epg_data_count > 0) {
            // Convert to number for comparison since Select returns string
            const epgSourceId = parseInt(selectedDummyEpgId, 10);

            // Check if we already have EPG data loaded in the store
            let epgData = tvgs.find((data) => data.epg_source === epgSourceId);

            // If not in store, fetch it
            if (!epgData) {
              const epgDataList = await API.getEPGData();
              epgData = epgDataList.find(
                (data) => data.epg_source === epgSourceId
              );
            }

            if (epgData) {
              const associations = channelIds.map((id) => ({
                channel_id: id,
                epg_data_id: epgData.id,
              }));
              await API.batchSetEPG(associations);
            }
          }
        }
      }

      // Refresh both the channels table data and the main channels store
      await Promise.all([
        API.requeryChannels(),
        useChannelsStore.getState().fetchChannels(),
      ]);
      onClose();
    } catch (error) {
      console.error('Failed to update channels:', error);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSetNamesFromEpg = async () => {
    if (!channelIds || channelIds.length === 0) {
      notifications.show({
        title: 'No Channels Selected',
        message: 'No channels to update.',
        color: 'orange',
      });
      return;
    }

    // Skip warning if suppressed
    if (isWarningSuppressed('batch-set-names-from-epg')) {
      return executeSetNamesFromEpg();
    }

    setConfirmSetNamesOpen(true);
  };

  const executeSetNamesFromEpg = async () => {
    try {
      // Start the backend task
      await API.setChannelNamesFromEpg(channelIds);

      // The task will send WebSocket updates for progress
      // Just show that it started successfully
      notifications.show({
        title: 'Task Started',
        message: `Started setting names from EPG for ${channelIds.length} channels. Progress will be shown in notifications.`,
        color: 'blue',
      });

      // Close the modal since the task is now running in background
      setConfirmSetNamesOpen(false);
      onClose();
    } catch (error) {
      console.error('Failed to start EPG name setting task:', error);
      notifications.show({
        title: 'Error',
        message: 'Failed to start EPG name setting task.',
        color: 'red',
      });
      setConfirmSetNamesOpen(false);
    }
  };

  const handleSetLogosFromEpg = async () => {
    if (!channelIds || channelIds.length === 0) {
      notifications.show({
        title: 'No Channels Selected',
        message: 'No channels to update.',
        color: 'orange',
      });
      return;
    }

    // Skip warning if suppressed
    if (isWarningSuppressed('batch-set-logos-from-epg')) {
      return executeSetLogosFromEpg();
    }

    setConfirmSetLogosOpen(true);
  };

  const executeSetLogosFromEpg = async () => {
    try {
      // Start the backend task
      await API.setChannelLogosFromEpg(channelIds);

      // The task will send WebSocket updates for progress
      // Just show that it started successfully
      notifications.show({
        title: 'Task Started',
        message: `Started setting logos from EPG for ${channelIds.length} channels. Progress will be shown in notifications.`,
        color: 'blue',
      });

      // Close the modal since the task is now running in background
      setConfirmSetLogosOpen(false);
      onClose();
    } catch (error) {
      console.error('Failed to start EPG logo setting task:', error);
      notifications.show({
        title: 'Error',
        message: 'Failed to start EPG logo setting task.',
        color: 'red',
      });
      setConfirmSetLogosOpen(false);
    }
  };

  const handleSetTvgIdsFromEpg = async () => {
    if (!channelIds || channelIds.length === 0) {
      notifications.show({
        title: 'No Channels Selected',
        message: 'No channels to update.',
        color: 'orange',
      });
      return;
    }

    // Skip warning if suppressed
    if (isWarningSuppressed('batch-set-tvg-ids-from-epg')) {
      return executeSetTvgIdsFromEpg();
    }

    setConfirmSetTvgIdsOpen(true);
  };

  const executeSetTvgIdsFromEpg = async () => {
    try {
      // Start the backend task
      await API.setChannelTvgIdsFromEpg(channelIds);

      // The task will send WebSocket updates for progress
      // Just show that it started successfully
      notifications.show({
        title: 'Task Started',
        message: `Started setting TVG-IDs from EPG for ${channelIds.length} channels. Progress will be shown in notifications.`,
        color: 'blue',
      });

      // Close the modal since the task is now running in background
      setConfirmSetTvgIdsOpen(false);
      onClose();
    } catch (error) {
      console.error('Failed to start EPG TVG-ID setting task:', error);
      notifications.show({
        title: 'Error',
        message: 'Failed to start EPG TVG-ID setting task.',
        color: 'red',
      });
      setConfirmSetTvgIdsOpen(false);
    }
  };

  // useEffect(() => {
  //   // const sameStreamProfile = channels.every(
  //   //   (channel) => channel.stream_profile_id == channels[0].stream_profile_id
  //   // );
  //   // const sameChannelGroup = channels.every(
  //   //   (channel) => channel.channel_group_id == channels[0].channel_group_id
  //   // );
  //   // const sameUserLevel = channels.every(
  //   //   (channel) => channel.user_level == channels[0].user_level
  //   // );
  //   // form.setValues({
  //   //   ...(sameStreamProfile && {
  //   //     stream_profile_id: `${channels[0].stream_profile_id}`,
  //   //   }),
  //   //   ...(sameChannelGroup && {
  //   //     channel_group_id: `${channels[0].channel_group_id}`,
  //   //   }),
  //   //   ...(sameUserLevel && {
  //   //     user_level: `${channels[0].user_level}`,
  //   //   }),
  //   // });
  // }, [channelIds, streamProfiles, channelGroups]);

  const handleChannelGroupModalClose = (newGroup) => {
    setChannelGroupModalOpen(false);

    if (newGroup && newGroup.id) {
      setSelectedChannelGroup(newGroup.id);
      form.setValues({
        channel_group: `${newGroup.name}`,
      });
    }
  };
  const filteredGroups = [
    { id: '-1', name: '(no change)' },
    ...groupOptions.filter((group) =>
      group.name.toLowerCase().includes(groupFilter.toLowerCase())
    ),
  ];

  const logoOptions = useMemo(() => {
    return [
      { id: '-1', name: '(no change)' },
      { id: '0', name: 'Use Default', isDefault: true },
      ...Object.values(channelLogos),
    ];
  }, [channelLogos]);

  const filteredLogos = logoOptions.filter((logo) =>
    logo.name.toLowerCase().includes(logoFilter.toLowerCase())
  );

  if (!isOpen) {
    return <></>;
  }

  return (
    <>
      <Modal
        opened={isOpen}
        onClose={onClose}
        size={'lg'}
        title={
          <Group gap="5">
            <ListOrdered size="20" />
            <Text>Channels</Text>
          </Group>
        }
        styles={{ hannontent: { '--mantine-color-body': '#27272A' } }}
      >
        <form onSubmit={form.onSubmit(handleSubmit)}>
          <Group justify="space-between" align="top">
            <Stack gap="5" style={{ flex: 1 }}>
              <Paper withBorder p="xs" radius="md">
                <Group justify="space-between" align="center" mb={6}>
                  <Text size="sm" fw={600}>
                    Channel Name
                  </Text>
                </Group>
                <Group align="end" gap="xs" wrap="nowrap">
                  <TextInput
                    size="xs"
                    label="Find (Regex)"
                    placeholder="e.g. ^(.*) HD$"
                    value={regexFind}
                    onChange={(e) => setRegexFind(e.currentTarget.value)}
                    style={{ flex: 1 }}
                  />
                  <TextInput
                    size="xs"
                    label="Replace"
                    placeholder="e.g. $1"
                    value={regexReplace}
                    onChange={(e) => setRegexReplace(e.currentTarget.value)}
                    style={{ flex: 1 }}
                  />
                </Group>
                <RegexPreview
                  channelIds={channelIds}
                  find={regexFind}
                  replace={regexReplace}
                />
              </Paper>

              <Paper withBorder p="xs" radius="md">
                <Group justify="space-between" align="center" mb={6}>
                  <Text size="sm" fw={600}>
                    EPG Operations
                  </Text>
                </Group>
                <Group gap="xs" wrap="nowrap">
                  <Button
                    size="xs"
                    variant="light"
                    onClick={handleSetNamesFromEpg}
                    style={{ flex: 1 }}
                  >
                    Set Names from EPG
                  </Button>
                  <Button
                    size="xs"
                    variant="light"
                    onClick={handleSetLogosFromEpg}
                    style={{ flex: 1 }}
                  >
                    Set Logos from EPG
                  </Button>
                  <Button
                    size="xs"
                    variant="light"
                    onClick={handleSetTvgIdsFromEpg}
                    style={{ flex: 1 }}
                  >
                    Set TVG-IDs from EPG
                  </Button>
                </Group>
                <Divider my="xs" />
                <Stack gap="xs">
                  <Text size="xs" fw={600}>
                    Assign Dummy EPG
                  </Text>
                  <Select
                    size="xs"
                    placeholder="Select a dummy EPG..."
                    data={[
                      { value: 'clear', label: '(Clear EPG Assignment)' },
                      ...dummyEpgSources.map((epg) => ({
                        value: String(epg.id),
                        label: epg.name,
                      })),
                    ]}
                    value={selectedDummyEpgId}
                    onChange={setSelectedDummyEpgId}
                    clearable
                  />
                </Stack>
                <Text size="xs" c="dimmed" mt="xs">
                  Updates channel names, logos, and TVG-IDs based on their
                  assigned EPG data, or assign a custom dummy EPG to selected
                  channels
                </Text>
              </Paper>

              <Popover
                opened={groupPopoverOpened}
                onChange={setGroupPopoverOpened}
                // position="bottom-start"
                withArrow
              >
                <Popover.Target>
                  <Group style={{ width: '100%' }} align="flex-end">
                    <TextInput
                      id="channel_group"
                      name="channel_group"
                      label="Channel Group"
                      readOnly
                      {...form.getInputProps('channel_group')}
                      key={form.key('channel_group')}
                      onClick={() => setGroupPopoverOpened(true)}
                      size="xs"
                      style={{ flex: 1 }}
                      rightSection={
                        form.getValues().channel_group &&
                        form.getValues().channel_group !== '(no change)' && (
                          <ActionIcon
                            size="xs"
                            variant="subtle"
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedChannelGroup('-1');
                              form.setValues({ channel_group: '(no change)' });
                            }}
                          >
                            <X size={12} />
                          </ActionIcon>
                        )
                      }
                    />

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
                  </Group>
                </Popover.Target>

                <Popover.Dropdown onMouseDown={(e) => e.stopPropagation()}>
                  <Group style={{ width: '100%' }} spacing="xs">
                    <TextInput
                      placeholder="Filter"
                      value={groupFilter}
                      onChange={(event) =>
                        setGroupFilter(event.currentTarget.value)
                      }
                      mb="xs"
                      size="xs"
                      style={{ flex: 1 }}
                    />

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
                                setSelectedChannelGroup(
                                  filteredGroups[index].id
                                );
                                form.setValues({
                                  channel_group: filteredGroups[index].name,
                                });
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

              <Group style={{ width: '100%' }} align="flex-end" gap="xs">
                <Popover
                  opened={logoPopoverOpened}
                  onChange={setLogoPopoverOpened}
                  withArrow
                >
                  <Popover.Target>
                    <TextInput
                      label="Logo"
                      readOnly
                      {...form.getInputProps('logo')}
                      key={form.key('logo')}
                      onClick={() => setLogoPopoverOpened(true)}
                      size="xs"
                      style={{ flex: 1 }}
                      rightSection={
                        selectedLogoId !== '-1' && (
                          <ActionIcon
                            size="xs"
                            variant="subtle"
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedLogoId('-1');
                              form.setValues({ logo: '(no change)' });
                            }}
                          >
                            <X size={12} />
                          </ActionIcon>
                        )
                      }
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
                          height={200}
                          itemCount={filteredLogos.length}
                          itemSize={55}
                          style={{ width: '100%' }}
                          ref={logoListRef}
                        >
                          {({ index, style }) => {
                            const item = filteredLogos[index];
                            return (
                              <div
                                style={{
                                  ...style,
                                  cursor: 'pointer',
                                  padding: '5px',
                                  borderRadius: '4px',
                                }}
                                onClick={() => {
                                  setSelectedLogoId(item.id);
                                  form.setValues({
                                    logo: item.name,
                                  });
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
                                  style={{
                                    flexDirection: 'column',
                                    gap: '2px',
                                  }}
                                >
                                  {item.isDefault ? (
                                    <img
                                      src={logo}
                                      height="30"
                                      style={{
                                        maxWidth: 80,
                                        objectFit: 'contain',
                                      }}
                                      alt="Default Logo"
                                    />
                                  ) : item.id > 0 ? (
                                    <img
                                      src={item.cache_url || logo}
                                      height="30"
                                      style={{
                                        maxWidth: 80,
                                        objectFit: 'contain',
                                      }}
                                      alt={item.name || 'Logo'}
                                      onError={(e) => {
                                        if (e.target.src !== logo) {
                                          e.target.src = logo;
                                        }
                                      }}
                                    />
                                  ) : (
                                    <Box h={30} />
                                  )}
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
                                    {item.name}
                                  </Text>
                                </Center>
                              </div>
                            );
                          }}
                        </List>
                      )}
                    </ScrollArea>
                  </Popover.Dropdown>
                </Popover>
                {selectedLogoId > 0 && (
                  <LazyLogo
                    logoId={selectedLogoId}
                    alt="channel logo"
                    style={{ height: 24, marginBottom: 5 }}
                  />
                )}
              </Group>

              <Select
                id="stream_profile_id"
                label="Stream Profile"
                name="stream_profile_id"
                {...form.getInputProps('stream_profile_id')}
                key={form.key('stream_profile_id')}
                data={[
                  { value: '-1', label: '(no change)' },
                  { value: '0', label: '(use default)' },
                ].concat(
                  streamProfiles.map((option) => ({
                    value: `${option.id}`,
                    label: option.name,
                  }))
                )}
                size="xs"
              />

              <Select
                size="xs"
                label="User Level Access"
                {...form.getInputProps('user_level')}
                key={form.key('user_level')}
                data={[
                  {
                    value: '-1',
                    label: '(no change)',
                  },
                ].concat(
                  Object.entries(USER_LEVELS).map(([, value]) => {
                    return {
                      label: USER_LEVEL_LABELS[value],
                      value: `${value}`,
                    };
                  })
                )}
              />
            </Stack>
          </Group>
          <Flex mih={50} gap="xs" justify="flex-end" align="flex-end">
            <Button
              type="submit"
              variant="default"
              disabled={isSubmitting}
              loading={isSubmitting}
              loaderProps={{ type: 'dots' }}
            >
              {isSubmitting ? 'Saving...' : 'Submit'}
            </Button>
          </Flex>
        </form>
      </Modal>

      <ChannelGroupForm
        isOpen={channelGroupModelOpen}
        onClose={handleChannelGroupModalClose}
      />

      <ConfirmationDialog
        opened={confirmSetNamesOpen}
        onClose={() => setConfirmSetNamesOpen(false)}
        onConfirm={executeSetNamesFromEpg}
        title="Confirm Set Names from EPG"
        message={
          <div style={{ whiteSpace: 'pre-line' }}>
            {`Are you sure you want to set names from EPG for ${channelIds?.length || 0} selected channels?

This will replace the current channel names with the names from their assigned EPG data.

This action cannot be undone.`}
          </div>
        }
        confirmLabel="Set Names"
        cancelLabel="Cancel"
        actionKey="batch-set-names-from-epg"
        onSuppressChange={suppressWarning}
        size="md"
      />

      <ConfirmationDialog
        opened={confirmSetLogosOpen}
        onClose={() => setConfirmSetLogosOpen(false)}
        onConfirm={executeSetLogosFromEpg}
        title="Confirm Set Logos from EPG"
        message={
          <div style={{ whiteSpace: 'pre-line' }}>
            {`Are you sure you want to set logos from EPG for ${channelIds?.length || 0} selected channels?

This will replace the current channel logos with logos from their assigned EPG data. New logos will be created if needed.

This action cannot be undone.`}
          </div>
        }
        confirmLabel="Set Logos"
        cancelLabel="Cancel"
        actionKey="batch-set-logos-from-epg"
        onSuppressChange={suppressWarning}
        size="md"
      />

      <ConfirmationDialog
        opened={confirmSetTvgIdsOpen}
        onClose={() => setConfirmSetTvgIdsOpen(false)}
        onConfirm={executeSetTvgIdsFromEpg}
        title="Confirm Set TVG-IDs from EPG"
        message={
          <div style={{ whiteSpace: 'pre-line' }}>
            {`Are you sure you want to set TVG-IDs from EPG for ${channelIds?.length || 0} selected channels?

This will replace the current TVG-IDs with the TVG-IDs from their assigned EPG data.

This action cannot be undone.`}
          </div>
        }
        confirmLabel="Set TVG-IDs"
        cancelLabel="Cancel"
        actionKey="batch-set-tvg-ids-from-epg"
        onSuppressChange={suppressWarning}
        size="md"
      />

      <ConfirmationDialog
        opened={confirmBatchUpdateOpen}
        onClose={() => setConfirmBatchUpdateOpen(false)}
        onConfirm={onSubmit}
        title="Confirm Batch Update"
        message={
          <div>
            <Text mb="md">
              You are about to apply the following changes to{' '}
              <strong>{channelIds?.length || 0}</strong> selected channel
              {(channelIds?.length || 0) !== 1 ? 's' : ''}:
            </Text>
            <Paper
              withBorder
              p="sm"
              style={{ backgroundColor: 'rgba(0, 0, 0, 0.2)' }}
            >
              <Stack gap="xs">
                {getConfirmationMessage().map((change, index) => (
                  <Text
                    key={index}
                    size="sm"
                    style={{ fontFamily: 'monospace' }}
                  >
                    {change}
                  </Text>
                ))}
              </Stack>
            </Paper>
            <Text mt="md" size="sm" c="dimmed">
              This action cannot be undone.
            </Text>
          </div>
        }
        confirmLabel="Apply Changes"
        cancelLabel="Cancel"
        actionKey="batch-update-channels"
        onSuppressChange={suppressWarning}
        size="md"
      />
    </>
  );
};

export default ChannelBatchForm;

// Lightweight inline preview component to visualize rename results for a subset
const RegexPreview = ({ channelIds, find, replace }) => {
  const channelsMap = useChannelsStore((s) => s.channels);
  const previewItems = useMemo(() => {
    const items = [];
    if (!find) return items;
    let flags = 'g';
    let re;
    try {
      re = new RegExp(find, flags);
    } catch (error) {
      console.error('Invalid regex:', error);
      return [{ before: 'Invalid regex', after: '' }];
    }
    for (let i = 0; i < Math.min(channelIds.length, 25); i++) {
      const id = channelIds[i];
      const before = channelsMap[id]?.name ?? '';
      const after = before.replace(re, replace ?? '');
      if (before !== after) {
        items.push({ before, after });
      }
    }
    return items;
  }, [channelIds, channelsMap, find, replace]);

  if (!find) return null;

  return (
    <Box mt={8}>
      <Text size="xs" c="dimmed" mb={4}>
        Preview (first {Math.min(channelIds.length, 25)} of {channelIds.length}{' '}
        selected)
      </Text>
      <ScrollArea h={120} offsetScrollbars>
        <Stack gap={4}>
          {previewItems.length === 0 ? (
            <Text size="xs" c="dimmed">
              No changes with current pattern.
            </Text>
          ) : (
            previewItems.map((row, idx) => (
              <Group key={idx} gap={8} wrap="nowrap" align="center">
                <Text
                  size="xs"
                  style={{
                    flex: 1,
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {row.before}
                </Text>
                <Text size="xs" c="gray.6">
                  →
                </Text>
                <Text
                  size="xs"
                  style={{
                    flex: 1,
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {row.after}
                </Text>
              </Group>
            ))
          )}
        </Stack>
      </ScrollArea>
    </Box>
  );
};
