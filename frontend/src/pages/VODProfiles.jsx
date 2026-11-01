import React, {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from 'react';
import { Navigate } from 'react-router-dom';
import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  Flex,
  Group,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';
import { Plus, RefreshCw, SquarePen, Trash2 } from 'lucide-react';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import API from '../api';
import useAuthStore from '../store/auth';
import ErrorBoundary from '../components/ErrorBoundary.jsx';
import ConfirmationDialog from '../components/ConfirmationDialog.jsx';
import SourceStatus from '../components/SourceStatus.jsx';
import tableClasses from '../components/tables/M3UsTable.module.css';
import { formatApiError } from '../utils';
import {
  hideNotification,
  showNotification,
  updateNotification,
} from '../utils/notificationUtils.js';
import {
  CATALOG_STATUS,
  METADATA_SOURCES,
  buildDuration,
  OUTPUT_GROUPS,
  OUTPUT_MODES,
  categoryRows,
  countsText,
  exampleName,
  optionLabel,
  titleSourceLabel,
} from '../utils/vodProfiles';

dayjs.extend(relativeTime);

// Loaded on demand like the Library, so the Library styles it shares keep
// loading after Mantine's.
const VODProfileDialog = React.lazy(
  () => import('../components/forms/VODProfileDialog.jsx')
);

const busy = (profile) =>
  profile.is_active && ['pending', 'building'].includes(profile.catalog_status);

const catalogNotification = (profile) => {
  const running = busy(profile);
  const failed = profile.catalog_status === 'failed';
  const titles = profile.catalog_progress?.titles;
  return {
    id: `vod-profile-catalog-${profile.id}`,
    title: running
      ? `Preparing ${profile.name}`
      : failed
        ? `${profile.name} could not be prepared`
        : `${profile.name} is prepared`,
    message: running
      ? titles
        ? `${titles.toLocaleString()} titles prepared…`
        : 'Waiting for the worker…'
      : failed
        ? profile.catalog_error || 'Unknown error'
        : countsText(profile.catalog_counts) || 'No titles',
    color: running ? 'blue' : failed ? 'red' : 'green',
    loading: running,
    autoClose: running || failed ? false : 5000,
    withCloseButton: !running,
  };
};

// Followed outside the page so the notification survives navigation.
const followed = new Set();
const followCatalog = async (profile) => {
  if (!busy(profile) || followed.has(profile.id)) return;
  const id = `vod-profile-catalog-${profile.id}`;
  followed.add(profile.id);
  showNotification(catalogNotification(profile));
  try {
    let current = profile;
    while (current && busy(current)) {
      await new Promise((resolve) => setTimeout(resolve, 2000));
      current = (await API.getVODProfiles()).find(
        (item) => item.id === profile.id
      );
      if (current) updateNotification(id, catalogNotification(current));
    }
    if (!current) hideNotification(id);
  } catch {
    hideNotification(id);
  } finally {
    followed.delete(profile.id);
  }
};

function CatalogStatus({ profile }) {
  if (!profile.is_active) return <SourceStatus label="Disabled" color="gray" />;
  const status = CATALOG_STATUS[profile.catalog_status];
  return (
    <SourceStatus
      label={status?.label || profile.catalog_status}
      color={status?.color}
      messages={
        profile.catalog_status === 'failed' ? [profile.catalog_error] : []
      }
      messageColor="red"
    />
  );
}

function Detail({ label, children }) {
  return (
    <Box style={{ minWidth: 0 }}>
      <Text size="xs" fw={600} mb={4}>
        {label}
      </Text>
      {children}
    </Box>
  );
}

function ProfileCard({
  profile,
  categories,
  onToggle,
  onEdit,
  onRebuild,
  onDelete,
}) {
  const editions = profile.edition_rules;
  const rows = ['movie', 'series'].flatMap((scope) =>
    categoryRows(categories, profile, scope)
  );
  const titles = profile.catalog_progress?.titles;
  const duration = buildDuration(
    profile.catalog_started_at,
    profile.catalog_completed_at
  );
  return (
    <Paper
      component="article"
      aria-label={`${profile.name} profile`}
      className={tableClasses.card}
      withBorder
      p="md"
      radius="md"
      style={
        profile.is_active
          ? undefined
          : { opacity: 0.65, filter: 'grayscale(0.75)' }
      }
    >
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Box style={{ minWidth: 0, flex: '1 1 200px' }}>
            <Group gap="xs">
              <Text fw={700} size="lg" truncate className={tableClasses.name}>
                {profile.name}
              </Text>
              {profile.is_default && (
                <Badge variant="light" color="teal">
                  Default
                </Badge>
              )}
              <CatalogStatus profile={profile} />
            </Group>
          </Box>
          <Group gap="xs" align="stretch" wrap="nowrap">
            <Tooltip
              label={
                profile.is_default
                  ? 'The default profile is always enabled'
                  : 'Enable or disable this profile'
              }
              withArrow
              events={{ hover: true, focus: true, touch: true }}
            >
              <Paper
                className={tableClasses.controls}
                withBorder
                px={6}
                py={4}
                radius="md"
                role="group"
                aria-label={`Enabled state for ${profile.name}`}
              >
                <Switch
                  size="sm"
                  aria-label={`Enable ${profile.name}`}
                  checked={profile.is_active}
                  disabled={profile.is_default}
                  onChange={() => onToggle(profile)}
                />
              </Paper>
            </Tooltip>
            <Paper
              className={tableClasses.controls}
              withBorder
              px={6}
              py={4}
              radius="md"
              role="group"
              aria-label={`Actions for ${profile.name}`}
            >
              <Flex gap={4} align="center" wrap="nowrap">
                <Tooltip label="Prepare catalogue">
                  <ActionIcon
                    aria-label={`Prepare ${profile.name}`}
                    variant="subtle"
                    size="md"
                    color="blue.5"
                    disabled={!profile.is_active || busy(profile)}
                    onClick={() => onRebuild(profile)}
                  >
                    <RefreshCw size={17} />
                  </ActionIcon>
                </Tooltip>
                <Tooltip label="Edit profile">
                  <ActionIcon
                    aria-label={`Edit ${profile.name}`}
                    variant="subtle"
                    size="md"
                    color="yellow"
                    onClick={() => onEdit(profile)}
                  >
                    <SquarePen size={17} />
                  </ActionIcon>
                </Tooltip>
                <Tooltip
                  label={
                    profile.is_default
                      ? 'Make another profile the default first'
                      : 'Delete profile'
                  }
                >
                  <ActionIcon
                    aria-label={`Delete ${profile.name}`}
                    variant="subtle"
                    size="md"
                    color="red"
                    disabled={profile.is_default}
                    onClick={() => onDelete(profile)}
                  >
                    <Trash2 size={17} />
                  </ActionIcon>
                </Tooltip>
              </Flex>
            </Paper>
          </Group>
        </Group>
        <SimpleGrid cols={{ base: 1, xs: 2, lg: 3 }} spacing="md">
          <Detail label="Output">
            <Text size="sm" truncate>
              {optionLabel(OUTPUT_MODES, profile.output_mode)} ·{' '}
              {optionLabel(OUTPUT_GROUPS, profile.output_groups)} categories
            </Text>
            <Text size="xs" c="dimmed" truncate>
              Title: {titleSourceLabel(profile.title_source)} · Metadata:{' '}
              {optionLabel(METADATA_SOURCES, profile.metadata_source)}
            </Text>
            <Text size="xs" c="dimmed" truncate>
              Format: {profile.name_template}
            </Text>
            <Text size="xs" c="dimmed" truncate>
              Example: {exampleName(profile.name_template)}
            </Text>
            {editions.length > 0 && (
              <Text size="xs" c="dimmed" truncate>
                Editions: {editions.map((rule) => rule.title_suffix).join(', ')}
              </Text>
            )}
          </Detail>
          <Detail label="Categories">
            <Text size="sm">
              {rows.filter((row) => row.enabled).length.toLocaleString()} of{' '}
              {rows.length.toLocaleString()} enabled
            </Text>
          </Detail>
          <Detail label="Catalogue">
            {profile.catalog_status === 'building' && titles ? (
              <Text size="sm" truncate>
                {`${titles.toLocaleString()} titles prepared…`}
              </Text>
            ) : countsText(profile.catalog_counts) ? (
              <>
                <Text size="sm" truncate>
                  Entries: {countsText(profile.catalog_counts, 'entries')}
                </Text>
                <Text size="xs" c="dimmed" truncate>
                  Titles: {countsText(profile.catalog_counts)}
                </Text>
              </>
            ) : (
              <Text size="sm">Not prepared yet</Text>
            )}
            {profile.catalog_completed_at && (
              <Text size="xs" c="dimmed">
                {[
                  duration && `Built in ${duration}`,
                  dayjs(profile.catalog_completed_at).fromNow(),
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </Text>
            )}
          </Detail>
        </SimpleGrid>
      </Stack>
    </Paper>
  );
}

function PageContent() {
  const [profiles, setProfiles] = useState(null);
  const [options, setOptions] = useState(null);
  const [error, setError] = useState('');
  const [editing, setEditing] = useState(null);
  const [deleting, setDeleting] = useState(null);

  const load = useCallback(async () => {
    try {
      setProfiles(await API.getVODProfiles());
      setError('');
    } catch (err) {
      setError(formatApiError(err));
    }
  }, []);

  useEffect(() => {
    load();
    API.getVODProfileOptions()
      .then(setOptions)
      .catch((err) => setError(formatApiError(err)));
  }, [load]);

  // Keep the status badges current until every active profile is settled.
  const preparing = profiles?.some(busy);
  useEffect(() => {
    if (!preparing) return undefined;
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, [preparing, load]);

  const run = async (action, failure) => {
    try {
      followCatalog(await action());
      await load();
    } catch (err) {
      showNotification({
        title: failure,
        message: formatApiError(err),
        color: 'red',
      });
    }
  };

  const toggle = (profile) =>
    run(
      () => API.saveVODProfile({ is_active: !profile.is_active }, profile.id),
      `Could not update ${profile.name}`
    );

  const rebuild = (profile) =>
    run(
      () => API.rebuildVODProfile(profile.id),
      `Could not prepare ${profile.name}`
    );

  const remove = async () => {
    const profile = deleting;
    setDeleting(null);
    try {
      await API.deleteVODProfile(profile.id);
      showNotification({ title: `Deleted ${profile.name}`, color: 'green' });
      await load();
    } catch (err) {
      showNotification({
        title: 'Could not delete the profile',
        message: formatApiError(err),
        color: 'red',
      });
    }
  };

  const categories = useMemo(() => options?.categories || [], [options]);

  return (
    <Box p="md">
      <Stack gap="md">
        <Group justify="space-between" align="center">
          <Title order={2}>Profiles</Title>
          <Button
            leftSection={<Plus size={16} />}
            disabled={!options}
            onClick={() => setEditing({})}
          >
            Add profile
          </Button>
        </Group>
        {error && (
          <Alert color="red" title="Profiles could not be loaded">
            {error}
          </Alert>
        )}
        {!profiles && !error && (
          <Loader size="sm" aria-label="Loading profiles" />
        )}
        {profiles && (
          <Stack gap="md">
            {profiles.map((profile) => (
              <ProfileCard
                key={profile.id}
                profile={profile}
                categories={categories}
                onToggle={toggle}
                onEdit={setEditing}
                onRebuild={rebuild}
                onDelete={setDeleting}
              />
            ))}
          </Stack>
        )}
      </Stack>
      {editing && options && (
        <Suspense fallback={null}>
          <VODProfileDialog
            profile={editing}
            profiles={profiles || []}
            options={options}
            onClose={() => setEditing(null)}
            onSaved={(profile) => {
              setEditing(null);
              followCatalog(profile);
              load();
            }}
          />
        </Suspense>
      )}
      <ConfirmationDialog
        opened={!!deleting}
        onClose={() => setDeleting(null)}
        onConfirm={remove}
        title={`Delete ${deleting?.name || 'profile'}?`}
        message="Its users receive the default profile afterwards."
        confirmLabel="Delete"
        cancelLabel="Cancel"
      />
    </Box>
  );
}

export default function VODProfilesPage() {
  const user = useAuthStore((state) => state.user);
  if (user?.user_level < 10) return <Navigate to="/channels" replace />;
  return (
    <ErrorBoundary inline>
      <PageContent />
    </ErrorBoundary>
  );
}
