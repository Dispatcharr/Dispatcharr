import React, { useEffect, useState } from 'react';
import {
  Box,
  Alert,
  Button,
  Divider,
  Group,
  Image,
  Modal,
  ScrollArea,
  SimpleGrid,
  Stack,
  Switch,
  TagsInput,
  Text,
  Textarea,
  TextInput,
} from '@mantine/core';
import { ExternalLink, Search, Save } from 'lucide-react';
import API from '../api';
import { showNotification } from '../utils/notificationUtils';
import { showVODProfileRebuildNotice } from '../utils/vodProfileUpdates.js';
import {
  canonicalMetadataValues,
  EMPTY_CANONICAL_METADATA_VALUES,
} from '../utils/vodCanonicalMetadata.js';

const VODCanonicalMetadataModal = ({
  opened,
  onClose,
  content,
  contentId,
  contentType,
  onSaved,
}) => {
  const [values, setValues] = useState(EMPTY_CANONICAL_METADATA_VALUES);
  const [searchTitle, setSearchTitle] = useState('');
  const [searchYear, setSearchYear] = useState('');
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [loadingCandidate, setLoadingCandidate] = useState('');
  const [saving, setSaving] = useState(false);
  const [searched, setSearched] = useState(false);

  const primaryLanguage =
    content?.tmdb?.primary_language || content?.tmdb?.languages?.[0] || '';
  const secondaryLanguage =
    content?.tmdb?.secondary_language || content?.tmdb?.languages?.[1] || '';

  useEffect(() => {
    if (!opened) return;
    const next = canonicalMetadataValues(content);
    setValues(next);
    setSearchTitle(next.clean_title || next.title);
    setSearchYear(next.year);
    setResults([]);
    setSearched(false);
  }, [content, opened]);

  const setValue = (key, value) =>
    setValues((current) => ({ ...current, [key]: value }));

  const searchTMDB = async () => {
    if (!searchTitle.trim()) return;
    setSearching(true);
    setSearched(false);
    setResults([]);
    try {
      const response = await API.lookupVODTMDB({
        content_type: contentType,
        query: searchTitle.trim(),
        year: searchYear,
      });
      setResults(response.results || []);
      setSearched(true);
    } catch (error) {
      showNotification({
        title: 'TMDB search failed',
        message: error?.body?.detail || error?.message || 'Please retry.',
        color: 'red',
      });
    } finally {
      setSearching(false);
    }
  };

  const loadCandidate = async (candidateId) => {
    setLoadingCandidate(String(candidateId));
    try {
      const response = await API.lookupVODTMDB({
        content_type: contentType,
        tmdb_id: candidateId,
      });
      const candidateValues = canonicalMetadataValues({
        tmdb: response.metadata,
      });
      setValues({
        ...candidateValues,
        tmdb_id: String(candidateId),
        clean_title: candidateValues.title,
      });
    } catch (error) {
      showNotification({
        title: 'TMDB preview failed',
        message: error?.body?.detail || error?.message || 'Please retry.',
        color: 'red',
      });
    } finally {
      setLoadingCandidate('');
    }
  };

  const save = async () => {
    if (!values.title.trim()) return;
    setSaving(true);
    try {
      const response = await API.updateCanonicalVODMetadata(
        contentType,
        contentId,
        values
      );
      await onSaved?.(response);
      showNotification({
        title: 'Canonical metadata saved',
        message:
          'Affected output profiles can now be rebuilt explicitly from their profile dialog.',
        color: 'green',
      });
      onClose();
      showVODProfileRebuildNotice(response);
    } catch (error) {
      showNotification({
        title: 'Metadata was not saved',
        message:
          error?.body?.detail ||
          Object.values(error?.body || {})?.[0] ||
          error?.message ||
          'Please retry.',
        color: 'red',
      });
    } finally {
      setSaving(false);
    }
  };

  const candidateRows = results.map((candidate) => (
    <Group
      key={candidate.id}
      wrap="nowrap"
      align="flex-start"
      p="xs"
      style={{
        border: '1px solid var(--mantine-color-dark-4)',
        borderRadius: 6,
      }}
    >
      {candidate.poster_url ? (
        <Image src={candidate.poster_url} w={48} h={72} fit="cover" bdrs={4} />
      ) : (
        <Box w={48} h={72} bg="dark.6" style={{ flexShrink: 0 }} />
      )}
      <Box style={{ flex: 1 }}>
        <Text fw={600}>
          {candidate.title ||
            candidate.original_title ||
            `TMDB ${candidate.id}`}
          {candidate.year ? ` (${candidate.year})` : ''}
        </Text>
        {candidate.original_title &&
          candidate.original_title !== candidate.title && (
            <Text size="xs" c="dimmed">
              Original: {candidate.original_title}
            </Text>
          )}
        <Text size="xs" c="dimmed" lineClamp={2}>
          {candidate.overview || 'No description returned.'}
        </Text>
      </Box>
      <Button
        size="xs"
        variant="default"
        loading={loadingCandidate === String(candidate.id)}
        onClick={() => loadCandidate(candidate.id)}
      >
        Load
      </Button>
      <Button
        component="a"
        size="xs"
        variant="subtle"
        leftSection={<ExternalLink size={14} />}
        href={`https://www.themoviedb.org/${contentType === 'series' ? 'tv' : 'movie'}/${candidate.id}`}
        target="_blank"
        rel="noreferrer"
      >
        TMDB
      </Button>
    </Group>
  ));

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title="Edit canonical metadata"
      size="70vw"
      centered
      styles={{ content: { maxWidth: 1150 } }}
    >
      <Stack gap="md">
        <Box
          p="sm"
          style={{
            border: '1px solid var(--mantine-color-dark-4)',
            borderRadius: 6,
          }}
        >
          <Stack gap="xs">
            <Text fw={600}>Find the correct TMDB title</Text>
            <Group align="end" wrap="wrap">
              <TextInput
                label="Search title"
                value={searchTitle}
                onChange={(event) => setSearchTitle(event.currentTarget.value)}
                onKeyDown={(event) => event.key === 'Enter' && searchTMDB()}
                style={{ flex: '1 1 320px', minWidth: 220 }}
              />
              <TextInput
                label="Year"
                value={searchYear}
                onChange={(event) => setSearchYear(event.currentTarget.value)}
                w={100}
              />
              <Button
                leftSection={<Search size={15} />}
                loading={searching}
                onClick={searchTMDB}
              >
                Search TMDB
              </Button>
            </Group>
            {searched && !searching && results.length === 0 && (
              <Alert color="red" title="No TMDB match">
                Adjust the cleanup title or year and search again.
              </Alert>
            )}
            {searched && !searching && results.length > 1 && (
              <Alert color="yellow" title="Multiple TMDB matches">
                Review the candidates and load the correct title.
              </Alert>
            )}
            {searched && !searching && results.length === 1 && (
              <Alert color="green" title="One TMDB match found">
                Load the result to review its metadata before saving.
              </Alert>
            )}
            {results.length > 0 && (
              <ScrollArea h={220} offsetScrollbars>
                <Stack gap="xs">{candidateRows}</Stack>
              </ScrollArea>
            )}
            {!searched && !searching && results.length === 0 && (
              <Text size="xs" c="dimmed">
                Search results are only a preview. Nothing changes until you
                save.
              </Text>
            )}
          </Stack>
        </Box>

        <Divider label="Canonical values" labelPosition="left" />
        <TextInput
          label="Cleanup title"
          description="Stored lookup title used before the provider title."
          value={values.clean_title}
          onChange={(event) =>
            setValue('clean_title', event.currentTarget.value)
          }
        />
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <TextInput
            label={`Primary title${primaryLanguage ? ` · ${primaryLanguage}` : ''}`}
            required
            value={values.title}
            onChange={(event) => setValue('title', event.currentTarget.value)}
          />
          {secondaryLanguage && (
            <TextInput
              label={`Secondary title · ${secondaryLanguage}`}
              value={values.secondary_title}
              onChange={(event) =>
                setValue('secondary_title', event.currentTarget.value)
              }
            />
          )}
          <Textarea
            label={`Primary description${primaryLanguage ? ` · ${primaryLanguage}` : ''}`}
            autosize
            minRows={3}
            value={values.description}
            onChange={(event) =>
              setValue('description', event.currentTarget.value)
            }
          />
          {secondaryLanguage && (
            <Textarea
              label={`Secondary description · ${secondaryLanguage}`}
              autosize
              minRows={3}
              value={values.secondary_description}
              onChange={(event) =>
                setValue('secondary_description', event.currentTarget.value)
              }
            />
          )}
        </SimpleGrid>

        <SimpleGrid cols={{ base: 2, sm: 4 }}>
          <TextInput
            label="Year"
            value={values.year}
            onChange={(event) => setValue('year', event.currentTarget.value)}
          />
          <TextInput
            label="Release date"
            placeholder="YYYY-MM-DD"
            value={values.release_date}
            onChange={(event) =>
              setValue('release_date', event.currentTarget.value)
            }
          />
          {contentType === 'movie' && (
            <TextInput
              label="Runtime · minutes"
              value={values.duration_minutes}
              onChange={(event) =>
                setValue('duration_minutes', event.currentTarget.value)
              }
            />
          )}
          <TextInput
            label="Rating"
            value={values.rating}
            onChange={(event) => setValue('rating', event.currentTarget.value)}
          />
          <TextInput
            label="Age rating"
            value={values.age_rating}
            onChange={(event) =>
              setValue('age_rating', event.currentTarget.value)
            }
          />
        </SimpleGrid>

        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <TextInput
            label="Genres · comma separated"
            value={values.genre}
            onChange={(event) => setValue('genre', event.currentTarget.value)}
          />
          <TextInput
            label="Country"
            value={values.country}
            onChange={(event) => setValue('country', event.currentTarget.value)}
          />
          <TextInput
            label="Director / creator"
            value={values.director}
            onChange={(event) =>
              setValue('director', event.currentTarget.value)
            }
          />
          <TextInput
            label="Cast · comma separated"
            value={values.actors}
            onChange={(event) => setValue('actors', event.currentTarget.value)}
          />
          <TextInput
            label="Crew · comma separated"
            value={values.crew}
            onChange={(event) => setValue('crew', event.currentTarget.value)}
          />
          <TextInput
            label="YouTube trailer ID or URL"
            value={values.youtube_trailer}
            onChange={(event) =>
              setValue('youtube_trailer', event.currentTarget.value)
            }
          />
          <TextInput
            label="Poster URL"
            value={values.poster_url}
            onChange={(event) =>
              setValue('poster_url', event.currentTarget.value)
            }
          />
          <TextInput
            label="Backdrop URL"
            value={values.backdrop_url}
            onChange={(event) =>
              setValue('backdrop_url', event.currentTarget.value)
            }
          />
        </SimpleGrid>

        <SimpleGrid cols={{ base: 2, sm: 4 }}>
          <TextInput
            label="TMDB ID"
            value={values.tmdb_id}
            onChange={(event) => setValue('tmdb_id', event.currentTarget.value)}
          />
          <TextInput
            label="IMDb ID"
            value={values.imdb_id}
            onChange={(event) => setValue('imdb_id', event.currentTarget.value)}
          />
          <TextInput
            label="TVDB ID"
            value={values.tvdb_id}
            onChange={(event) => setValue('tvdb_id', event.currentTarget.value)}
          />
          <TextInput
            label="Wikidata ID"
            value={values.wikidata_id}
            onChange={(event) =>
              setValue('wikidata_id', event.currentTarget.value)
            }
          />
        </SimpleGrid>

        <TagsInput
          label="Keywords"
          description="TMDB keywords are stored individually and can be adjusted here."
          value={values.keywords}
          onChange={(value) => setValue('keywords', value)}
          splitChars={[',']}
          clearable
        />
        <Group>
          <Switch
            checked={values.is_anime}
            onChange={(event) =>
              setValue('is_anime', event.currentTarget.checked)
            }
            label="Anime"
          />
          <Switch
            checked={values.adult}
            onChange={(event) => setValue('adult', event.currentTarget.checked)}
            label="Adult content"
          />
        </Group>

        <Group justify="flex-end">
          <Button variant="default" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button
            leftSection={<Save size={15} />}
            loading={saving}
            disabled={!values.title.trim()}
            onClick={save}
          >
            Save metadata
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default VODCanonicalMetadataModal;
