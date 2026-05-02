import React, { useEffect, useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { yupResolver } from '@hookform/resolvers/yup';
import {
  Badge,
  Button,
  Flex,
  Grid,
  GridCol,
  Modal,
  NumberInput,
  Paper,
  SegmentedControl,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core';
import { TriangleAlert } from 'lucide-react';
import { DateTimePicker } from '@mantine/dates';
import { useWebSocket } from '../../WebSocket';
import {
  addM3UProfile,
  applyRegex,
  applyXcSimplePatterns,
  buildProfileSchema,
  buildSubmitValues,
  fetchFirstStreamUrl,
  getDetectedMode,
  prepareExpDate,
  updateM3UProfile,
  validateXcSimple,
} from '../../utils/forms/M3uProfileUtils.js';

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

  const getResolver = () => {
    return yupResolver(buildProfileSchema(isDefaultProfile, isXC));
  };

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
    resolver: getResolver(),
  });

  const onSubmit = async (values) => {
    const expDate = prepareExpDate(values.exp_date, isXC);

    if (isXC && xcMode === 'simple' && !isDefaultProfile) {
      const errs = validateXcSimple(newUsername, newPassword);
      if (Object.keys(errs).length > 0) { setSimpleErrors(errs); return; }
      setSimpleErrors({});
      values = applyXcSimplePatterns(values, m3u, newUsername, newPassword);
    }

    if (isXC && xcMode === 'advanced' && !isDefaultProfile) {
      if (!searchPattern.trim()) { setError('search_pattern', { message: 'Search pattern is required' }); return; }
      if (!replacePattern.trim()) { setError('replace_pattern', { message: 'Replace pattern is required' }); return; }
    }

    const submitValues = buildSubmitValues(values, profile, isDefaultProfile, isXC, xcMode);
    if (expDate !== undefined) submitValues.exp_date = expDate;

    profile?.id
      ? await updateM3UProfile(m3u, {...submitValues, id: profile.id})
      : await addM3UProfile(m3u, submitValues);

    reset();
    setSearchPattern('');
    setReplacePattern('');
    onClose();
  };

  useEffect(() => {
    if (!m3u?.id) return;

    fetchFirstStreamUrl(m3u.id)
      .then((url) => {
        if (url) {
          setStreamUrl(url);
          setSampleInput(url);
        }
      })
      .catch((error) => console.error('Error fetching stream URL:', error));
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
      const detectedMode = getDetectedMode(storedMode, profile, m3u);
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

  const getHighlightedSearchText = () =>
    applyRegex(
      sampleInput,
      searchPattern,
      (match) => `<mark style="background-color: #ffee58;">${match}</mark>`
    );

  const getLocalReplaceResult = () =>
    applyRegex(sampleInput, searchPattern, replacePattern);

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
            <GridCol span={12}>
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
            </GridCol>

            <GridCol span={12}>
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
            </GridCol>
          </Grid>
        </>
      )}
    </Modal>
  );
};

export default RegexFormAndView;
