// Modal.js
import React, { useState, useEffect } from 'react';
import { useFormik } from 'formik';
import * as Yup from 'yup';
import API from '../../api';
import M3UProfiles from './M3UProfiles';
import {
  LoadingOverlay,
  TextInput,
  Button,
  Checkbox,
  Modal,
  Flex,
  NativeSelect,
  FileInput,
  Select,
  Space,
  Chip,
  Stack,
  Group,
  Center,
  SimpleGrid,
} from '@mantine/core';
import useChannelsStore from '../../store/channels';
import { CircleCheck, CircleX } from 'lucide-react';

const M3UGroupFilter = ({ playlist = null, isOpen, onClose }) => {
  const { channelGroups } = useChannelsStore();
  const [groupStates, setGroupStates] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [groupFilter, setGroupFilter] = useState('');

  useEffect(() => {
    console.log(playlist.channel_groups);
    setGroupStates(
      playlist.channel_groups.map((group) => ({
        ...group,
        name: channelGroups[group.channel_group].name,
      }))
    );
  }, [channelGroups]);

  const toggleGroupEnabled = (id) => {
    setGroupStates(
      groupStates.map((state) => ({
        ...state,
        enabled: state.channel_group == id ? !state.enabled : state.enabled,
      }))
    );
  };

  const submit = async () => {
    setIsLoading(true);
    await API.updatePlaylist({
      ...playlist,
      channel_groups: groupStates,
    });
    setIsLoading(false);

    onClose();
  };

  const selectAll = () => {
    setGroupStates(
      groupStates.map((state) => ({
        ...state,
        enabled: state.name.toLowerCase().includes(groupFilter.toLowerCase())
          ? true
          : state.enabled,
      }))
    );
  };

  const deselectAll = () => {
    setGroupStates(
      groupStates.map((state) => ({
        ...state,
        enabled: state.name.toLowerCase().includes(groupFilter.toLowerCase())
          ? false
          : state.enabled,
      }))
    );
  };

  if (!isOpen) {
    return <></>;
  }

  return (
    <Modal opened={isOpen} onClose={onClose} title="M3U Group Filter" size="xl">
      <LoadingOverlay visible={isLoading} overlayBlur={2} />
      <Stack>
        <Flex gap="sm">
          <TextInput
            placeholder="Filter"
            value={groupFilter}
            onChange={(event) => setGroupFilter(event.currentTarget.value)}
            style={{ flex: 1 }}
          />
          <Button variant="default" size="sm" onClick={selectAll}>
            Select Visible
          </Button>
          <Button variant="default" size="sm" onClick={deselectAll}>
            Deselect Visible
          </Button>
        </Flex>
        <SimpleGrid cols={4}>
          {groupStates
            .filter((group) =>
              group.name.toLowerCase().includes(groupFilter.toLowerCase())
            )
            .map((group) => (
              <Button
                color={group.enabled ? 'green' : 'gray'}
                variant="filled"
                checked={group.enabled}
                onClick={() => toggleGroupEnabled(group.channel_group)}
                radius="xl"
                leftSection={group.enabled ? <CircleCheck /> : <CircleX />}
                justify="left"
              >
                {group.name}
              </Button>
            ))}
        </SimpleGrid>

        <Flex mih={50} gap="xs" justify="flex-end" align="flex-end">
          <Button
            type="submit"
            variant="contained"
            color="primary"
            disabled={isLoading}
            size="small"
            onClick={submit}
          >
            Save and Refresh
          </Button>
        </Flex>
      </Stack>
    </Modal>
  );
};

export default M3UGroupFilter;
