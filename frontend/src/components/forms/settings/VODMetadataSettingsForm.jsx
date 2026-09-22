import React, { useLayoutEffect, useMemo, useState } from 'react';
import {
  Button,
  Group,
  Loader,
  PasswordInput,
  Select,
  Stack,
  Switch,
  Text,
} from '@mantine/core';
import API from '../../../api';
import { showNotification } from '../../../utils/notificationUtils';

const LANGUAGE_OPTIONS = [
  ['de-DE', 'German (de-DE)'],
  ['en-US', 'English (en-US)'],
  ['en-GB', 'English (en-GB)'],
  ['fr-FR', 'French (fr-FR)'],
  ['es-ES', 'Spanish (es-ES)'],
  ['it-IT', 'Italian (it-IT)'],
  ['nl-NL', 'Dutch (nl-NL)'],
  ['pl-PL', 'Polish (pl-PL)'],
  ['pt-PT', 'Portuguese (pt-PT)'],
  ['tr-TR', 'Turkish (tr-TR)'],
].map(([value, label]) => ({ value, label }));

const VODMetadataSettingsForm = ({
  status,
  loading = false,
  error = '',
  onSaved,
}) => {
  const [token, setToken] = useState('');
  const [primaryLanguage, setPrimaryLanguage] = useState('en-US');
  const [secondaryLanguage, setSecondaryLanguage] = useState('');
  const [autoEnrich, setAutoEnrich] = useState(true);
  const [matchMissing, setMatchMissing] = useState(false);
  const [preferArtwork, setPreferArtwork] = useState(true);
  const [saving, setSaving] = useState(false);

  useLayoutEffect(() => {
    if (!status) return;
    const settings = status.settings || {};
    const languages = settings.languages || ['en-US'];
    setPrimaryLanguage(languages[0] || 'en-US');
    setSecondaryLanguage(languages[1] || '');
    setAutoEnrich(settings.auto_enrich !== false);
    setMatchMissing(Boolean(settings.match_missing));
    setPreferArtwork(settings.prefer_artwork !== false);
  }, [status]);

  const languages = useMemo(
    () =>
      [primaryLanguage, secondaryLanguage].filter(
        (value, index, values) => value && values.indexOf(value) === index
      ),
    [primaryLanguage, secondaryLanguage]
  );

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        languages,
        auto_enrich: autoEnrich,
        match_missing: matchMissing,
        prefer_artwork: preferArtwork,
      };
      if (token.trim()) payload.api_token = token.trim();
      const next = await API.updateVODMetadataSettings(payload);
      onSaved?.(next);
      setToken('');
      showNotification({
        title: 'TMDB settings saved',
        message: 'The automatic enrichment settings were updated.',
        color: 'green',
      });
    } catch (error) {
      showNotification({
        title: 'TMDB settings were not saved',
        message:
          error?.body?.languages ||
          error?.body?.api_token ||
          error?.message ||
          'Please check the values and retry.',
        color: 'red',
      });
    } finally {
      setSaving(false);
    }
  };

  if (loading || (!status && !error)) {
    return (
      <Group justify="center" gap="xs" py="xl">
        <Loader size="sm" />
        <Text size="sm" c="dimmed">
          Loading TMDB settings
        </Text>
      </Group>
    );
  }

  if (!status) {
    return (
      <Text size="sm" c="red">
        {error || 'The TMDB settings could not be loaded.'}
      </Text>
    );
  }

  const environmentToken = status?.settings?.token_source === 'environment';
  return (
    <Stack maw={900}>
      <PasswordInput
        label="TMDB API read access token"
        description={
          environmentToken
            ? 'Configured through the container environment.'
            : status?.settings?.token_configured
              ? 'A token is configured. Enter a value only to replace it.'
              : 'Enter the application read access token from TMDB.'
        }
        value={token}
        onChange={(event) => setToken(event.currentTarget.value)}
        placeholder={status?.settings?.token_configured ? 'Configured' : ''}
        disabled={environmentToken}
      />

      <Group grow align="flex-start">
        <Select
          label="Primary metadata language"
          data={LANGUAGE_OPTIONS}
          value={primaryLanguage}
          onChange={(value) => setPrimaryLanguage(value || 'en-US')}
          searchable
          allowDeselect={false}
        />
        <Select
          label="Secondary metadata language"
          data={LANGUAGE_OPTIONS.filter(
            (option) => option.value !== primaryLanguage
          )}
          value={secondaryLanguage || null}
          onChange={(value) => setSecondaryLanguage(value || '')}
          searchable
          clearable
        />
      </Group>

      <Switch
        label="Automatically enrich after a changed provider VOD refresh"
        description="Only a changed provider catalog starts the incremental pipeline. Output profiles rebuild after enrichment."
        checked={autoEnrich}
        onChange={(event) => setAutoEnrich(event.currentTarget.checked)}
      />
      <Switch
        label="Match content without a TMDB or IMDb ID"
        description="Search uses the cleaned lookup title and release year. Only one exact result is accepted."
        checked={matchMissing}
        onChange={(event) => setMatchMissing(event.currentTarget.checked)}
      />
      <Switch
        label="Prefer TMDB posters and backdrops"
        description="Provider artwork remains stored and is used as fallback."
        checked={preferArtwork}
        onChange={(event) => setPreferArtwork(event.currentTarget.checked)}
      />

      <Button onClick={save} loading={saving} style={{ alignSelf: 'flex-end' }}>
        Save
      </Button>
    </Stack>
  );
};

export default VODMetadataSettingsForm;
