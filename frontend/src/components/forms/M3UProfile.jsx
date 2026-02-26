import React, { useState, useEffect, useMemo } from 'react';
import { useForm } from 'react-hook-form';
import { yupResolver } from '@hookform/resolvers/yup';
import * as Yup from 'yup';
import API from '../../api';
import {
  Flex,
  Modal,
  TextInput,
  Button,
  Title,
  Text,
  Paper,
  Badge,
  Grid,
  Textarea,
  NumberInput,
} from '@mantine/core';
import { useWebSocket } from '../../WebSocket';
import usePlaylistsStore from '../../store/playlists';

const RegexFormAndView = ({ profile = null, m3u, isOpen, onClose }) => {
  const [websocketReady, sendMessage] = useWebSocket();

  const profileSearchPreview = usePlaylistsStore((s) => s.profileSearchPreview);
  const profileResult = usePlaylistsStore((s) => s.profileResult);

  const [streamUrl, setStreamUrl] = useState('');
  const [searchPattern, setSearchPattern] = useState('');
  const [replacePattern, setReplacePattern] = useState('');
  const [debouncedPatterns, setDebouncedPatterns] = useState({});
  const [sampleInput, setSampleInput] = useState('');
  const isDefaultProfile = profile?.is_default;

  const defaultValues = useMemo(
    () => ({
      name: profile?.name || '',
      max_streams: profile?.max_streams || 0,
      search_pattern: profile?.search_pattern || '',
      replace_pattern: profile?.replace_pattern || '',
      notes: profile?.custom_properties?.notes || '',
    }),
    [profile]
  );

  const schema = Yup.object({
    name: Yup.string().required('Name is required'),
    search_pattern: Yup.string().when([], {
      is: () => !isDefaultProfile,
      then: (schema) => schema.required('Search pattern is required'),
      otherwise: (schema) => schema.notRequired(),
    }),
    replace_pattern: Yup.string().when([], {
      is: () => !isDefaultProfile,
      then: (schema) => schema.required('Replace pattern is required'),
      otherwise: (schema) => schema.notRequired(),
    }),
    notes: Yup.string(), // Optional field
  });

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    reset,
    setValue,
    watch,
  } = useForm({
    defaultValues,
    resolver: yupResolver(schema),
  });

  const onSubmit = async (values) => {
    console.log('submiting');

    // For default profiles, only send name and custom_properties (notes)
    let submitValues;
    if (isDefaultProfile) {
      submitValues = {
        name: values.name,
        custom_properties: {
          // Preserve existing custom_properties and add/update notes
          ...(profile?.custom_properties || {}),
          notes: values.notes || '',
        },
      };
    } else {
      // For regular profiles, send all fields
      submitValues = {
        name: values.name,
        max_streams: values.max_streams,
        search_pattern: values.search_pattern,
        replace_pattern: values.replace_pattern,
        custom_properties: {
          // Preserve existing custom_properties and add/update notes
          ...(profile?.custom_properties || {}),
          notes: values.notes || '',
        },
      };
    }

    if (profile?.id) {
      await API.updateM3UProfile(m3u.id, {
        id: profile.id,
        ...submitValues,
      });
    } else {
      await API.addM3UProfile(m3u.id, submitValues);
    }

    reset();
    // Reset local state to sync with form reset
    setSearchPattern('');
    setReplacePattern('');
    onClose();
  };

  useEffect(() => {
    async function fetchStreamUrl() {
      try {
        if (!m3u?.id) return;

        const params = new URLSearchParams();
        params.append('page', 1);
        params.append('page_size', 1);
        params.append('m3u_account', m3u.id);
        const response = await API.queryStreams(params);

        if (response?.results?.length > 0) {
          setStreamUrl(response.results[0].url);
          setSampleInput(response.results[0].url); // Initialize sample input with a real stream URL
        }
      } catch (error) {
        console.error('Error fetching stream URL:', error);
      }
    }
    fetchStreamUrl();
  }, [m3u]);

  useEffect(() => {
    if (!websocketReady || !streamUrl) return;

    try {
      sendMessage(
        JSON.stringify({
          type: 'm3u_profile_test',
          url: sampleInput || streamUrl, // Use sampleInput if provided, otherwise use streamUrl
          search: debouncedPatterns['search'] || '',
          replace: debouncedPatterns['replace'] || '',
        })
      );
    } catch (error) {
      console.error('Error sending WebSocket message:', error);
    }
  }, [websocketReady, m3u, debouncedPatterns, streamUrl, sampleInput]);

  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedPatterns({ search: searchPattern, replace: replacePattern });
    }, 500);

    return () => clearTimeout(handler); // Cleanup timeout on unmount or value change
  }, [searchPattern, replacePattern]);

  const onSearchPatternUpdate = (e) => {
    const value = e.target.value;
    setSearchPattern(value);
    setValue('search_pattern', value);
  };

  const onReplacePatternUpdate = (e) => {
    const value = e.target.value;
    setReplacePattern(value);
    setValue('replace_pattern', value);
  };

  useEffect(() => {
    reset(defaultValues);
    setSearchPattern(profile?.search_pattern || '');
    setReplacePattern(profile?.replace_pattern || '');
  }, [defaultValues, profile, reset]);

  const handleSampleInputChange = (e) => {
    setSampleInput(e.target.value);
  };

  // Local regex testing for immediate visual feedback
  const getHighlightedSearchText = () => {
    if (!searchPattern || !sampleInput) return sampleInput;
    try {
      const regex = new RegExp(searchPattern, 'g');
      return sampleInput.replace(
        regex,
        (match) => `<mark style="background-color: #ffee58;">${match}</mark>`
      );
    } catch {
      return sampleInput;
    }
  };

  const getLocalReplaceResult = () => {
    if (!searchPattern || !sampleInput) return sampleInput;
    try {
      const regex = new RegExp(searchPattern, 'g');
      return sampleInput.replace(regex, replacePattern);
    } catch {
      return sampleInput;
    }
  };

  return (
    <Modal
      opened={isOpen}
      onClose={onClose}
      title={
        isDefaultProfile
          ? 'Edit Default Profile (Name & Notes Only)'
          : 'M3U Profile'
      }
      size="lg"
    >
      <form onSubmit={handleSubmit(onSubmit)}>
        <TextInput
          label="Name"
          {...register('name')}
          error={errors.name?.message}
        />

        {/* Only show max streams field for non-default profiles */}
        {!isDefaultProfile && (
          <NumberInput
            label="Max Streams"
            {...register('max_streams')}
            value={watch('max_streams')}
            onChange={(value) => setValue('max_streams', value || 0)}
            error={errors.max_streams?.message}
            min={0}
            placeholder="0 = unlimited"
          />
        )}

        {/* Only show search/replace fields for non-default profiles */}
        {!isDefaultProfile && (
          <>
            <TextInput
              label="Search Pattern (Regex)"
              value={searchPattern}
              onChange={onSearchPatternUpdate}
              error={errors.search_pattern?.message}
            />
            <TextInput
              label="Replace Pattern"
              value={replacePattern}
              onChange={onReplacePatternUpdate}
              error={errors.replace_pattern?.message}
            />
          </>
        )}

        <Textarea
          label="Notes"
          placeholder="Add any notes or comments about this profile..."
          {...register('notes')}
          error={errors.notes?.message}
          minRows={2}
          maxRows={4}
          autosize
        />

        <Flex
          mih={50}
          gap="xs"
          justify="flex-end"
          align="flex-end"
          style={{ marginBottom: 5 }}
        >
          <Button
            type="submit"
            disabled={isSubmitting}
            size="xs"
            style={{ width: isSubmitting ? 'auto' : 'auto' }}
          >
            Submit
          </Button>
        </Flex>
      </form>

      {/* Only show regex demonstration for non-default profiles */}
      {!isDefaultProfile && (
        <>
          <Title order={4} mt={15} mb={10}>
            Live Regex Demonstration
          </Title>

          <Paper shadow="sm" p="xs" radius="md" withBorder mb={8}>
            <Text size="sm" weight={500} mb={3}>
              Sample Text
            </Text>
            <TextInput
              value={sampleInput}
              onChange={handleSampleInputChange}
              placeholder="Enter a sample URL to test with"
              size="sm"
            />
          </Paper>

          <Grid gutter="xs">
            <Grid.Col span={12}>
              <Paper shadow="sm" p="xs" radius="md" withBorder>
                <Text size="sm" weight={500} mb={3}>
                  Matched Text{' '}
                  <Badge size="xs" color="yellow">
                    highlighted
                  </Badge>
                </Text>
                <Text
                  size="sm"
                  dangerouslySetInnerHTML={{
                    __html: getHighlightedSearchText(),
                  }}
                  sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}
                />
              </Paper>
            </Grid.Col>

            <Grid.Col span={12}>
              <Paper shadow="sm" p="xs" radius="md" withBorder>
                <Text size="sm" weight={500} mb={3}>
                  Result After Replace
                </Text>
                <Text
                  size="sm"
                  sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}
                >
                  {getLocalReplaceResult()}
                </Text>
              </Paper>
            </Grid.Col>
          </Grid>
        </>
      )}
    </Modal>
  );
};

export default RegexFormAndView;
