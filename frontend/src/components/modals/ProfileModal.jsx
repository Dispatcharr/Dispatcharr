import React, { useState, useEffect } from 'react';
import {
  Alert,
  Box,
  Button,
  Group,
  Modal,
  Stack,
  Text,
  TextInput,
  ActionIcon,
  Tooltip,
} from '@mantine/core';
import { Copy, SquareMinus, SquarePen } from 'lucide-react';
import API from '../../api';
import { notifications } from '@mantine/notifications';
import useChannelsStore from '../../store/channels';
import { USER_LEVELS } from '../../constants';

const ProfileModal = ({ opened, onClose, mode, profile }) => {
  const [profileNameInput, setProfileNameInput] = useState('');
  const setSelectedProfileId = useChannelsStore((s) => s.setSelectedProfileId);

  useEffect(() => {
    if (opened && profile) {
      setProfileNameInput(
        mode === 'duplicate' ? `${profile.name} Copy` : profile.name
      );
    }
  }, [opened, mode, profile]);

  const closeModal = () => {
    setProfileNameInput('');
    onClose();
  };

  const submitProfileModal = async () => {
    const trimmedName = profileNameInput.trim();

    if (!mode || !profile) return;

    if (!trimmedName) {
      notifications.show({
        title: 'Profile name is required',
        color: 'red.5',
      });
      return;
    }

    if (mode === 'edit') {
      if (trimmedName === profile.name) {
        closeModal();
        return;
      }

      const updatedProfile = await API.updateChannelProfile({
        id: profile.id,
        name: trimmedName,
      });

      if (updatedProfile) {
        notifications.show({
          title: 'Profile renamed',
          message: `${profile.name} → ${trimmedName}`,
          color: 'green.5',
        });
        closeModal();
      }
    }

    if (mode === 'duplicate') {
      const duplicatedProfile = await API.duplicateChannelProfile(
        profile.id,
        trimmedName
      );

      if (duplicatedProfile) {
        notifications.show({
          title: 'Profile duplicated',
          message: `${profile.name} copied to ${duplicatedProfile.name}`,
          color: 'green.5',
        });
        setSelectedProfileId(`${duplicatedProfile.id}`);
        closeModal();
      }
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={closeModal}
      title={
        mode === 'duplicate'
          ? `Duplicate Profile: ${profile?.name}`
          : `Rename Profile: ${profile?.name}`
      }
      centered
      size="sm"
    >
      <Stack gap="sm">
        {mode === 'edit' && (
          <Alert color="yellow" title="Warning">
            <Text size="sm">
              If you have any profile links (M3U, EPG, HDHR) shared with
              clients, they will need to be updated after renaming this profile.
            </Text>
          </Alert>
        )}
        <TextInput
          label="Profile name"
          placeholder="Profile name"
          value={profileNameInput}
          onChange={(event) => setProfileNameInput(event.currentTarget.value)}
          data-autofocus
        />

        <Group justify="flex-end" gap="xs">
          <Button variant="default" size="xs" onClick={closeModal}>
            Cancel
          </Button>
          <Button size="xs" onClick={submitProfileModal}>
            {mode === 'duplicate' ? 'Duplicate' : 'Save'}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export const renderProfileOption = (
  theme,
  profiles,
  onEditProfile,
  onDeleteProfile,
  authUser
) => {
  return ({ option }) => {
    return (
      <Group justify="space-between" style={{ width: '100%' }}>
        <Box>{option.label}</Box>
        {option.value != '0' && (
          <Group gap={4} wrap="nowrap">
            <Tooltip label="Rename profile">
              <ActionIcon
                size="xs"
                variant="transparent"
                color={theme.tailwind.yellow[3]}
                onClick={(e) => {
                  e.stopPropagation();
                  onEditProfile('edit', option.value);
                }}
                disabled={authUser.user_level != USER_LEVELS.ADMIN}
              >
                <SquarePen size={14} />
              </ActionIcon>
            </Tooltip>

            <Tooltip label="Duplicate profile">
              <ActionIcon
                size="xs"
                variant="transparent"
                color={theme.tailwind.green[5]}
                onClick={(e) => {
                  e.stopPropagation();
                  onEditProfile('duplicate', option.value);
                }}
                disabled={authUser.user_level != USER_LEVELS.ADMIN}
              >
                <Copy size={14} />
              </ActionIcon>
            </Tooltip>

            <ActionIcon
              size="xs"
              variant="transparent"
              color={theme.tailwind.red[6]}
              onClick={(e) => {
                e.stopPropagation();
                onDeleteProfile(option.value);
              }}
              disabled={authUser.user_level != USER_LEVELS.ADMIN}
            >
              <SquareMinus />
            </ActionIcon>
          </Group>
        )}
      </Group>
    );
  };
};

export default ProfileModal;
