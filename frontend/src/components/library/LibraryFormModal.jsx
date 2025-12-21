import React, { useEffect, useState } from 'react';
import {
  ActionIcon,
  Button,
  Checkbox,
  Loader,
  Group,
  Modal,
  NumberInput,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
  Textarea,
  ScrollArea,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { ArrowUp, FolderOpen, Plus, Trash2 } from 'lucide-react';
import API from '../../api';

const LIBRARY_TYPES = [
  { value: 'movies', label: 'Movies' },
  { value: 'shows', label: 'TV Shows' },
];

const defaultLocation = () => ({
  path: '',
  include_subdirectories: true,
  is_primary: false,
});

const LibraryFormModal = ({ opened, onClose, library, onSubmit, submitting }) => {
  const editing = Boolean(library);

  const form = useForm({
    mode: 'controlled',
    initialValues: {
      name: '',
      description: '',
      library_type: 'movies',
      metadata_language: 'en',
      metadata_country: 'US',
      scan_interval_minutes: 1440,
      auto_scan_enabled: true,
      add_to_vod: false,
      metadata_options: {},
      locations: [defaultLocation()],
    },
  });

  const [browser, setBrowser] = useState({
    open: false,
    index: null,
    path: '',
    parent: null,
    entries: [],
    loading: false,
    error: null,
  });

  useEffect(() => {
    if (library) {
      form.setValues({
        name: library.name || '',
        description: library.description || '',
        library_type:
          LIBRARY_TYPES.some((option) => option.value === library.library_type)
            ? library.library_type
            : 'movies',
        metadata_language: library.metadata_language || 'en',
        metadata_country: library.metadata_country || 'US',
        scan_interval_minutes: library.scan_interval_minutes || 1440,
        auto_scan_enabled: library.auto_scan_enabled ?? true,
        add_to_vod: library.add_to_vod ?? false,
        metadata_options: library.metadata_options || {},
        locations:
          library.locations?.length > 0
            ? library.locations.map((loc) => ({
                id: loc.id,
                path: loc.path,
                include_subdirectories:
                  loc.include_subdirectories ?? true,
                is_primary: loc.is_primary ?? false,
              }))
            : [defaultLocation()],
      });
    } else {
      form.reset();
      form.setFieldValue('locations', [defaultLocation()]);
    }
  }, [library, opened]);

  useEffect(() => {
    if (!opened) {
      closeBrowser();
    }
  }, [opened]);

  const addLocation = () => {
    form.insertListItem('locations', defaultLocation());
  };

  const removeLocation = (index) => {
    const values = form.getValues();
    if (values.locations.length === 1) {
      form.setFieldValue('locations', [defaultLocation()]);
      return;
    }
    form.removeListItem('locations', index);
  };

  const loadDirectory = async (targetPath) => {
    const normalizedPath = targetPath ?? '';
    setBrowser((prev) => ({ ...prev, loading: true, error: null }));
    try {
      const response = await API.browseLibraryPath(normalizedPath);
      setBrowser((prev) => ({
        ...prev,
        path: response.path ?? normalizedPath,
        parent: response.parent || null,
        entries: Array.isArray(response.entries) ? response.entries : [],
        loading: false,
      }));
    } catch (error) {
      console.error('Failed to browse directories', error);
      setBrowser((prev) => ({
        ...prev,
        loading: false,
        error: 'Unable to load directories. Check permissions and try again.',
      }));
    }
  };

  const openDirectoryBrowser = (index) => {
    const current = form.values.locations?.[index]?.path || '';
    setBrowser({
      open: true,
      index,
      path: current,
      parent: null,
      entries: [],
      loading: true,
      error: null,
    });
    void loadDirectory(current);
  };

  const closeBrowser = () => {
    setBrowser({
      open: false,
      index: null,
      path: '',
      parent: null,
      entries: [],
      loading: false,
      error: null,
    });
  };

  const handleSelectDirectory = (path) => {
    void loadDirectory(path ?? '');
  };

  const handleUseDirectory = () => {
    if (browser.index == null) {
      closeBrowser();
      return;
    }
    const resolvedPath = browser.path || '';
    form.setFieldValue(`locations.${browser.index}.path`, resolvedPath);
    closeBrowser();
  };

  const submit = (values) => {
    const payload = {
      ...values,
      locations: values.locations.map((loc, index) => ({
        ...loc,
        is_primary: loc.is_primary || index === 0,
      })),
    };
    onSubmit(payload);
  };

  return (
    <>
      <Modal
        opened={opened}
        onClose={onClose}
        title={editing ? 'Edit Library' : 'Create Library'}
        size="lg"
        overlayProps={{ backgroundOpacity: 0.6, blur: 4 }}
        zIndex={400}
      >
        <form onSubmit={form.onSubmit(submit)}>
        <Stack spacing="md">
          <TextInput
            label="Name"
            placeholder="My Movies"
            required
            {...form.getInputProps('name')}
          />

          <Textarea
            label="Description"
            placeholder="Optional description for this library"
            autosize
            minRows={2}
            {...form.getInputProps('description')}
          />

          <Group grow>
            <Select
              label="Library Type"
              data={LIBRARY_TYPES}
              comboboxProps={{ withinPortal: false }}
              {...form.getInputProps('library_type')}
            />
            <NumberInput
              label="Auto-scan Interval (minutes)"
              min={15}
              step={15}
              {...form.getInputProps('scan_interval_minutes')}
            />
          </Group>

          <Group grow>
            <TextInput
              label="Metadata Language"
              placeholder="en"
              {...form.getInputProps('metadata_language')}
            />
            <TextInput
              label="Metadata Country"
              placeholder="US"
              {...form.getInputProps('metadata_country')}
            />
          </Group>

          <Switch
            label="Enable automatic scanning"
            checked={form.values.auto_scan_enabled}
            onChange={(event) =>
              form.setFieldValue('auto_scan_enabled', event.currentTarget.checked)
            }
          />
          <Switch
            label="Expose this library in VOD"
            checked={form.values.add_to_vod}
            onChange={(event) =>
              form.setFieldValue('add_to_vod', event.currentTarget.checked)
            }
          />

          <Stack spacing="sm">
            <Group justify="space-between" align="center">
              <Text fw={600}>Locations</Text>
              <Button
                size="xs"
                leftSection={<Plus size={14} />}
                variant="light"
                onClick={addLocation}
                type="button"
              >
                Add Path
              </Button>
            </Group>

            {form.values.locations.map((location, index) => (
              <Stack
                key={location.id || index}
                p="sm"
                style={{
                  border: '1px solid rgba(148, 163, 184, 0.2)',
                  borderRadius: 8,
                }}
                spacing="xs"
              >
                <Group justify="space-between" align="center">
                  <Text size="sm" fw={500}>
                    Location {index + 1}
                  </Text>
                  <ActionIcon
                    size="sm"
                    color="red"
                    variant="subtle"
                    onClick={() => removeLocation(index)}
                  >
                    <Trash2 size={16} />
                  </ActionIcon>
                </Group>
                <Group align="flex-end" gap="sm">
                  <TextInput
                    placeholder="/path/to/library"
                    required
                    value={location.path}
                    onChange={(event) =>
                      form.setFieldValue(
                        `locations.${index}.path`,
                        event.currentTarget.value
                      )
                    }
                    style={{ flex: 1 }}
                  />
                  <Button
                    variant="light"
                    size="xs"
                    leftSection={<FolderOpen size={14} />}
                    onClick={() => openDirectoryBrowser(index)}
                    type="button"
                  >
                    Browse
                  </Button>
                </Group>
                <Group>
                  <Checkbox
                    label="Include subdirectories"
                    checked={location.include_subdirectories}
                    onChange={(event) =>
                      form.setFieldValue(
                        `locations.${index}.include_subdirectories`,
                        event.currentTarget.checked
                      )
                    }
                  />
                  <Checkbox
                    label="Primary"
                    checked={location.is_primary}
                    onChange={(event) =>
                      form.setFieldValue(
                        `locations.${index}.is_primary`,
                        event.currentTarget.checked
                      )
                    }
                  />
                </Group>
              </Stack>
            ))}
          </Stack>

          <Group justify="flex-end" mt="md">
            <Button variant="default" onClick={onClose} type="button">
              Cancel
            </Button>
            <Button type="submit" loading={submitting}>
              {editing ? 'Save changes' : 'Create library'}
            </Button>
          </Group>
        </Stack>
        </form>
      </Modal>
      <Modal
        opened={browser.open}
        onClose={closeBrowser}
        title="Select library directory"
        size="lg"
        overlayProps={{ backgroundOpacity: 0.6, blur: 4 }}
        zIndex={410}
      >
        <Stack spacing="md">
          <Group justify="space-between" align="center">
            <Text size="sm" c="dimmed">
              {browser.path || '/'}
            </Text>
            <Button
              size="xs"
              variant="light"
              leftSection={<ArrowUp size={14} />}
              onClick={() => handleSelectDirectory(browser.parent)}
              disabled={!browser.parent || browser.loading}
              type="button"
            >
              Up one level
            </Button>
          </Group>
          {browser.error && (
            <Text size="sm" c="red">
              {browser.error}
            </Text>
          )}
          <ScrollArea h={260} offsetScrollbars>
            {browser.loading ? (
              <Group justify="center" py="md">
                <Loader size="sm" />
              </Group>
            ) : browser.entries.length === 0 ? (
              <Text c="dimmed" size="sm">
                No subdirectories found.
              </Text>
            ) : (
              <Stack spacing="xs">
                {browser.entries.map((entry) => (
                  <Button
                    key={entry.path}
                    variant="subtle"
                    fullWidth
                    justify="space-between"
                    onClick={() => handleSelectDirectory(entry.path)}
                    type="button"
                  >
                    <span>{entry.name || entry.path}</span>
                    <Text size="xs" c="dimmed">
                      {entry.path}
                    </Text>
                  </Button>
                ))}
              </Stack>
            )}
          </ScrollArea>
          <Group justify="space-between">
            <Button
              variant="light"
              size="xs"
              onClick={() => void loadDirectory(browser.path)}
              loading={browser.loading}
              type="button"
            >
              Refresh
            </Button>
            <Group gap="sm">
              <Button variant="subtle" onClick={closeBrowser} type="button">
                Cancel
              </Button>
              <Button onClick={handleUseDirectory} type="button">
                Use this folder
              </Button>
            </Group>
          </Group>
        </Stack>
      </Modal>
    </>
  );
};

export default LibraryFormModal;
