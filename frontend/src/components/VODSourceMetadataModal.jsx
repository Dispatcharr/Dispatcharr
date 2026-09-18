import React, { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Group,
  Modal,
  Stack,
  Text,
  TextInput,
} from '@mantine/core';
import API from '../api';
import { normalizeLanguageCodes } from '../utils/languageCodes.js';
import { showNotification } from '../utils/notificationUtils';
import { VOD_METADATA_FIELDS } from '../utils/vodMetadataOptions.js';
import VODMetadataFields from './VODMetadataFields.jsx';
import { showVODProfileRebuildNotice } from '../utils/vodProfileUpdates.js';

const editableValues = (provider) => {
  const values = provider?.source_metadata?.values || {};
  return Object.fromEntries(
    Object.entries(values).filter(([field]) =>
      VOD_METADATA_FIELDS.includes(field)
    )
  );
};

const providerValue = (provider, ...keys) => {
  const properties = provider?.custom_properties || {};
  const candidates = [
    provider,
    properties,
    properties.detailed_info,
    properties.basic_data,
    properties.movie_data,
    properties.series_data,
  ].filter((value) => value && typeof value === 'object');
  for (const candidate of candidates) {
    for (const key of keys) {
      if (candidate[key]) return String(candidate[key]);
    }
  }
  return '';
};

const canonicalTmdbId = (provider, contentType) => {
  const canonical =
    contentType === 'series' ? provider?.series : provider?.movie;
  return String(
    provider?.tmdb_override_id ||
      canonical?.tmdb_match_id ||
      canonical?.tmdb_id ||
      ''
  );
};

const canonicalContent = (provider, contentType) =>
  contentType === 'series' ? provider?.series : provider?.movie;

const canonicalTitle = (provider, contentType) => {
  const canonical = canonicalContent(provider, contentType);
  return (
    canonical?.display_name ||
    canonical?.clean_title ||
    canonical?.name ||
    'Unknown canonical title'
  );
};

const VODSourceMetadataModal = ({
  provider,
  contentType,
  opened,
  onClose,
  onSaved,
  onMoved,
}) => {
  const [metadata, setMetadata] = useState({});
  const [targetSearch, setTargetSearch] = useState('');
  const [targetYear, setTargetYear] = useState('');
  const [localTargets, setLocalTargets] = useState([]);
  const [selectedTarget, setSelectedTarget] = useState(null);
  const [targetSearchComplete, setTargetSearchComplete] = useState(false);
  const [targetSearchError, setTargetSearchError] = useState('');
  const [searchingTargets, setSearchingTargets] = useState(false);
  const [confirmation, setConfirmation] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (opened && provider) {
      const canonical = canonicalContent(provider, contentType);
      setMetadata(editableValues(provider));
      setTargetSearch(
        canonical?.clean_title ||
          provider?.clean_title ||
          providerValue(provider, 'name', 'title') ||
          canonical?.display_name ||
          canonical?.name ||
          ''
      );
      setTargetYear(
        providerValue(
          provider,
          'year',
          'release_date',
          'releasedate',
          'releaseDate',
          'first_air_date'
        ).match(/(?:19|20)\d{2}/)?.[0] ||
          (canonical?.year ? String(canonical.year) : '')
      );
      setLocalTargets([]);
      setSelectedTarget(null);
      setTargetSearchComplete(false);
      setTargetSearchError('');
      setConfirmation(null);
    }
  }, [contentType, opened, provider]);

  const searchCanonicalTargets = async () => {
    const query = targetSearch.trim();
    if (!query) return;
    setSearchingTargets(true);
    setTargetSearchComplete(false);
    setTargetSearchError('');
    setSelectedTarget(null);
    try {
      const response = await API.searchVODCanonicalTargets(
        contentType,
        query,
        targetYear.trim()
      );
      setLocalTargets(response?.results || []);
      setTargetSearchComplete(true);
    } catch (error) {
      setTargetSearchError(
        error?.message || 'The local canonical library could not be searched.'
      );
    } finally {
      setSearchingTargets(false);
    }
  };

  const moveSource = async (confirmed = false) => {
    if (!selectedTarget) return null;
    try {
      return await API.updateVODRelationTmdbMatch(
        selectedTarget.payload,
        [{ content_type: contentType, relation_id: provider.id }],
        { confirmed }
      );
    } catch (error) {
      if (error?.status === 409 && error?.body?.requires_confirmation) {
        setConfirmation(error.body);
        return null;
      }
      throw error;
    }
  };

  const saveSourceMetadata = async () => {
    const normalized = Object.fromEntries(
      Object.entries(metadata).filter(
        ([, value]) =>
          value !== '' &&
          value !== null &&
          value !== undefined &&
          (!Array.isArray(value) || value.length > 0)
      )
    );
    if (normalized.audio_languages) {
      normalized.audio_languages = normalizeLanguageCodes(
        normalized.audio_languages
      );
    }
    if (normalized.subtitle_languages) {
      normalized.subtitle_languages = normalizeLanguageCodes(
        normalized.subtitle_languages
      );
    }
    const result = await API.updateVODRelationManualMetadata(
      contentType,
      provider.id,
      normalized,
      Object.keys(normalized)
    );
    onSaved?.({
      ...provider,
      source_metadata: result.source_metadata,
    });
    return result;
  };

  const save = async () => {
    setSaving(true);
    try {
      let moved = null;
      if (selectedTarget) {
        moved = await moveSource();
        if (!moved) return;
      }
      const metadataResult = await saveSourceMetadata();
      if (moved) onMoved?.(moved);
      showNotification({
        title: 'Source metadata saved',
        message: 'Manual values are locked against later observations.',
        color: 'green',
      });
      onClose();
      showVODProfileRebuildNotice(
        Number(moved?.profiles_affected || 0) >=
          Number(metadataResult?.profiles_affected || 0)
          ? moved
          : metadataResult
      );
    } catch (error) {
      showNotification({
        title: 'Source metadata could not be saved',
        message: error?.message || 'The request failed.',
        color: 'red',
      });
    } finally {
      setSaving(false);
    }
  };

  const confirmMove = async () => {
    setSaving(true);
    try {
      const moved = await moveSource(true);
      const metadataResult = await saveSourceMetadata();
      setConfirmation(null);
      onMoved?.(moved);
      showNotification({
        title: 'Provider source moved',
        message: 'The source now belongs to the selected canonical title.',
        color: 'green',
      });
      onClose();
      showVODProfileRebuildNotice(
        Number(moved?.profiles_affected || 0) >=
          Number(metadataResult?.profiles_affected || 0)
          ? moved
          : metadataResult
      );
    } catch (error) {
      showNotification({
        title: 'TMDB assignment could not be changed',
        message:
          error?.body?.tmdb_id || error?.message || 'The request failed.',
        color: 'red',
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title="Edit"
      size="70vw"
      centered
      styles={{ content: { maxWidth: 1000 } }}
    >
      <Stack>
        <Stack gap="xs">
          <Text fw={600}>Move to canonical title</Text>
          <Text size="xs" c="dimmed">
            Current: {canonicalTitle(provider, contentType)}
            {canonicalTmdbId(provider, contentType)
              ? ` · TMDB ${canonicalTmdbId(provider, contentType)}`
              : ''}
          </Text>
          <Group align="end" wrap="wrap">
            <TextInput
              label="Canonical title"
              value={targetSearch}
              onChange={(event) => {
                setTargetSearch(event.currentTarget.value);
                setLocalTargets([]);
                setTargetSearchComplete(false);
                setSelectedTarget(null);
              }}
              onKeyDown={(event) =>
                event.key === 'Enter' && searchCanonicalTargets()
              }
              style={{ flex: '1 1 320px', minWidth: 220 }}
            />
            <TextInput
              label="Year"
              value={targetYear}
              onChange={(event) => {
                setTargetYear(event.currentTarget.value);
                setLocalTargets([]);
                setTargetSearchComplete(false);
                setSelectedTarget(null);
              }}
              w={100}
            />
            <Button
              variant="default"
              loading={searchingTargets}
              disabled={!targetSearch.trim()}
              onClick={searchCanonicalTargets}
            >
              Search
            </Button>
          </Group>
          {targetSearchError && (
            <Alert color="orange">{targetSearchError}</Alert>
          )}
          {localTargets.map((target) => {
            const isCurrent =
              String(target.id) ===
              String(canonicalContent(provider, contentType)?.id || '');
            return (
              <Group key={`local-${target.id}`} justify="space-between">
                <Text size="sm">
                  {target.title}
                  {target.year ? ` (${target.year})` : ''} ·{' '}
                  {target.source_count} sources
                  {target.tmdb_id ? ` · TMDB ${target.tmdb_id}` : ''}
                </Text>
                <Button
                  size="xs"
                  variant={
                    selectedTarget?.key === `local-${target.id}`
                      ? 'filled'
                      : 'default'
                  }
                  disabled={isCurrent}
                  onClick={() =>
                    setSelectedTarget({
                      key: `local-${target.id}`,
                      label: target.title,
                      payload: { target_id: target.id },
                    })
                  }
                >
                  {isCurrent ? 'Current' : 'Use'}
                </Button>
              </Group>
            );
          })}
          {targetSearchComplete && localTargets.length === 0 && (
            <Text size="sm" c="dimmed">
              No matching canonical title exists in the local library.
            </Text>
          )}
          {targetSearchComplete && (
            <Alert color="blue" title="Create a new canonical title">
              <Group justify="space-between" align="center">
                <Text size="sm">
                  Create the new canonical entry from this source's provider
                  data. TMDB can be added afterwards from its detail view.
                </Text>
                <Button
                  size="xs"
                  variant={selectedTarget?.key === 'new' ? 'filled' : 'default'}
                  onClick={() =>
                    setSelectedTarget({
                      key: 'new',
                      label: `${providerValue(provider, 'name', 'title') || targetSearch.trim()}${targetYear.trim() ? ` (${targetYear.trim()})` : ''}`,
                      payload: { create_from_provider: true },
                    })
                  }
                >
                  Create from provider
                </Button>
              </Group>
            </Alert>
          )}
          {selectedTarget && (
            <Alert color="blue">
              This source will be moved to: {selectedTarget.label}
            </Alert>
          )}
        </Stack>
        <VODMetadataFields value={metadata} onChange={setMetadata} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={save} loading={saving}>
            {selectedTarget ? 'Move, save and lock' : 'Save and lock'}
          </Button>
        </Group>
      </Stack>
      <Modal
        opened={Boolean(confirmation)}
        onClose={() => setConfirmation(null)}
        title="Move a source with existing metadata?"
        centered
      >
        <Stack>
          <Alert color="orange">
            Metadata has already been stored for this title. Continuing moves
            this exact provider source to the new canonical title.
          </Alert>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirmation(null)}>
              Cancel
            </Button>
            <Button color="orange" loading={saving} onClick={confirmMove}>
              Move source
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Modal>
  );
};

export default VODSourceMetadataModal;
