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
  useMantineTheme,
} from '@mantine/core';
import {
  ArrowDown01,
  Binary,
  CircleCheck,
  EllipsisVertical,
  SquareMinus,
  SquarePen,
  SquarePlus,
  Settings,
  Eye,
  EyeOff,
  Filter,
  Square,
  SquareCheck,
  Pin,
  PinOff,
  Lock,
  LockOpen,
} from 'lucide-react';
import API from '../../../api';
import { notifications } from '@mantine/notifications';
import useChannelsStore from '../../../store/channels';
import useChannelsTableStore from '../../../store/channelsTable';
import useAuthStore from '../../../store/auth';
import { USER_LEVELS } from '../../../constants';
import AssignChannelNumbersForm from '../../forms/AssignChannelNumbers';
import GroupManager from '../../forms/GroupManager';
import ConfirmationDialog from '../../ConfirmationDialog';
import useWarningsStore from '../../../store/warnings';
import ProfileModal, { renderProfileOption } from '../../modals/ProfileModal';
import EPGMatchModal from '../../modals/EPGMatchModal';

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
  table,
  showDisabled,
  setShowDisabled,
  showOnlyStreamlessChannels,
  setShowOnlyStreamlessChannels,
}) => {
  const theme = useMantineTheme();

  const [channelNumAssignmentStart, setChannelNumAssignmentStart] = useState(1);
  const [assignNumbersModalOpen, setAssignNumbersModalOpen] = useState(false);
  const [groupManagerOpen, setGroupManagerOpen] = useState(false);
  const [epgMatchModalOpen, setEpgMatchModalOpen] = useState(false);
  const [confirmDeleteProfileOpen, setConfirmDeleteProfileOpen] =
    useState(false);
  const [profileToDelete, setProfileToDelete] = useState(null);
  const [deletingProfile, setDeletingProfile] = useState(false);
  const [profileModalState, setProfileModalState] = useState({
    opened: false,
    mode: null,
    profileId: null,
  });

  const profiles = useChannelsStore((s) => s.profiles);
  const selectedProfileId = useChannelsStore((s) => s.selectedProfileId);
  const setSelectedProfileId = useChannelsStore((s) => s.setSelectedProfileId);
  const authUser = useAuthStore((s) => s.user);
  const isWarningSuppressed = useWarningsStore((s) => s.isWarningSuppressed);
  const suppressWarning = useWarningsStore((s) => s.suppressWarning);
  const isUnlocked = useChannelsTableStore((s) => s.isUnlocked);
  const setIsUnlocked = useChannelsTableStore((s) => s.setIsUnlocked);

  const headerPinned = table?.headerPinned ?? false;
  const setHeaderPinned = table?.setHeaderPinned || (() => {});
  const closeAssignChannelNumbersModal = () => {
    setAssignNumbersModalOpen(false);
  };

  const closeProfileModal = () => {
    setProfileModalState({ opened: false, mode: null, profileId: null });
  };

  const openProfileModal = (mode, profileId) => {
    if (!profiles[profileId]) return;
    setProfileModalState({ opened: true, mode, profileId });
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
    setDeletingProfile(true);
    try {
      await API.deleteChannelProfile(id);
    } finally {
      setDeletingProfile(false);
      setConfirmDeleteProfileOpen(false);
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
      API.requeryChannels();
    } catch (err) {
      console.error(err);
      notifications.show({
        title: 'Failed to assign channels',
        color: 'red.5',
      });
    }
  };

  const renderModalOption = renderProfileOption(
    theme,
    profiles,
    openProfileModal,
    deleteProfile,
    authUser
  );

  const toggleShowDisabled = () => {
    setShowDisabled(!showDisabled);
  };

  const toggleShowOnlyStreamlessChannels = () => {
    setShowOnlyStreamlessChannels(!showOnlyStreamlessChannels);
  };

  const toggleHeaderPinned = () => {
    setHeaderPinned(!headerPinned);
  };

  const toggleUnlock = () => {
    setIsUnlocked(!isUnlocked);
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
          renderOption={renderModalOption}
          style={{ minWidth: 190 }}
        />

        <Tooltip label="Create Profile">
          <CreateProfilePopover />
        </Tooltip>

        {isUnlocked && (
          <Text
            size="xs"
            c="yellow.5"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 4,
              paddingLeft: 10,
              fontWeight: 500,
            }}
          >
            <LockOpen size={14} />
            Editing Mode
          </Text>
        )}
      </Group>

      <Box
        style={{
          display: 'flex',
          justifyContent: 'flex-end',
          padding: 10,
        }}
      >
        <Flex gap={6}>
          <Menu shadow="md" width={200}>
            <Menu.Target>
              <Button size="xs" variant="default" onClick={() => {}}>
                <Filter size={18} />
              </Button>
            </Menu.Target>

            <Menu.Dropdown>
              <Menu.Item
                onClick={toggleShowDisabled}
                leftSection={
                  showDisabled ? <Eye size={18} /> : <EyeOff size={18} />
                }
                disabled={selectedProfileId === '0'}
              >
                <Text size="xs">
                  {showDisabled ? 'Hide Disabled' : 'Show Disabled'}
                </Text>
              </Menu.Item>

              <Menu.Item
                onClick={toggleShowOnlyStreamlessChannels}
                leftSection={
                  showOnlyStreamlessChannels ? (
                    <SquareCheck size={18} />
                  ) : (
                    <Square size={18} />
                  )
                }
              >
                <Text size="xs">Only Empty Channels</Text>
              </Menu.Item>
            </Menu.Dropdown>
          </Menu>

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
                leftSection={
                  headerPinned ? <Pin size={18} /> : <PinOff size={18} />
                }
                onClick={toggleHeaderPinned}
              >
                <Text size="xs">
                  {headerPinned ? 'Unpin Headers' : 'Pin Headers'}
                </Text>
              </Menu.Item>

              <Menu.Item
                leftSection={
                  isUnlocked ? <LockOpen size={18} /> : <Lock size={18} />
                }
                onClick={toggleUnlock}
                disabled={authUser.user_level != USER_LEVELS.ADMIN}
              >
                <Text size="xs">
                  {isUnlocked ? 'Lock Table' : 'Unlock for Editing'}
                </Text>
              </Menu.Item>

              <Menu.Divider />

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
                onClick={() => setEpgMatchModalOpen(true)}
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

      <ProfileModal
        opened={profileModalState.opened}
        onClose={closeProfileModal}
        mode={profileModalState.mode}
        profile={
          profileModalState.profileId
            ? profiles[profileModalState.profileId]
            : null
        }
        onDeleteProfile={deleteProfile}
      />

      <AssignChannelNumbersForm
        channelIds={selectedTableIds}
        isOpen={assignNumbersModalOpen}
        onClose={closeAssignChannelNumbersModal}
      />

      <GroupManager
        isOpen={groupManagerOpen}
        onClose={() => setGroupManagerOpen(false)}
      />

      <EPGMatchModal
        opened={epgMatchModalOpen}
        onClose={() => setEpgMatchModalOpen(false)}
        selectedChannelIds={selectedTableIds}
      />

      <ConfirmationDialog
        opened={confirmDeleteProfileOpen}
        onClose={() => setConfirmDeleteProfileOpen(false)}
        onConfirm={() => executeDeleteProfile(profileToDelete?.id)}
        loading={deletingProfile}
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
