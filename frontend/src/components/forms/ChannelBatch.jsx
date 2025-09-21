import React, { useState, useEffect, useMemo, useRef } from 'react';
import useChannelsStore from '../../store/channels';
import API from '../../api';
import useStreamProfilesStore from '../../store/streamProfiles';
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

const ChannelBatchForm = ({ channelIds, isOpen, onClose }) => {
  const theme = useMantineTheme();

  const groupListRef = useRef(null);

  const channelGroups = useChannelsStore((s) => s.channelGroups);

  const streamProfiles = useStreamProfilesStore((s) => s.profiles);

  const [channelGroupModelOpen, setChannelGroupModalOpen] = useState(false);
  const [selectedChannelGroup, setSelectedChannelGroup] = useState('-1');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [regexFind, setRegexFind] = useState('');
  const [regexReplace, setRegexReplace] = useState('');

  const [groupPopoverOpened, setGroupPopoverOpened] = useState(false);
  const [groupFilter, setGroupFilter] = useState('');
  const groupOptions = Object.values(channelGroups);

  const form = useForm({
    mode: 'uncontrolled',
    initialValues: {
      channel_group: '(no change)',
      stream_profile_id: '-1',
      user_level: '-1',
    },
  });

  const onSubmit = async () => {
    setIsSubmitting(true);

    const values = {
      ...form.getValues(),
    }; // Handle channel group ID - convert to integer if it exists
    if (selectedChannelGroup && selectedChannelGroup !== '-1') {
      values.channel_group_id = parseInt(selectedChannelGroup);
    } else {
      delete values.channel_group_id;
    }

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
      } else {
        await API.updateChannels(channelIds, values);
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
      onClose();
    } catch (error) {
      console.error('Failed to start EPG name setting task:', error);
      notifications.show({
        title: 'Error',
        message: 'Failed to start EPG name setting task.',
        color: 'red',
      });
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
      onClose();
    } catch (error) {
      console.error('Failed to start EPG logo setting task:', error);
      notifications.show({
        title: 'Error',
        message: 'Failed to start EPG logo setting task.',
        color: 'red',
      });
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
        <form onSubmit={form.onSubmit(onSubmit)}>
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
                </Group>
                <Text size="xs" c="dimmed" mt="xs">
                  Updates channel names and logos based on their assigned EPG
                  data
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
            <Button type="submit" variant="default" disabled={isSubmitting}>
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
