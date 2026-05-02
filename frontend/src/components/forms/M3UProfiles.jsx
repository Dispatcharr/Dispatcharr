import React, { useEffect, useState } from 'react';
import M3UProfile from './M3UProfile';
import AccountInfoModal from './AccountInfoModal';
import usePlaylistsStore from '../../store/playlists';
import ConfirmationDialog from '../ConfirmationDialog';
import useWarningsStore from '../../store/warnings';
import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Flex,
  Group,
  Modal,
  NumberInput,
  Stack,
  Switch,
  Text,
  useMantineTheme,
} from '@mantine/core';
import { Info, SquareMinus, SquarePen } from 'lucide-react';
import {
  deleteM3UProfile,
  updateM3UProfile,
} from '../../utils/forms/M3uProfileUtils.js';
import {
  getExpirationInfo,
  isAccountExpired,
  profileSortComparator,
} from '../../utils/forms/M3uProfilesUtils.js';

const M3uProfileCard = ({
  item,
  accountType,
  onClickInfo,
  onClickEdit,
  onClickDelete,
  onChangeMaxStreams,
  onChangeActive,
}) => {
  const theme = useMantineTheme();
  const accountStatus = item.custom_properties?.user_info?.status ?? null;
  const expirationInfo = getExpirationInfo(item);
  const expired = isAccountExpired(item);

  return (
    <Card>
      <Stack spacing="sm">
        {/* Header with name and status badges */}
        <Group justify="space-between" align="center">
          <Group spacing="sm" align="center">
            <Stack spacing={2}>
              <Text fw={600}>{item.name}</Text>
              {/* Show notes if they exist */}
              {item.custom_properties?.notes && (
                <Text size="xs" c="dimmed" style={{ fontStyle: 'italic' }}>
                  {item.custom_properties.notes}
                </Text>
              )}
            </Stack>
            {accountType === 'XC' && item.custom_properties && (
              <Group spacing="xs">
                {/* Account status badge */}
                {accountStatus && (
                  <Badge
                    size="sm"
                    color={
                      accountStatus === 'Active'
                        ? 'green'
                        : expired
                          ? 'red'
                          : 'gray'
                    }
                    variant="light"
                  >
                    {accountStatus}
                  </Badge>
                )}
                {/* Expiration badge */}
                {expirationInfo && (
                  <Badge
                    size="sm"
                    color={expirationInfo.color}
                    variant="outline"
                  >
                    {expirationInfo.text}
                  </Badge>
                )}
                {/* Info button next to badges */}
                <ActionIcon
                  size="sm"
                  variant="filled"
                  color="blue"
                  onClick={onClickInfo}
                  title="View account information"
                  style={{
                    backgroundColor: 'rgba(34, 139, 230, 0.1)',
                    color: '#228be6',
                  }}
                >
                  <Info size="16" />
                </ActionIcon>
              </Group>
            )}
          </Group>
        </Group>

        {/* Max Streams and Actions */}
        <Flex gap="sm" align="flex-end">
          <NumberInput
            label="Max Streams"
            value={item.max_streams}
            disabled={item.is_default}
            onChange={onChangeMaxStreams}
            style={{ flex: 1 }}
          />

          <Group spacing="xs" style={{ paddingBottom: 8 }}>
            {/* Toggle switch */}
            <Switch
              checked={item.is_active}
              onChange={onChangeActive}
              disabled={item.is_default}
              label="Active"
              labelPosition="left"
              size="sm"
            />

            {/* Always show edit button, but limit what can be edited for default profiles */}
            <ActionIcon
              size="sm"
              variant="transparent"
              color={theme.tailwind.yellow[3]}
              onClick={onClickEdit}
              title={
                item.is_default ? 'Edit profile name and notes' : 'Edit profile'
              }
            >
              <SquarePen size="20" />
            </ActionIcon>

            {!item.is_default && (
              <>
                <ActionIcon
                  color={theme.tailwind.red[6]}
                  onClick={onClickDelete}
                  size="small"
                  variant="transparent"
                  title="Delete profile"
                >
                  <SquareMinus size="20" />
                </ActionIcon>
              </>
            )}
          </Group>
        </Flex>
      </Stack>
    </Card>
  );
};

const M3UProfiles = ({ playlist = null, isOpen, onClose }) => {
  const allProfiles = usePlaylistsStore((s) => s.profiles);
  const fetchPlaylist = usePlaylistsStore((s) => s.fetchPlaylist);
  const isWarningSuppressed = useWarningsStore((s) => s.isWarningSuppressed);
  const suppressWarning = useWarningsStore((s) => s.suppressWarning);

  const [profileEditorOpen, setProfileEditorOpen] = useState(false);
  const [profile, setProfile] = useState(null);
  const [profiles, setProfiles] = useState([]);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [profileToDelete, setProfileToDelete] = useState(null);
  const [deletingProfile, setDeletingProfile] = useState(false);
  const [accountInfoOpen, setAccountInfoOpen] = useState(false);
  const [selectedProfileForInfo, setSelectedProfileForInfo] = useState(null);

  const handleRefreshAccountInfo = async () => {
    // Refresh the playlist data to get updated account info
    if (playlist?.id) {
      await fetchPlaylist(playlist.id);
    }
  };

  useEffect(() => {
    try {
      // Make sure playlist exists, has an id, and profiles exist for this playlist
      if (playlist && playlist.id && allProfiles && allProfiles[playlist.id]) {
        setProfiles(allProfiles[playlist.id]);
      } else {
        // Reset profiles if none are available
        setProfiles([]);
      }
    } catch (error) {
      console.error('Error setting profiles:', error);
      setProfiles([]);
    }
  }, [allProfiles, playlist]);

  const editProfile = (profile = null) => {
    if (profile) {
      setProfile(profile);
    }

    setProfileEditorOpen(true);
  };
  const deleteProfile = async (id) => {
    if (!playlist || !playlist.id) return;

    // Get profile details for the confirmation dialog
    const profileObj = profiles.find((p) => p.id === id);
    setProfileToDelete(profileObj);
    setDeleteTarget(id);

    // Skip warning if it's been suppressed
    if (isWarningSuppressed('delete-profile')) {
      return executeDeleteProfile(id);
    }

    setConfirmDeleteOpen(true);
  };

  const executeDeleteProfile = async (id) => {
    if (!playlist || !playlist.id) return;
    setDeletingProfile(true);
    try {
      await deleteM3UProfile(playlist, id);
    } catch (error) {
      console.error('Error deleting profile:', error);
    } finally {
      setDeletingProfile(false);
      setConfirmDeleteOpen(false);
    }
  };

  const toggleActive = async (values) => {
    if (!playlist || !playlist.id) return;
    try {
      await updateM3UProfile(playlist.id, {
        ...values,
        is_active: !values.is_active,
      });
    } catch (error) {
      console.error('Error toggling profile active state:', error);
    }
  };

  const modifyMaxStreams = async (value, item) => {
    if (!playlist || !playlist.id) return;
    try {
      await updateM3UProfile(playlist.id, {
        ...item,
        max_streams: value,
      });
    } catch (error) {
      console.error('Error updating max streams:', error);
    }
  };

  const closeEditor = () => {
    setProfileEditorOpen(false);
    // Delay clearing the profile until after the modal animation completes
    setTimeout(() => {
      setProfile(null);
    }, 300); // Mantine modal animation typically takes ~200-300ms
  };

  const showAccountInfo = (profile) => {
    setSelectedProfileForInfo(profile);
    setAccountInfoOpen(true);
  };

  const closeAccountInfo = () => {
    setSelectedProfileForInfo(null);
    setAccountInfoOpen(false);
  };

  // Don't render if modal is not open, or if playlist data is invalid
  if (!isOpen || !playlist || !playlist.id) {
    return <></>;
  }

  // Make sure profiles is always an array even if we have no data
  const profilesArray = Array.isArray(profiles) ? profiles : [];

  return (
    <>
      <Modal
        opened={isOpen}
        onClose={onClose}
        title="Profiles"
        scrollAreaComponent={Modal.NativeScrollArea}
        lockScroll={false}
        withinPortal={true}
        yOffset="2vh"
      >
        {profilesArray.sort(profileSortComparator).map((item) => {
          return (
            <M3uProfileCard
              key={item.id}
              item={item}
              accountType={playlist?.account_type}
              onClickInfo={() => showAccountInfo(item)}
              onChangeMaxStreams={(value) => modifyMaxStreams(value, item)}
              onChangeActive={() => toggleActive(item)}
              onClickEdit={() => editProfile(item)}
              onClickDelete={() => deleteProfile(item.id)}
            />
          );
        })}

        <Flex mih={50} gap="xs" justify="flex-end" align="flex-end">
          <Button
            variant="contained"
            color="primary"
            size="small"
            onClick={() => editProfile()}
            style={{ width: '100%' }}
          >
            New
          </Button>
        </Flex>
      </Modal>{' '}
      <M3UProfile
        m3u={playlist}
        profile={profile}
        isOpen={profileEditorOpen}
        onClose={closeEditor}
      />
      <ConfirmationDialog
        opened={confirmDeleteOpen}
        onClose={() => setConfirmDeleteOpen(false)}
        onConfirm={() => executeDeleteProfile(deleteTarget)}
        loading={deletingProfile}
        title="Confirm Profile Deletion"
        message={
          profileToDelete ? (
            <div style={{ whiteSpace: 'pre-line' }}>
              {`Are you sure you want to delete the following profile?

Name: ${profileToDelete.name}
Max Streams: ${profileToDelete.max_streams}

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
      <AccountInfoModal
        isOpen={accountInfoOpen}
        onClose={closeAccountInfo}
        profile={selectedProfileForInfo}
        onRefresh={handleRefreshAccountInfo}
      />
    </>
  );
};

export default M3UProfiles;
