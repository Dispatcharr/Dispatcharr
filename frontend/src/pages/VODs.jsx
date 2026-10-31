import React, { Suspense, useState } from 'react';
import { Navigate } from 'react-router-dom';
import {
  Box,
  Center,
  Group,
  SegmentedControl,
  Stack,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';
import { LayoutGrid, List } from 'lucide-react';
import useAuthStore from '../store/auth';
import useLibraryStore from '../store/useLibraryStore';
import ErrorBoundary from '../components/ErrorBoundary.jsx';
import { canViewVod } from '../utils/vodAccess';
import classes from '../components/VODLayout.module.css';

const LibraryView = React.lazy(() => import('../components/LibraryView.jsx'));

// Visible titles per type, independent of the current search and filters.
const totalsText = (totals) =>
  [
    ['movie', (count) => (count === 1 ? 'movie' : 'movies')],
    ['series', () => 'series'],
  ]
    .filter(([kind]) => Number.isInteger(totals?.[kind]))
    .map(
      ([kind, noun]) => `${totals[kind].toLocaleString()} ${noun(totals[kind])}`
    )
    .join(' · ');

export default function VODsPage() {
  const user = useAuthStore((state) => state.user);
  const admin = user?.user_level >= 10;
  const [view, setView] = useState('titles');
  const totalsLabel = totalsText(
    useLibraryStore((state) => state.options.totals)
  );
  const [displayMode, setDisplayMode] = useState(() =>
    localStorage.getItem('vodsViewMode') === 'list' ? 'list' : 'posters'
  );
  if (!canViewVod(user)) return <Navigate to="/channels" replace />;
  return (
    <Box p="md" id="vods-container" className={classes.library}>
      <Stack gap="md">
        <Group justify="space-between" gap="sm">
          <Group gap="sm" align="baseline">
            <Title order={2}>Library</Title>
            {totalsLabel && (
              <Text c="dimmed" size="sm" aria-label="Library titles">
                {totalsLabel}
              </Text>
            )}
          </Group>
          <Group gap="xs">
            {admin && (
              <SegmentedControl
                aria-label="Library content"
                styles={{
                  label: {
                    display: 'flex',
                    alignItems: 'center',
                    minHeight: 30,
                  },
                }}
                value={view}
                onChange={setView}
                data={[
                  { value: 'titles', label: 'Titles' },
                  { value: 'sources', label: 'Sources' },
                ]}
              />
            )}
            {(!admin || view === 'titles') && (
              <SegmentedControl
                aria-label="Library layout"
                styles={{
                  label: {
                    display: 'flex',
                    alignItems: 'center',
                    minHeight: 30,
                  },
                }}
                value={displayMode}
                onChange={(value) => {
                  setDisplayMode(value);
                  localStorage.setItem('vodsViewMode', value);
                }}
                data={[
                  {
                    value: 'list',
                    label: (
                      <Tooltip label="List">
                        <Center>
                          <List size={18} aria-label="List" />
                        </Center>
                      </Tooltip>
                    ),
                  },
                  {
                    value: 'posters',
                    label: (
                      <Tooltip label="Posters">
                        <Center>
                          <LayoutGrid size={18} aria-label="Posters" />
                        </Center>
                      </Tooltip>
                    ),
                  },
                ]}
              />
            )}
          </Group>
        </Group>
        <ErrorBoundary inline>
          <Suspense fallback={<Text role="status">Loading library…</Text>}>
            <LibraryView
              view={admin ? view : 'titles'}
              displayMode={admin && view === 'sources' ? 'list' : displayMode}
            />
          </Suspense>
        </ErrorBoundary>
      </Stack>
    </Box>
  );
}
