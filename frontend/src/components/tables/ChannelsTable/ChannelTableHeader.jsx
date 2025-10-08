import React, { useState } from 'react';
import {
  ActionIcon,
  Box,
  Button,
  Flex,
  Group,
  Menu,
  NumberInput,
  Popover,
  Select,
  Text,
  TextInput,
  Tooltip,
  UnstyledButton,
  useMantineTheme,
} from '@mantine/core';
import {
  ArrowDown01,
  Binary,
  Check,
  CircleCheck,
  Ellipsis,
  EllipsisVertical,
  SquareMinus,
  SquarePen,
  SquarePlus,
  Settings,
} from 'lucide-react';
import API from '../../../api';
import { notifications } from '@mantine/notifications';
import useChannelsStore from '../../../store/channels';
import useAuthStore from '../../../store/auth';
import { USER_LEVELS } from '../../../constants';
import AssignChannelNumbersForm from '../../forms/AssignChannelNumbers';
import GroupManager from '../../forms/GroupManager';
import ConfirmationDialog from '../../ConfirmationDialog';
import useWarningsStore from '../../../store/warnings';

const CreateProfilePopover = React.memo(() => {
  const [opened, setOpened] = useState(false);
  const [name, setName] = useState('');
  const theme = useMantineTheme();

  const authUser = useAuthStore((s) => s.user);

  const setOpen = () => {
    setName('');
    setOpened(!opened);
  };

  const submit = async () => {
    await API.addChannelProfile({ name });
    setName('');
    setOpened(false);
  };

  return (
    <Popover
      opened={opened}
      onChange={setOpen}
      position="bottom"
      withArrow
      shadow="md"
    >
      <Popover.Target>
        <ActionIcon
          variant="transparent"
          color={theme.tailwind.green[5]}
          onClick={setOpen}
          disabled={authUser.user_level != USER_LEVELS.ADMIN}
        >
          <SquarePlus />
        </ActionIcon>
      </Popover.Target>

      <Popover.Dropdown>
        <Group>
          <TextInput
            placeholder="Profile Name"
            value={name}
            onChange={(event) => setName(event.currentTarget.value)}
            size="xs"
          />

          <ActionIcon
            variant="transparent"
            color={theme.tailwind.green[5]}
            size="sm"
            onClick={submit}
          >
            <CircleCheck />
          </ActionIcon>
        </Group>
      </Popover.Dropdown>
    </Popover>
  );
});

const ChannelTableHeader = ({
  rows,
  editChannel,
  deleteChannels,
  selectedTableIds,
}) => {
  const theme = useMantineTheme();

  const [channelNumAssignmentStart, setChannelNumAssignmentStart] = useState(1);
  const [assignNumbersModalOpen, setAssignNumbersModalOpen] = useState(false);
  const [groupManagerOpen, setGroupManagerOpen] = useState(false);
  const [confirmDeleteProfileOpen, setConfirmDeleteProfileOpen] =
    useState(false);
  const [profileToDelete, setProfileToDelete] = useState(null);

  const profiles = useChannelsStore((s) => s.profiles);
  const selectedProfileId = useChannelsStore((s) => s.selectedProfileId);
  const setSelectedProfileId = useChannelsStore((s) => s.setSelectedProfileId);
  const authUser = useAuthStore((s) => s.user);
  const isWarningSuppressed = useWarningsStore((s) => s.isWarningSuppressed);
  const suppressWarning = useWarningsStore((s) => s.suppressWarning);
  const closeAssignChannelNumbersModal = () => {
    setAssignNumbersModalOpen(false);
  };

  const deleteProfile = async (id) => {
    // Get profile details for the confirmation dialog
    const profileObj = profiles[id];
    setProfileToDelete(profileObj);

    // Skip warning if it's been suppressed
    if (isWarningSuppressed('delete-profile')) {
      return executeDeleteProfile(id);
    }

    setConfirmDeleteProfileOpen(true);
  };

  const executeDeleteProfile = async (id) => {
    await API.deleteChannelProfile(id);
    setConfirmDeleteProfileOpen(false);
  };

  const matchEpg = async () => {
    try {
      // Hit our new endpoint that triggers the fuzzy matching Celery task
      // If channels are selected, only match those; otherwise match all
      if (selectedTableIds.length > 0) {
        await API.matchEpg(selectedTableIds);
        notifications.show({
          title: `EPG matching task started for ${selectedTableIds.length} selected channel(s)!`,
        });
      } else {
        await API.matchEpg();
        notifications.show({
          title: 'EPG matching task started for all channels without EPG!',
        });
      }
    } catch (err) {
      notifications.show(`Error: ${err.message}`);
    }
  };

  const assignChannels = async () => {
    try {
      // Call our custom API endpoint
      const result = await API.assignChannelNumbers(
        selectedTableIds,
        channelNumAssignmentStart
      );

      // We might get { message: "Channels have been auto-assigned!" }
      notifications.show({
        title: result.message || 'Channels assigned',
        color: 'green.5',
      });

      // Refresh the channel list
      // await fetchChannels();
      API.requeryChannels();
    } catch (err) {
      console.error(err);
      notifications.show({
        title: 'Failed to assign channels',
        color: 'red.5',
      });
    }
  };

  const renderProfileOption = ({ option, checked }) => {
    return (
      <Group justify="space-between" style={{ width: '100%' }}>
        <Box>{option.label}</Box>
        {option.value != '0' && (
          <ActionIcon
            size="xs"
            variant="transparent"
            color={theme.tailwind.red[6]}
            onClick={(e) => {
              e.stopPropagation();
              deleteProfile(option.value);
            }}
            disabled={authUser.user_level != USER_LEVELS.ADMIN}
          >
            <SquareMinus />
          </ActionIcon>
        )}
      </Group>
    );
  };

  return (
    <Group justify="space-between">
      <Group gap={5} style={{ paddingLeft: 10 }}>
        <Select
          size="xs"
          allowDeselect={false}
          value={selectedProfileId}
          onChange={setSelectedProfileId}
          data={Object.values(profiles).map((profile) => ({
            label: profile.name,
            value: `${profile.id}`,
          }))}
          renderOption={renderProfileOption}
        />

        <Tooltip label="Create Profile">
          <CreateProfilePopover />
        </Tooltip>
      </Group>

      <Box
        style={{
          display: 'flex',
          justifyContent: 'flex-end',
          padding: 10,
        }}
      >
        <Flex gap={6}>
          <Button
            leftSection={<SquarePen size={18} />}
            variant="default"
            size="xs"
            onClick={() => editChannel()}
            disabled={
              selectedTableIds.length == 0 ||
              authUser.user_level != USER_LEVELS.ADMIN
            }
          >
            Edit
          </Button>

          <Button
            leftSection={<SquareMinus size={18} />}
            variant="default"
            size="xs"
            onClick={deleteChannels}
            disabled={
              selectedTableIds.length == 0 ||
              authUser.user_level != USER_LEVELS.ADMIN
            }
          >
            Delete
          </Button>

          <Button
            leftSection={<SquarePlus size={18} />}
            variant="light"
            size="xs"
            onClick={() => editChannel(null, { forceAdd: true })}
            disabled={authUser.user_level != USER_LEVELS.ADMIN}
            p={5}
            color={theme.tailwind.green[5]}
            style={{
              ...(authUser.user_level == USER_LEVELS.ADMIN && {
                borderWidth: '1px',
                borderColor: theme.tailwind.green[5],
                color: 'white',
              }),
            }}
          >
            Add
          </Button>

          <Menu>
            <Menu.Target>
              <ActionIcon variant="default" size={30}>
                <EllipsisVertical size={18} />
              </ActionIcon>
            </Menu.Target>

            <Menu.Dropdown>
              <Menu.Item
                leftSection={<ArrowDown01 size={18} />}
                disabled={
                  selectedTableIds.length == 0 ||
                  authUser.user_level != USER_LEVELS.ADMIN
                }
                onClick={() => setAssignNumbersModalOpen(true)}
              >
                <Text size="xs">Assign #s</Text>
              </Menu.Item>

              <Menu.Item
                leftSection={<Binary size={18} />}
                disabled={authUser.user_level != USER_LEVELS.ADMIN}
                onClick={matchEpg}
              >
                <Text size="xs">
                  {selectedTableIds.length > 0
                    ? `Auto-Match (${selectedTableIds.length} selected)`
                    : 'Auto-Match EPG'}
                </Text>
              </Menu.Item>

              <Menu.Item
                leftSection={<Settings size={18} />}
                disabled={authUser.user_level != USER_LEVELS.ADMIN}
                onClick={() => setGroupManagerOpen(true)}
              >
                <Text size="xs">Edit Groups</Text>
              </Menu.Item>
            </Menu.Dropdown>
          </Menu>
        </Flex>
      </Box>

      <AssignChannelNumbersForm
        channelIds={selectedTableIds}
        isOpen={assignNumbersModalOpen}
        onClose={closeAssignChannelNumbersModal}
      />

      <GroupManager
        isOpen={groupManagerOpen}
        onClose={() => setGroupManagerOpen(false)}
      />

      <ConfirmationDialog
        opened={confirmDeleteProfileOpen}
        onClose={() => setConfirmDeleteProfileOpen(false)}
        onConfirm={() => executeDeleteProfile(profileToDelete?.id)}
        title="Confirm Profile Deletion"
        message={
          profileToDelete ? (
            <div style={{ whiteSpace: 'pre-line' }}>
              {`Are you sure you want to delete the following profile?

Name: ${profileToDelete.name}

This action cannot be undone.`}
            </div>
          ) : (
            'Are you sure you want to delete this profile? This action cannot be undone.'
          )
        }
        confirmLabel="Delete"
        cancelLabel="Cancel"
        actionKey="delete-profile"
        onSuppressChange={suppressWarning}
        size="md"
      />
    </Group>
  );
};

export default ChannelTableHeader;
