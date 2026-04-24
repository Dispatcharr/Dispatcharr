import React, { useEffect, useMemo, useRef, useState } from 'react';
import useChannelsStore from '../../store/channels';
import useChannelsTableStore from '../../store/channelsTable.jsx';
import useStreamProfilesStore from '../../store/streamProfiles';
import useEPGsStore from '../../store/epgs';
import ChannelGroupForm from './ChannelGroup';
import {
  ActionIcon,
  Box,
  Button,
  Center,
  Divider,
  Flex,
  Group,
  Modal,
  Paper,
  Popover,
  PopoverDropdown,
  PopoverTarget,
  ScrollArea,
  Select,
  Stack,
  Text,
  TextInput,
  Tooltip,
  UnstyledButton,
  useMantineTheme,
} from '@mantine/core';
import { ListOrdered, SquarePlus, X } from 'lucide-react';
import { FixedSizeList as List } from 'react-window';
import { useForm } from '@mantine/form';
import { USER_LEVEL_LABELS, USER_LEVELS } from '../../constants';
import { useChannelLogoSelection } from '../../hooks/useSmartLogos';
import LazyLogo from '../LazyLogo';
import logo from '../../images/logo.png';
import ConfirmationDialog from '../ConfirmationDialog';
import useWarningsStore from '../../store/warnings';
import { showNotification } from '../../utils/notificationUtils.js';
import { requeryChannels } from '../../utils/forms/ChannelUtils.js';
import {
  batchSetEPG,
  buildEpgAssociations,
  buildSubmitValues,
  bulkRegexRenameChannels,
  computeRegexPreview,
  getChannelGroupChange,
  getEpgChange,
  getLogoChange,
  getMatureContentChange,
  getRegexNameChange,
  getStreamProfileChange,
  getUserLevelChange,
  setChannelLogosFromEpg,
  setChannelNamesFromEpg,
  setChannelTvgIdsFromEpg,
  updateChannels,
} from '../../utils/forms/ChannelBatchUtils.js';

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
  const [settingNames, setSettingNames] = useState(false);
  const [settingLogos, setSettingLogos] = useState(false);
  const [settingTvgIds, setSettingTvgIds] = useState(false);
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
      is_adult: '-1',
    },
  });

  // Build confirmation message based on selected changes
  const getConfirmationMessage = () => {
    const values = form.getValues();

    return [
      getRegexNameChange(regexFind, regexReplace),
      getChannelGroupChange(selectedChannelGroup, channelGroups),
      getLogoChange(selectedLogoId, channelLogos),
      getStreamProfileChange(values.stream_profile_id, streamProfiles),
      getUserLevelChange(values.user_level, USER_LEVEL_LABELS),
      getMatureContentChange(values.is_adult),
      getEpgChange(selectedDummyEpgId, epgs),
    ].filter(Boolean);
  };

  const handleSubmit = () => {
    const changes = getConfirmationMessage();

    // If no changes detected, show notification
    if (changes.length === 0) {
      showNotification({
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

    try {
      const values = buildSubmitValues(
        form.getValues(),
        selectedChannelGroup,
        selectedLogoId
      );

      if (Object.keys(values).length > 0) {
        await updateChannels(channelIds, values);
      }

      if (regexFind.trim().length > 0) {
        await bulkRegexRenameChannels(channelIds, regexFind, regexReplace, 'g');
      }

      const associations = await buildEpgAssociations(
        selectedDummyEpgId,
        channelIds,
        epgs,
        tvgs
      );
      if (associations) {
        await batchSetEPG(associations);
      }

      await Promise.all([
        requeryChannels(),
        useChannelsStore.getState().fetchChannelIds(),
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
      showNotification({
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
    setSettingNames(true);
    try {
      // Start the backend task
      await setChannelNamesFromEpg(channelIds);

      // The task will send WebSocket updates for progress
      // Just show that it started successfully
      showNotification({
        title: 'Task Started',
        message: `Started setting names from EPG for ${channelIds.length} channels. Progress will be shown in notifications.`,
        color: 'blue',
      });

      // Close the modal since the task is now running in background
      onClose();
    } catch (error) {
      console.error('Failed to start EPG name setting task:', error);
      showNotification({
        title: 'Error',
        message: 'Failed to start EPG name setting task.',
        color: 'red',
      });
    } finally {
      setSettingNames(false);
      setConfirmSetNamesOpen(false);
    }
  };

  const handleSetLogosFromEpg = async () => {
    if (!channelIds || channelIds.length === 0) {
      showNotification({
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
    setSettingLogos(true);
    try {
      // Start the backend task
      await setChannelLogosFromEpg(channelIds);

      // The task will send WebSocket updates for progress
      // Just show that it started successfully
      showNotification({
        title: 'Task Started',
        message: `Started setting logos from EPG for ${channelIds.length} channels. Progress will be shown in notifications.`,
        color: 'blue',
      });

      // Close the modal since the task is now running in background
      onClose();
    } catch (error) {
      console.error('Failed to start EPG logo setting task:', error);
      showNotification({
        title: 'Error',
        message: 'Failed to start EPG logo setting task.',
        color: 'red',
      });
    } finally {
      setSettingLogos(false);
      setConfirmSetLogosOpen(false);
    }
  };

  const handleSetTvgIdsFromEpg = async () => {
    if (!channelIds || channelIds.length === 0) {
      showNotification({
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
    setSettingTvgIds(true);
    try {
      // Start the backend task
      await setChannelTvgIdsFromEpg(channelIds);

      // The task will send WebSocket updates for progress
      // Just show that it started successfully
      showNotification({
        title: 'Task Started',
        message: `Started setting TVG-IDs from EPG for ${channelIds.length} channels. Progress will be shown in notifications.`,
        color: 'blue',
      });

      // Close the modal since the task is now running in background
      onClose();
    } catch (error) {
      console.error('Failed to start EPG TVG-ID setting task:', error);
      showNotification({
        title: 'Error',
        message: 'Failed to start EPG TVG-ID setting task.',
        color: 'red',
      });
    } finally {
      setSettingTvgIds(false);
      setConfirmSetTvgIdsOpen(false);
    }
  };

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

  const LogoListItem = ({ item, onSelect }) => (
    <div
      style={{ cursor: 'pointer', padding: '5px', borderRadius: '4px' }}
      onClick={() => onSelect(item)}
      onMouseEnter={(e) => {
        e.currentTarget.style.backgroundColor = 'rgb(68, 68, 68)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.backgroundColor = 'transparent';
      }}
    >
      <Center style={{ flexDirection: 'column', gap: '2px' }}>
        {item.isDefault ? (
          <img
            src={logo}
            height="30"
            style={{ maxWidth: 80, objectFit: 'contain' }}
            alt="Default Logo"
          />
        ) : item.id > 0 ? (
          <img
            src={item.cache_url || logo}
            height="30"
            style={{ maxWidth: 80, objectFit: 'contain' }}
            alt={item.name || 'Logo'}
            onError={(e) => {
              if (e.target.src !== logo) e.target.src = logo;
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

  const LogoPickerList = ({ filteredLogos, listRef, onSelect }) => (
    <List
      height={200}
      itemCount={filteredLogos.length}
      itemSize={55}
      style={{ width: '100%' }}
      ref={listRef}
    >
      {({ index, style }) => (
        <div style={style}>
          <LogoListItem item={filteredLogos[index]} onSelect={onSelect} />
        </div>
      )}
    </List>
  );

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
                withArrow
              >
                <PopoverTarget>
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
                </PopoverTarget>

                <PopoverDropdown onMouseDown={(e) => e.stopPropagation()}>
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
                </PopoverDropdown>
              </Popover>

              <Group style={{ width: '100%' }} align="flex-end" gap="xs">
                <Popover
                  opened={logoPopoverOpened}
                  onChange={setLogoPopoverOpened}
                  withArrow
                >
                  <PopoverTarget>
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
                  </PopoverTarget>
                  <PopoverDropdown onMouseDown={(e) => e.stopPropagation()}>
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
                        <LogoPickerList
                          filteredLogos={filteredLogos}
                          listRef={logoListRef}
                          onSelect={(item) => {
                            setSelectedLogoId(item.id);
                            form.setValues({ logo: item.name });
                            setLogoPopoverOpened(false);
                          }}
                        />
                      )}
                    </ScrollArea>
                  </PopoverDropdown>
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

              <Select
                size="xs"
                label="Mature Content"
                {...form.getInputProps('is_adult')}
                key={form.key('is_adult')}
                data={[
                  { value: '-1', label: '(no change)' },
                  { value: 'true', label: 'Yes' },
                  { value: 'false', label: 'No' },
                ]}
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
        loading={settingNames}
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
        loading={settingLogos}
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
        loading={settingTvgIds}
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
        loading={isSubmitting}
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
  // Use only current page data from the channels table for preview
  const pageChannels = useChannelsTableStore((s) => s.channels);
  const nameById = useMemo(() => {
    const map = {};
    if (Array.isArray(pageChannels)) {
      for (const ch of pageChannels) {
        if (ch?.id != null) map[ch.id] = ch.name || '';
      }
    }
    return map;
  }, [pageChannels]);
  const previewItems = useMemo(
    () => computeRegexPreview(channelIds, nameById, find, replace),
    [channelIds, nameById, find, replace]
  );

  if (!find) return null;

  return (
    <Box mt={8}>
      <Text size="xs" c="dimmed" mb={4}>
        Preview shows matches from the current page only (up to 25).
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
