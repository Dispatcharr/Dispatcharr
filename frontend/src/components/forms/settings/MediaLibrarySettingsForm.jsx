import React, { useEffect, useState } from 'react';
import {
  Alert,
  Anchor,
  Button,
  Group,
  List,
  Modal,
  PasswordInput,
  Stack,
  Switch,
  Text,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { ExternalLink } from 'lucide-react';

import API from '../../../api';

const MediaLibrarySettingsForm = React.memo(({ active }) => {
  const [settings, setSettings] = useState(null);
  const [apiKey, setApiKey] = useState('');
  const [clearApiKey, setClearApiKey] = useState(false);
  const [preferNfo, setPreferNfo] = useState(true);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [helpOpened, setHelpOpened] = useState(false);

  useEffect(() => {
    if (!active) {
      setSaved(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    API.getMediaLibrarySettings()
      .then((value) => {
        if (cancelled) return;
        setSettings(value);
        setPreferNfo(value.prefer_nfo !== false);
        setApiKey('');
        setClearApiKey(false);
      })
      .catch(() => {
        if (cancelled) return;
        notifications.show({
          title: 'Unable to load Media Library settings',
          message: 'The current settings could not be loaded.',
          color: 'red',
        });
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [active]);

  const save = async (event) => {
    event.preventDefault();
    setSaving(true);
    setSaved(false);
    try {
      const payload = { prefer_nfo: preferNfo };
      if (clearApiKey) {
        payload.clear_tmdb_api_key = true;
      } else if (apiKey.trim()) {
        payload.tmdb_api_key = apiKey.trim();
      }
      const updated = await API.updateMediaLibrarySettings(payload);
      setSettings(updated);
      setPreferNfo(updated.prefer_nfo !== false);
      setApiKey('');
      setClearApiKey(false);
      setSaved(true);
    } catch {
      notifications.show({
        title: 'Unable to save Media Library settings',
        message: 'Review the values and try again.',
        color: 'red',
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <form onSubmit={save}>
        <Stack>
          {saved && (
            <Alert variant="light" color="green" title="Saved Successfully" />
          )}
          <Alert color={settings?.tmdb_configured ? 'green' : 'yellow'}>
            TMDB metadata and artwork enrichment is{' '}
            {settings?.tmdb_configured ? 'configured' : 'not configured'}.
            {settings?.tmdb_source === 'environment' &&
              ' The key is supplied by the TMDB_API_KEY environment variable.'}
          </Alert>
          <PasswordInput
            label="TMDB API Key"
            description={
              settings?.tmdb_saved
                ? 'Enter a new key to replace the saved key, or leave this blank to preserve it.'
                : 'Required for optional TMDB metadata and artwork lookups.'
            }
            placeholder={settings?.tmdb_saved ? 'Saved key is hidden' : ''}
            value={apiKey}
            disabled={loading || clearApiKey}
            onChange={(event) => {
              setApiKey(event.currentTarget.value);
              if (event.currentTarget.value) setClearApiKey(false);
            }}
          />
          <Button
            variant="subtle"
            size="compact-sm"
            w="fit-content"
            onClick={() => setHelpOpened(true)}
          >
            Where do I get this?
          </Button>
          {settings?.tmdb_saved && (
            <Switch
              label="Explicitly clear the saved TMDB API key"
              description={
                settings.tmdb_environment
                  ? 'TMDB will remain enabled because TMDB_API_KEY is set in the environment.'
                  : 'A blank API key never clears the saved credential.'
              }
              checked={clearApiKey}
              disabled={loading}
              onChange={(event) => setClearApiKey(event.currentTarget.checked)}
            />
          )}
          <Switch
            label="Prefer NFO metadata"
            description="When enabled, local NFO metadata and artwork take priority and TMDB fills missing values. When disabled, TMDB values take priority and NFO data is used as a fallback."
            checked={preferNfo}
            disabled={loading}
            onChange={(event) => setPreferNfo(event.currentTarget.checked)}
          />
          <Group justify="end">
            <Button type="submit" loading={saving} disabled={loading}>
              Save
            </Button>
          </Group>
        </Stack>
      </form>

      <Modal
        opened={helpOpened}
        onClose={() => setHelpOpened(false)}
        title="How to get a TMDB API key"
        size="lg"
        centered
        overlayProps={{ backgroundOpacity: 0.55, blur: 2 }}
      >
        <Stack>
          <Text>
            Dispatcharr uses TMDB for optional artwork and metadata enrichment.
          </Text>
          <List type="ordered" spacing="sm">
            <List.Item>
              Visit{' '}
              <Anchor
                href="https://www.themoviedb.org"
                target="_blank"
                rel="noreferrer"
              >
                themoviedb.org <ExternalLink size={13} />
              </Anchor>{' '}
              and sign in or create an account.
            </List.Item>
            <List.Item>
              Open{' '}
              <Anchor
                href="https://www.themoviedb.org/settings/api"
                target="_blank"
                rel="noreferrer"
              >
                TMDB API settings <ExternalLink size={13} />
              </Anchor>{' '}
              and choose to create an API key.
            </List.Item>
            <List.Item>
              Complete the application and copy the API Key (v3 auth) into this
              setting.
            </List.Item>
          </List>
          <Alert color="blue">
            TMDB displays both v3 and v4 credentials. Dispatcharr needs the v3
            API key.
          </Alert>
          <Group justify="end">
            <Button onClick={() => setHelpOpened(false)}>Close</Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
});

MediaLibrarySettingsForm.displayName = 'MediaLibrarySettingsForm';

export default MediaLibrarySettingsForm;
