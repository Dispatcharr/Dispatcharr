import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Modal,
  Stack,
  Group,
  Text,
  TextInput,
  Button,
  ActionIcon,
  Flex,
  Badge,
  Alert,
  Divider,
  ScrollArea,
  useMantineTheme,
  Chip,
  Box,
} from '@mantine/core';
import {
  SquarePlus,
  SquarePen,
  SquareMinus,
  Check,
  X,
  AlertCircle,
  Database,
  Tv,
  Trash,
  Filter,
} from 'lucide-react';
import { notifications } from '@mantine/notifications';
import useChannelsStore from '../../store/channels';
import useWarningsStore from '../../store/warnings';
import ConfirmationDialog from '../ConfirmationDialog';
import API from '../../api';

// Move GroupItem outside to prevent recreation on every render
const GroupItem = React.memo(
  ({
    group,
    editingGroup,
    editName,
    onEditNameChange,
    onSaveEdit,
    onCancelEdit,
    onEdit,
    onDelete,
    groupUsage,
    canEditGroup,
    canDeleteGroup,
  }) => {
    const theme = useMantineTheme();

    const getGroupBadges = (group) => {
      const usage = groupUsage[group.id];
      const badges = [];

      if (usage?.hasChannels) {
        badges.push(
          <Badge
            key="channels"
            size="xs"
            color="blue"
            leftSection={<Tv size={10} />}
          >
            Channels
          </Badge>
        );
      }

      if (usage?.hasM3UAccounts) {
        badges.push(
          <Badge
            key="m3u"
            size="xs"
            color="purple"
            leftSection={<Database size={10} />}
          >
            M3U
          </Badge>
        );
      }

      return badges;
    };

    return (
      <Box
        style={{
          border: '1px solid #444',
          borderRadius: '8px',
          backgroundColor:
            editingGroup === group.id
              ? '#3f3f46'
              : group.enabled
                ? '#2A2A2E'
                : '#1E1E22',
          padding: '8px',
          marginBottom: '2px',
        }}
      >
        <Group justify="space-between" gap="xs" align="flex-start">
          <Stack gap={4} style={{ flex: 1 }}>
            {editingGroup === group.id ? (
              <TextInput
                value={editName}
                onChange={onEditNameChange}
                size="sm"
                onKeyPress={(e) => e.key === 'Enter' && onSaveEdit()}
                autoFocus
              />
            ) : (
              <>
                <Text size="sm" fw={500}>
                  {group.name}
                </Text>
                <Group gap={4}>{getGroupBadges(group)}</Group>
              </>
            )}
          </Stack>

          <Group gap="xs">
            {editingGroup === group.id ? (
              <>
                <ActionIcon color="green" size="sm" onClick={onSaveEdit}>
                  <Check size={14} />
                </ActionIcon>
                <ActionIcon color="gray" size="sm" onClick={onCancelEdit}>
                  <X size={14} />
                </ActionIcon>
              </>
            ) : (
              <>
                <ActionIcon
                  variant="transparent"
                  color={theme.tailwind.yellow[3]}
                  size="sm"
                  onClick={() => onEdit(group)}
                  disabled={!canEditGroup(group)}
                >
                  <SquarePen size={18} />
                </ActionIcon>
                <ActionIcon
                  variant="transparent"
                  color={theme.tailwind.red[6]}
                  size="sm"
                  onClick={() => onDelete(group)}
                  disabled={!canDeleteGroup(group)}
                >
                  <SquareMinus size="18" />
                </ActionIcon>
              </>
            )}
          </Group>
        </Group>
      </Box>
    );
  }
);

const GroupManager = React.memo(({ isOpen, onClose }) => {
  const channelGroups = useChannelsStore((s) => s.channelGroups);
  const canEditChannelGroup = useChannelsStore((s) => s.canEditChannelGroup);
  const canDeleteChannelGroup = useChannelsStore(
    (s) => s.canDeleteChannelGroup
  );
  const isWarningSuppressed = useWarningsStore((s) => s.isWarningSuppressed);
  const suppressWarning = useWarningsStore((s) => s.suppressWarning);

  const [editingGroup, setEditingGroup] = useState(null);
  const [editName, setEditName] = useState('');
  const [newGroupName, setNewGroupName] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [groupUsage, setGroupUsage] = useState({});
  const [loading, setLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [isCleaningUp, setIsCleaningUp] = useState(false);
  const [showChannelGroups, setShowChannelGroups] = useState(true);
  const [showM3UGroups, setShowM3UGroups] = useState(true);
  const [showUnusedGroups, setShowUnusedGroups] = useState(true);

  // Confirmation dialog states
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [groupToDelete, setGroupToDelete] = useState(null);
  const [confirmCleanupOpen, setConfirmCleanupOpen] = useState(false);
  const [deletingGroup, setDeletingGroup] = useState(false);

  // Memoize the channel groups array to prevent unnecessary re-renders
  const channelGroupsArray = useMemo(
    () => Object.values(channelGroups),
    [channelGroups]
  );

  // Memoize sorted groups to prevent re-sorting on every render
  const sortedGroups = useMemo(
    () => channelGroupsArray.sort((a, b) => a.name.localeCompare(b.name)),
    [channelGroupsArray]
  );

  // Filter groups based on search term and chip filters
  const filteredGroups = useMemo(() => {
    let filtered = sortedGroups;

    // Apply search filter
    if (searchTerm.trim()) {
      filtered = filtered.filter((group) =>
        group.name.toLowerCase().includes(searchTerm.toLowerCase())
      );
    }

    // Apply chip filters
    filtered = filtered.filter((group) => {
      const usage = groupUsage[group.id];
      if (!usage) return false;

      const hasChannels = usage.hasChannels;
      const hasM3U = usage.hasM3UAccounts;
      const isUnused = !hasChannels && !hasM3U;

      // If group is unused, only show if unused groups are enabled
      if (isUnused) {
        return showUnusedGroups;
      }

      // For groups with channels and/or M3U, show if either filter is enabled
      let shouldShow = false;
      if (hasChannels && showChannelGroups) shouldShow = true;
      if (hasM3U && showM3UGroups) shouldShow = true;

      return shouldShow;
    });

    return filtered;
  }, [
    sortedGroups,
    searchTerm,
    showChannelGroups,
    showM3UGroups,
    showUnusedGroups,
    groupUsage,
  ]);

  // Calculate filter counts
  const filterCounts = useMemo(() => {
    const counts = {
      channels: 0,
      m3u: 0,
      unused: 0,
    };

    sortedGroups.forEach((group) => {
      const usage = groupUsage[group.id];
      if (usage) {
        const hasChannels = usage.hasChannels;
        const hasM3U = usage.hasM3UAccounts;

        // Count groups with channels (including those with both)
        if (hasChannels) {
          counts.channels++;
        }

        // Count groups with M3U (including those with both)
        if (hasM3U) {
          counts.m3u++;
        }

        // Count truly unused groups
        if (!hasChannels && !hasM3U) {
          counts.unused++;
        }
      }
    });

    return counts;
  }, [sortedGroups, groupUsage]);

  const fetchGroupUsage = useCallback(async () => {
    setLoading(true);
    try {
      // Use the actual channel group data that already has the flags
      const usage = {};

      Object.values(channelGroups).forEach((group) => {
        usage[group.id] = {
          hasChannels: group.hasChannels ?? false,
          hasM3UAccounts: group.hasM3UAccounts ?? false,
          canEdit: group.canEdit ?? true,
          canDelete: group.canDelete ?? true,
        };
      });

      setGroupUsage(usage);
    } catch (error) {
      console.error('Error fetching group usage:', error);
    } finally {
      setLoading(false);
    }
  }, [channelGroups]);

  // Fetch group usage information when modal opens
  useEffect(() => {
    if (isOpen) {
      fetchGroupUsage();
    }
  }, [isOpen, fetchGroupUsage]);

  const handleEdit = useCallback((group) => {
    setEditingGroup(group.id);
    setEditName(group.name);
  }, []);

  const handleSaveEdit = useCallback(async () => {
    if (!editName.trim()) {
      notifications.show({
        title: 'Error',
        message: 'Group name cannot be empty',
        color: 'red',
      });
      return;
    }

    try {
      await API.updateChannelGroup({
        id: editingGroup,
        name: editName.trim(),
      });

      notifications.show({
        title: 'Success',
        message: 'Group updated successfully',
        color: 'green',
      });

      setEditingGroup(null);
      setEditName('');
      await fetchGroupUsage(); // Refresh usage data
    } catch (error) {
      notifications.show({
        title: 'Error',
        message: 'Failed to update group',
        color: 'red',
      });
    }
  }, [editName, editingGroup, fetchGroupUsage]);

  const handleCancelEdit = useCallback(() => {
    setEditingGroup(null);
    setEditName('');
  }, []);

  const handleCreate = useCallback(async () => {
    if (!newGroupName.trim()) {
      notifications.show({
        title: 'Error',
        message: 'Group name cannot be empty',
        color: 'red',
      });
      return;
    }

    try {
      await API.addChannelGroup({
        name: newGroupName.trim(),
      });

      notifications.show({
        title: 'Success',
        message: 'Group created successfully',
        color: 'green',
      });

      setNewGroupName('');
      setIsCreating(false);
      await fetchGroupUsage(); // Refresh usage data
    } catch (error) {
      notifications.show({
        title: 'Error',
        message: 'Failed to create group',
        color: 'red',
      });
    }
  }, [newGroupName, fetchGroupUsage]);

  const executeDeleteGroup = useCallback(
    async (group) => {
      setDeletingGroup(true);
      try {
        await API.deleteChannelGroup(group.id);

        notifications.show({
          title: 'Success',
          message: 'Group deleted successfully',
          color: 'green',
        });

        await fetchGroupUsage(); // Refresh usage data
      } catch (error) {
        notifications.show({
          title: 'Error',
          message: 'Failed to delete group',
          color: 'red',
        });
      } finally {
        setDeletingGroup(false);
        setConfirmDeleteOpen(false);
      }
    },
    [fetchGroupUsage]
  );

  const handleDelete = useCallback(
    async (group) => {
      const usage = groupUsage[group.id];

      if (
        usage &&
        (!usage.canDelete || usage.hasChannels || usage.hasM3UAccounts)
      ) {
        notifications.show({
          title: 'Cannot Delete',
          message:
            'This group is associated with channels or M3U accounts and cannot be deleted',
          color: 'orange',
        });
        return;
      }

      // Store group for confirmation dialog
      setGroupToDelete(group);

      // Skip warning if it's been suppressed
      if (isWarningSuppressed('delete-group')) {
        return executeDeleteGroup(group);
      }

      setConfirmDeleteOpen(true);
    },
    [groupUsage, isWarningSuppressed, executeDeleteGroup]
  );

  const executeCleanup = useCallback(async () => {
    setIsCleaningUp(true);
    try {
      const result = await API.cleanupUnusedChannelGroups();

      notifications.show({
        title: 'Cleanup Complete',
        message: `Successfully deleted ${result.deleted_count} unused groups`,
        color: 'green',
      });

      await fetchGroupUsage(); // Refresh usage data
      setConfirmCleanupOpen(false);
    } catch (error) {
      notifications.show({
        title: 'Cleanup Failed',
        message: 'Failed to cleanup unused groups',
        color: 'red',
      });
      setConfirmCleanupOpen(false);
    } finally {
      setIsCleaningUp(false);
    }
  }, [fetchGroupUsage]);

  const handleCleanup = useCallback(async () => {
    // Skip warning if it's been suppressed
    if (isWarningSuppressed('cleanup-groups')) {
      return executeCleanup();
    }

    setConfirmCleanupOpen(true);
  }, [isWarningSuppressed, executeCleanup]);

  const handleNewGroupNameChange = useCallback((e) => {
    setNewGroupName(e.target.value);
  }, []);

  const handleEditNameChange = useCallback((e) => {
    setEditName(e.target.value);
  }, []);

  const handleSearchChange = useCallback((e) => {
    setSearchTerm(e.target.value);
  }, []);

  if (!isOpen) return null;

  return (
    <>
      <Modal
        opened={isOpen}
        onClose={onClose}
        title="Group Manager"
        size="lg"
        scrollAreaComponent={ScrollArea.Autosize}
        zIndex={2000}
      >
        <Stack>
          <Alert icon={<AlertCircle size={16} />} color="blue" variant="light">
            Manage channel groups. Groups associated with M3U accounts or
            containing channels cannot be deleted.
          </Alert>

          {/* Create new group section */}
          <Group justify="space-between">
            {isCreating ? (
              <Group style={{ flex: 1 }}>
                <TextInput
                  placeholder="Enter group name"
                  value={newGroupName}
                  onChange={handleNewGroupNameChange}
                  style={{ flex: 1 }}
                  onKeyPress={(e) => e.key === 'Enter' && handleCreate()}
                  autoFocus
                />
                <ActionIcon color="green" onClick={handleCreate}>
                  <Check size={16} />
                </ActionIcon>
                <ActionIcon
                  color="gray"
                  onClick={() => {
                    setIsCreating(false);
                    setNewGroupName('');
                  }}
                >
                  <X size={16} />
                </ActionIcon>
              </Group>
            ) : (
              <Button
                leftSection={<SquarePlus size={16} />}
                variant="light"
                size="sm"
                onClick={() => setIsCreating(true)}
              >
                Add Group
              </Button>
            )}

            {!isCreating && (
              <Button
                leftSection={<Trash size={16} />}
                variant="light"
                size="sm"
                color="orange"
                onClick={handleCleanup}
                loading={isCleaningUp}
              >
                Cleanup Unused
              </Button>
            )}
          </Group>

          <Divider />

          {/* Filter Controls */}
          <Stack gap="sm">
            <Group justify="space-between" align="center">
              <Group align="center" gap="sm">
                <Filter size={16} />
                <Text size="sm" fw={600}>
                  Filter Groups
                </Text>
              </Group>
              <TextInput
                placeholder="Search groups..."
                value={searchTerm}
                onChange={handleSearchChange}
                size="sm"
                style={{ width: '200px' }}
                rightSection={
                  searchTerm && (
                    <ActionIcon
                      size="sm"
                      variant="subtle"
                      onClick={() => setSearchTerm('')}
                    >
                      <X size={14} />
                    </ActionIcon>
                  )
                }
              />
            </Group>

            <Group gap="xs" align="center">
              <Text size="xs" c="dimmed">
                Show:
              </Text>
              <Chip
                checked={showChannelGroups}
                onChange={setShowChannelGroups}
                size="sm"
                color="blue"
              >
                <Group gap={4}>
                  <Tv size={10} />
                  Channel Groups ({filterCounts.channels})
                </Group>
              </Chip>
              <Chip
                checked={showM3UGroups}
                onChange={setShowM3UGroups}
                size="sm"
                color="purple"
              >
                <Group gap={4}>
                  <Database size={10} />
                  M3U Groups ({filterCounts.m3u})
                </Group>
              </Chip>
              <Chip
                checked={showUnusedGroups}
                onChange={setShowUnusedGroups}
                size="sm"
                color="gray"
              >
                Unused Groups ({filterCounts.unused})
              </Chip>
            </Group>
          </Stack>

          <Divider />

          {/* Existing groups */}
          <Stack>
            <Text size="sm" fw={600}>
              Groups ({filteredGroups.length}
              {(searchTerm ||
                !showChannelGroups ||
                !showM3UGroups ||
                !showUnusedGroups) &&
                ` of ${sortedGroups.length}`}
              )
            </Text>

            {loading ? (
              <Text size="sm" c="dimmed">
                Loading group information...
              </Text>
            ) : filteredGroups.length === 0 ? (
              <Text size="sm" c="dimmed">
                {searchTerm ||
                !showChannelGroups ||
                !showM3UGroups ||
                !showUnusedGroups
                  ? 'No groups found matching your filters'
                  : 'No groups found'}
              </Text>
            ) : (
              <Stack gap="xs">
                {filteredGroups.map((group) => (
                  <GroupItem
                    key={group.id}
                    group={group}
                    editingGroup={editingGroup}
                    editName={editName}
                    onEditNameChange={handleEditNameChange}
                    onSaveEdit={handleSaveEdit}
                    onCancelEdit={handleCancelEdit}
                    onEdit={handleEdit}
                    onDelete={handleDelete}
                    groupUsage={groupUsage}
                    canEditGroup={canEditChannelGroup}
                    canDeleteGroup={canDeleteChannelGroup}
                  />
                ))}
              </Stack>
            )}
          </Stack>

          <Divider />

          <Flex justify="flex-end">
            <Button variant="default" onClick={onClose}>
              Close
            </Button>
          </Flex>
        </Stack>
      </Modal>

      <ConfirmationDialog
        opened={confirmDeleteOpen}
        onClose={() => setConfirmDeleteOpen(false)}
        onConfirm={() => groupToDelete && executeDeleteGroup(groupToDelete)}
        loading={deletingGroup}
        title="Confirm Group Deletion"
        message={
          groupToDelete ? (
            <div style={{ whiteSpace: 'pre-line' }}>
              {`Are you sure you want to delete the following group?

Name: ${groupToDelete.name}

This action cannot be undone.`}
            </div>
          ) : (
            'Are you sure you want to delete this group? This action cannot be undone.'
          )
        }
        confirmLabel="Delete"
        cancelLabel="Cancel"
        actionKey="delete-group"
        onSuppressChange={suppressWarning}
        size="md"
        zIndex={2100}
      />

      <ConfirmationDialog
        opened={confirmCleanupOpen}
        onClose={() => setConfirmCleanupOpen(false)}
        onConfirm={executeCleanup}
        loading={isCleaningUp}
        title="Confirm Group Cleanup"
        message={
          <div style={{ whiteSpace: 'pre-line' }}>
            {`Are you sure you want to cleanup all unused groups?

This will permanently delete all groups that are not associated with any channels or M3U accounts.

This action cannot be undone.`}
          </div>
        }
        confirmLabel="Cleanup"
        cancelLabel="Cancel"
        actionKey="cleanup-groups"
        onSuppressChange={suppressWarning}
        size="md"
        zIndex={2100}
      />
    </>
  );
});

export default GroupManager;
