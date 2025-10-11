import React, { useEffect, useMemo, useState } from 'react';
import {
  Button,
  Group,
  Loader,
  Modal,
  NumberInput,
  Stack,
  Text,
  TextInput,
  Textarea,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { RefreshCcw } from 'lucide-react';
import { notifications } from '@mantine/notifications';

import API from '../../api';
import useMediaLibraryStore from '../../store/mediaLibrary';

const emptyValues = {
  title: '',
  synopsis: '',
  release_year: null,
  rating: '',
  genres: '',
  tags: '',
  studios: '',
  tmdb_id: '',
  imdb_id: '',
  poster_url: '',
  backdrop_url: '',
};

const listToString = (value) =>
  Array.isArray(value) && value.length > 0 ? value.join(', ') : '';

const toList = (value) =>
  typeof value === 'string'
    ? value
        .split(',')
        .map((entry) => entry.trim())
        .filter(Boolean)
    : Array.isArray(value)
      ? value
      : [];

const MediaEditModal = ({ opened, onClose, mediaItemId, onSaved }) => {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [applyingTmdb, setApplyingTmdb] = useState(false);
  const [mediaItem, setMediaItem] = useState(null);

  const form = useForm({
    initialValues: emptyValues,
  });

  const populateForm = (item) => {
    form.setValues({
      title: item.title || '',
      synopsis: item.synopsis || '',
      release_year: item.release_year || null,
      rating: item.rating || '',
      genres: listToString(item.genres),
      tags: listToString(item.tags),
      studios: listToString(item.studios),
      tmdb_id: item.tmdb_id || '',
      imdb_id: item.imdb_id || '',
      poster_url: item.poster_url || '',
      backdrop_url: item.backdrop_url || '',
    });
  };

  useEffect(() => {
    if (!opened || !mediaItemId) {
      setMediaItem(null);
      form.setValues(emptyValues);
      return;
    }

    setLoading(true);
    API.getMediaItem(mediaItemId)
      .then((item) => {
        setMediaItem(item);
        populateForm(item);
      })
      .catch((error) => {
        notifications.show({
          color: 'red',
          title: 'Failed to load media item',
          message: error.message || 'Unable to load media item details.',
        });
      })
      .finally(() => setLoading(false));
  }, [opened, mediaItemId]);

  const applyMediaItemUpdate = async (data) => {
    let normalized = data;
    if (!normalized || typeof normalized !== 'object') {
      try {
        normalized = await API.getMediaItem(mediaItemId);
      } catch (error) {
        notifications.show({
          color: 'red',
          title: 'Failed to refresh item',
          message: error.message || 'Unable to refresh media item after update.',
        });
        return false;
      }
    }

    setMediaItem(normalized);
    populateForm(normalized);

    try {
      await useMediaLibraryStore.getState().openItem(mediaItemId);
    } catch (error) {
      // Log but do not block success UX
      console.debug('Failed to refresh active item state', error);
    }

    if (typeof onSaved === 'function') {
      await onSaved(normalized);
    }

    return true;
  };

  const handleApplyTmdb = async () => {
    if (!form.values.tmdb_id) {
      notifications.show({
        color: 'yellow',
        title: 'TMDB ID required',
        message: 'Enter a TMDB ID before applying metadata.',
      });
      return;
    }

    setApplyingTmdb(true);
    try {
      const updated = await API.setMediaItemTMDB(
        mediaItemId,
        form.values.tmdb_id
      );
      const applied = await applyMediaItemUpdate(updated);
      if (applied) {
        notifications.show({
          color: 'green',
          title: 'Metadata updated',
          message: 'TMDB details applied successfully.',
        });
      }
    } catch (error) {
      // errorNotification already handled in API helper
    } finally {
      setApplyingTmdb(false);
    }
  };

  const handleSubmit = async (values) => {
    if (!mediaItem) return;

    const payload = {};

    const assignIfChanged = (field, value) => {
      const current = mediaItem[field];
      const normalizedValue = value ?? '';
      const normalizedCurrent = current ?? '';

      if (normalizedValue === '' && normalizedCurrent === '') {
        return;
      }

      if (normalizedValue === '' && normalizedCurrent !== '') {
        payload[field] = '';
        return;
      }

      if (normalizedValue !== normalizedCurrent) {
        payload[field] = value;
      }
    };

    assignIfChanged('title', values.title);
    assignIfChanged('synopsis', values.synopsis);
    if (values.release_year !== mediaItem.release_year) {
      payload.release_year = values.release_year || null;
    }
    assignIfChanged('rating', values.rating);
    const genresList = toList(values.genres);
    if (JSON.stringify(genresList) !== JSON.stringify(mediaItem.genres || [])) {
      payload.genres = genresList;
    }
    const tagsList = toList(values.tags);
    if (JSON.stringify(tagsList) !== JSON.stringify(mediaItem.tags || [])) {
      payload.tags = tagsList;
    }
    const studiosList = toList(values.studios);
    if (JSON.stringify(studiosList) !== JSON.stringify(mediaItem.studios || [])) {
      payload.studios = studiosList;
    }
    assignIfChanged('tmdb_id', values.tmdb_id);
    assignIfChanged('imdb_id', values.imdb_id);
    assignIfChanged('poster_url', values.poster_url);
    assignIfChanged('backdrop_url', values.backdrop_url);

    // Remove unchanged keys
    Object.keys(payload).forEach((key) => {
      const value = payload[key];
      if (
        value === undefined ||
        (Array.isArray(value) && value.length === 0 && !['genres', 'tags', 'studios'].includes(key))
      ) {
        delete payload[key];
      }
    });

    if (Object.keys(payload).length === 0) {
      notifications.show({
        color: 'blue',
        title: 'No changes detected',
        message: 'Update the fields before saving.',
      });
      return;
    }

    setSaving(true);
    try {
      const updated = await API.updateMediaItem(mediaItemId, payload);
      const applied = await applyMediaItemUpdate(updated);

      if (applied) {
        notifications.show({
          color: 'green',
          title: 'Media item saved',
          message: 'Changes were applied successfully.',
        });
        onClose();
      }
    } catch (error) {
      // errorNotification already displayed
    } finally {
      setSaving(false);
    }
  };

  const modalTitle = useMemo(() => {
    if (!mediaItem) return 'Edit Media';
    return `Edit ${mediaItem.title || 'Media'}`;
  }, [mediaItem]);

  return (
    <Modal opened={opened} onClose={onClose} title={modalTitle} size="lg" centered>
      {loading ? (
        <Group justify="center" py="xl">
          <Loader />
        </Group>
      ) : !mediaItem ? (
        <Text size="sm" c="dimmed">
          Unable to load media item details.
        </Text>
      ) : (
        <form onSubmit={form.onSubmit(handleSubmit)}>
          <Stack gap="md">
            <TextInput
              label="Title"
              placeholder="Movie title"
              {...form.getInputProps('title')}
            />
            <Textarea
              label="Synopsis"
              placeholder="Plot summary"
              minRows={3}
              {...form.getInputProps('synopsis')}
            />
            <Group grow>
              <NumberInput
                label="Release Year"
                min={1895}
                max={3000}
                {...form.getInputProps('release_year')}
              />
              <TextInput
                label="Rating"
                placeholder="PG-13"
                {...form.getInputProps('rating')}
              />
            </Group>
            <TextInput
              label="Genres"
              placeholder="Comma separated"
              {...form.getInputProps('genres')}
            />
            <TextInput
              label="Tags"
              placeholder="Comma separated"
              {...form.getInputProps('tags')}
            />
            <TextInput
              label="Studios"
              placeholder="Comma separated"
              {...form.getInputProps('studios')}
            />
            <Group grow align="end">
              <TextInput
                label="TMDB ID"
                placeholder="Enter TMDB ID"
                {...form.getInputProps('tmdb_id')}
              />
              <Button
                variant="light"
                leftSection={<RefreshCcw size={14} />}
                onClick={handleApplyTmdb}
                loading={applyingTmdb}
                type="button"
              >
                Apply TMDB Metadata
              </Button>
            </Group>
            <TextInput
              label="IMDB ID"
              placeholder="tt1234567"
              {...form.getInputProps('imdb_id')}
            />
            <TextInput
              label="Poster URL"
              placeholder="https://..."
              {...form.getInputProps('poster_url')}
            />
            <TextInput
              label="Backdrop URL"
              placeholder="https://..."
              {...form.getInputProps('backdrop_url')}
            />
            <Group justify="flex-end" mt="md">
              <Button variant="default" onClick={onClose} type="button">
                Cancel
              </Button>
              <Button type="submit" loading={saving}>
                Save Changes
              </Button>
            </Group>
          </Stack>
        </form>
      )}
    </Modal>
  );
};

export default MediaEditModal;
