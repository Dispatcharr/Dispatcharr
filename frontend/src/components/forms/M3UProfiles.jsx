import React, { useState, useEffect } from 'react';
import API from '../../api';
import M3UProfile from './M3UProfile';
import AccountInfoModal from './AccountInfoModal';
import usePlaylistsStore from '../../store/playlists';
import ConfirmationDialog from '../ConfirmationDialog';
import useWarningsStore from '../../store/warnings';
import {
  Card,
  Checkbox,
  Flex,
  Modal,
  Button,
  Box,
  ActionIcon,
  Text,
  NumberInput,
  useMantineTheme,
  Center,
  Group,
  Switch,
  Badge,
  Stack,
} from '@mantine/core';
import { SquareMinus, SquarePen, Info } from 'lucide-react';

const M3UProfiles = ({ playlist = null, isOpen, onClose }) => {
  const theme = useMantineTheme();

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
    try {
      await API.deleteM3UProfile(playlist.id, id);
      setConfirmDeleteOpen(false);
    } catch (error) {
      console.error('Error deleting profile:', error);
      setConfirmDeleteOpen(false);
    }
  };

  const toggleActive = async (values) => {
    if (!playlist || !playlist.id) return;
    try {
      await API.updateM3UProfile(playlist.id, {
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
      await API.updateM3UProfile(playlist.id, {
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

  // Helper function to get account status from profile
  const getAccountStatus = (profile) => {
    if (!profile.custom_properties?.user_info) return null;
    return profile.custom_properties.user_info.status;
  };

  // Helper function to check if account is expired
  const isAccountExpired = (profile) => {
    if (!profile.custom_properties?.user_info?.exp_date) return false;
    try {
      const expDate = new Date(
        parseInt(profile.custom_properties.user_info.exp_date) * 1000
      );
      return expDate < new Date();
    } catch {
      return false;
    }
  };

  // Helper function to get account expiration info
  const getExpirationInfo = (profile) => {
    if (!profile.custom_properties?.user_info?.exp_date) return null;
    try {
      const expDate = new Date(
        parseInt(profile.custom_properties.user_info.exp_date) * 1000
      );
      const now = new Date();
      const diffMs = expDate - now;

      if (diffMs <= 0) return { text: 'Expired', color: 'red' };

      const days = Math.floor(diffMs / (1000 * 60 * 60 * 24));
      if (days > 30) return { text: `${days} days`, color: 'green' };
      if (days > 7) return { text: `${days} days`, color: 'yellow' };
      if (days > 0) return { text: `${days} days`, color: 'orange' };

      const hours = Math.floor(diffMs / (1000 * 60 * 60));
      return { text: `${hours}h`, color: 'red' };
    } catch {
      return null;
    }
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
        {profilesArray
          .sort((a, b) => {
            // Always put default profile first
            if (a.is_default) return -1;
            if (b.is_default) return 1;
            // Sort remaining profiles alphabetically by name
            return a.name.localeCompare(b.name);
          })
          .map((item) => {
            const accountStatus = getAccountStatus(item);
            const expirationInfo = getExpirationInfo(item);
            const expired = isAccountExpired(item);

            return (
              <Card key={item.id}>
                <Stack spacing="sm">
                  {/* Header with name and status badges */}
                  <Group justify="space-between" align="center">
                    <Group spacing="sm" align="center">
                      <Stack spacing={2}>
                        <Text fw={600}>{item.name}</Text>
                        {/* Show notes if they exist */}
                        {item.custom_properties?.notes && (
                          <Text
                            size="xs"
                            c="dimmed"
                            style={{ fontStyle: 'italic' }}
                          >
                            {item.custom_properties.notes}
                          </Text>
                        )}
                      </Stack>
                      {playlist?.account_type === 'XC' &&
                        item.custom_properties && (
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
                              onClick={() => showAccountInfo(item)}
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
                      onChange={(value) => modifyMaxStreams(value, item)}
                      style={{ flex: 1 }}
                    />

                    <Group spacing="xs" style={{ paddingBottom: 8 }}>
                      {/* Toggle switch */}
                      <Switch
                        checked={item.is_active}
                        onChange={() => toggleActive(item)}
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
                        onClick={() => editProfile(item)}
                        title={
                          item.is_default
                            ? 'Edit profile name and notes'
                            : 'Edit profile'
                        }
                      >
                        <SquarePen size="20" />
                      </ActionIcon>

                      {!item.is_default && (
                        <>
                          <ActionIcon
                            color={theme.tailwind.red[6]}
                            onClick={() => deleteProfile(item.id)}
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
