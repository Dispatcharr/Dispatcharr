import React, { useState, useEffect, useMemo } from 'react';
import { useForm } from 'react-hook-form';
import { yupResolver } from '@hookform/resolvers/yup';
import * as Yup from 'yup';
import API from '../../api';
import {
  Alert,
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
  SegmentedControl,
} from '@mantine/core';
import { TriangleAlert } from 'lucide-react';
import { DateTimePicker } from '@mantine/dates';
import { useWebSocket } from '../../WebSocket';

const RegexFormAndView = ({ profile = null, m3u, isOpen, onClose }) => {
  const [websocketReady, sendMessage] = useWebSocket();
  const [streamUrl, setStreamUrl] = useState('');
  const [searchPattern, setSearchPattern] = useState('');
  const [replacePattern, setReplacePattern] = useState('');
  const [debouncedPatterns, setDebouncedPatterns] = useState({});
  const [sampleInput, setSampleInput] = useState('');
  const [xcMode, setXcMode] = useState('simple');
  const [newUsername, setNewUsername] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [simpleErrors, setSimpleErrors] = useState({});
  const isDefaultProfile = profile?.is_default;

  const isXC = m3u?.account_type === 'XC';

  const defaultValues = useMemo(
    () => ({
      name: profile?.name || '',
      max_streams: profile?.max_streams || 0,
      search_pattern: profile?.search_pattern || '',
      replace_pattern: profile?.replace_pattern || '',
      notes: profile?.custom_properties?.notes || '',
      exp_date: profile?.exp_date ? new Date(profile.exp_date) : null,
    }),
    [profile]
  );

  const schema = Yup.object({
    name: Yup.string().required('Name is required'),
    search_pattern: Yup.string().when([], {
      is: () => !isDefaultProfile && !isXC,
      then: (schema) => schema.required('Search pattern is required'),
      otherwise: (schema) => schema.notRequired(),
    }),
    replace_pattern: Yup.string().when([], {
      is: () => !isDefaultProfile && !isXC,
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
    setError,
  } = useForm({
    defaultValues,
    resolver: yupResolver(schema),
  });

  const onSubmit = async (values) => {
    console.log('submiting');

    // Convert exp_date for submission
    let expDateValue = values.exp_date;
    if (isXC) {
      // XC accounts have exp_date auto-managed; don't send it
      expDateValue = undefined;
    } else if (expDateValue instanceof Date) {
      expDateValue = expDateValue.toISOString();
    } else if (!expDateValue) {
      expDateValue = null;
    }

    // For XC simple mode: validate simple inputs and build patterns from credentials
    if (isXC && xcMode === 'simple' && !isDefaultProfile) {
      const errs = {};
      if (!newUsername.trim()) errs.newUsername = 'New username is required';
      if (!newPassword.trim()) errs.newPassword = 'New password is required';
      if (Object.keys(errs).length > 0) {
        setSimpleErrors(errs);
        return;
      }
      setSimpleErrors({});
      values.search_pattern = `${m3u?.username || ''}/${m3u?.password || ''}`;
      values.replace_pattern = `${newUsername.trim()}/${newPassword.trim()}`;
    }

    // For XC advanced mode: validate regex pattern fields
    if (isXC && xcMode === 'advanced' && !isDefaultProfile) {
      if (!searchPattern.trim()) {
        setError('search_pattern', { message: 'Search pattern is required' });
        return;
      }
      if (!replacePattern.trim()) {
        setError('replace_pattern', { message: 'Replace pattern is required' });
        return;
      }
    }

    // Build submit values
    let submitValues;
    if (isDefaultProfile) {
      submitValues = {
        name: values.name,
        search_pattern: searchPattern || '',
        replace_pattern: replacePattern || '',
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
          ...(isXC ? { xcMode } : {}),
        },
      };
    }

    // Add exp_date for non-XC accounts
    if (expDateValue !== undefined) {
      submitValues.exp_date = expDateValue;
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
  }, [
    websocketReady,
    sendMessage,
    m3u,
    debouncedPatterns,
    streamUrl,
    sampleInput,
  ]);

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
    if (isXC && !isDefaultProfile) {
      const storedMode = profile?.custom_properties?.xcMode;
      let detectedMode;
      if (storedMode) {
        detectedMode = storedMode;
      } else if (
        profile?.search_pattern &&
        profile.search_pattern === `${m3u?.username}/${m3u?.password}`
      ) {
        detectedMode = 'simple';
      } else if (profile?.search_pattern) {
        detectedMode = 'advanced';
      } else {
        detectedMode = 'simple';
      }
      setXcMode(detectedMode);
      if (detectedMode === 'simple') {
        const rp = profile?.replace_pattern || '';
        const idx = rp.indexOf('/');
        setNewUsername(idx === -1 ? rp : rp.slice(0, idx));
        setNewPassword(idx === -1 ? '' : rp.slice(idx + 1));
      }
    }
  }, [
    defaultValues,
    isDefaultProfile,
    isXC,
    m3u?.password,
    m3u?.username,
    profile,
    reset,
  ]);

  const handleSampleInputChange = (e) => {
    setSampleInput(e.target.value);
  };

  const handleXcModeChange = (mode) => {
    if (mode === 'advanced' && xcMode === 'simple') {
      // Pre-populate regex fields from current simple values
      const sp = `${m3u?.username || ''}/${m3u?.password || ''}`;
      const rp = `${newUsername}/${newPassword}`;
      setSearchPattern(sp);
      setReplacePattern(rp);
      setValue('search_pattern', sp);
      setValue('replace_pattern', rp);
    } else if (mode === 'simple' && xcMode === 'advanced') {
      // Parse current replace pattern back into username/password
      const idx = replacePattern.indexOf('/');
      setNewUsername(
        idx === -1 ? replacePattern : replacePattern.slice(0, idx)
      );
      setNewPassword(idx === -1 ? '' : replacePattern.slice(idx + 1));
    }
    setXcMode(mode);
  };

  // Local regex for the live demo preview. Returns an array of strings and
  // <mark> React nodes so user-supplied text is never interpolated into raw
  // HTML (avoids self-XSS via dangerouslySetInnerHTML).
  const getHighlightedSearchText = () => {
    if (!searchPattern || !sampleInput) return sampleInput;
    try {
      const regex = new RegExp(searchPattern, 'g');
      const parts = [];
      let lastIndex = 0;
      let m;
      while ((m = regex.exec(sampleInput)) !== null) {
        if (m.index > lastIndex) {
          parts.push(sampleInput.slice(lastIndex, m.index));
        }
        parts.push(
          <mark
            key={`${m.index}-${parts.length}`}
            style={{ backgroundColor: '#ffee58' }}
          >
            {m[0]}
          </mark>
        );
        lastIndex = m.index + m[0].length;
        if (m[0].length === 0) regex.lastIndex++;
      }
      if (lastIndex < sampleInput.length) {
        parts.push(sampleInput.slice(lastIndex));
      }
      return parts;
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
      title={isDefaultProfile ? 'Edit Default Profile' : 'M3U Profile'}
      size="lg"
    >
      <form onSubmit={handleSubmit(onSubmit)}>
        <TextInput
          label="Name"
          description="A label to identify this URL rewrite profile"
          placeholder="e.g. Provider A - 2nd Connection"
          {...register('name')}
          error={errors.name?.message}
        />

        {/* Only show max streams field for non-default profiles */}
        {!isDefaultProfile && (
          <NumberInput
            label="Max Streams"
            description="Maximum concurrent streams allowed for this profile. Set to 0 for unlimited."
            {...register('max_streams')}
            value={watch('max_streams')}
            onChange={(value) => setValue('max_streams', value || 0)}
            error={errors.max_streams?.message}
            min={0}
            placeholder="0 = unlimited"
          />
        )}

        {/* Search/replace fields */}
        {isDefaultProfile ? (
          <>
            <Alert
              icon={<TriangleAlert size={16} />}
              color="yellow"
              title="Default Profile"
              mt="xs"
            >
              <Text size="sm">
                These patterns are applied to every stream in this playlist. If
                the search pattern doesn&apos;t match a stream URL, the original
                URL is used as-is.
              </Text>
            </Alert>
            <TextInput
              label="Search Pattern (Regex)"
              description="A regular expression matching the part of the stream URL you want to replace."
              placeholder="e.g. 10\.0\.0\.10"
              value={searchPattern}
              onChange={onSearchPatternUpdate}
              error={errors.search_pattern?.message}
            />
            <TextInput
              label="Replace Pattern"
              description="The value to substitute in place of the matched text. Use $1, $2, etc. to reference regex capture groups."
              placeholder="e.g. 192.168.1.100"
              value={replacePattern}
              onChange={onReplacePatternUpdate}
              error={errors.replace_pattern?.message}
            />
          </>
        ) : (
          <>
            {isXC && (
              <SegmentedControl
                mt="xs"
                mb="xs"
                fullWidth
                size="xs"
                value={xcMode}
                onChange={handleXcModeChange}
                data={[
                  { label: 'Simple', value: 'simple' },
                  { label: 'Advanced (Regex)', value: 'advanced' },
                ]}
              />
            )}
            {isXC && xcMode === 'simple' ? (
              <>
                <TextInput
                  label="New Username"
                  description="Your updated XC account username. The current username in all stream URLs will be replaced with this."
                  placeholder="e.g. username2"
                  value={newUsername}
                  onChange={(e) => {
                    setNewUsername(e.target.value);
                    setSimpleErrors((s) => ({ ...s, newUsername: undefined }));
                  }}
                  error={simpleErrors.newUsername}
                />
                <TextInput
                  label="New Password"
                  description="Your updated XC account password. The current password in all stream URLs will be replaced with this."
                  placeholder="e.g. password2"
                  value={newPassword}
                  onChange={(e) => {
                    setNewPassword(e.target.value);
                    setSimpleErrors((s) => ({ ...s, newPassword: undefined }));
                  }}
                  error={simpleErrors.newPassword}
                />
              </>
            ) : (
              <>
                <TextInput
                  label="Search Pattern (Regex)"
                  description="A regular expression matching the part of the stream URL you want to replace. For most users, matching just the credentials is enough."
                  placeholder="e.g. username1/password1"
                  value={searchPattern}
                  onChange={onSearchPatternUpdate}
                  error={errors.search_pattern?.message}
                />
                <TextInput
                  label="Replace Pattern"
                  description="The value to substitute in place of the matched text. Use $1, $2, etc. to reference regex capture groups."
                  placeholder="e.g. username2/password2"
                  value={replacePattern}
                  onChange={onReplacePatternUpdate}
                  error={errors.replace_pattern?.message}
                />
              </>
            )}
          </>
        )}

        {!isXC && (
          <DateTimePicker
            label="Expiration Date"
            description="Set an expiration date to receive a 7-day warning notification"
            placeholder="No expiration"
            clearable
            valueFormat="MMM D, YYYY h:mm A"
            value={watch('exp_date')}
            onChange={(value) => setValue('exp_date', value)}
          />
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
          justify="space-between"
          align="flex-end"
          style={{ marginBottom: 5 }}
        >
          {isDefaultProfile && (
            <Button
              variant="subtle"
              color="gray"
              size="xs"
              onClick={() => {
                setSearchPattern('^(.*)$');
                setReplacePattern('$1');
                setValue('search_pattern', '^(.*)$');
                setValue('replace_pattern', '$1');
              }}
            >
              Reset to Defaults
            </Button>
          )}
          <Button
            type="submit"
            disabled={isSubmitting}
            size="xs"
            style={{ marginLeft: isDefaultProfile ? undefined : 'auto' }}
          >
            Submit
          </Button>
        </Flex>
      </form>

      {/* Show regex demonstration for default profiles and non-default profiles in advanced mode */}
      {(isDefaultProfile || !isXC || xcMode === 'advanced') && (
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
                <Text size="sm" weight={500} mb={3} component="div">
                  Matched Text{' '}
                  <Badge size="xs" color="yellow">
                    highlighted
                  </Badge>
                </Text>
                <Text
                  size="sm"
                  sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}
                >
                  {getHighlightedSearchText()}
                </Text>
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
