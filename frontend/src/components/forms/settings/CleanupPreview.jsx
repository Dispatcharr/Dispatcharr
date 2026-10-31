import { useEffect, useRef, useState } from 'react';
import { Button, Group, Paper, Stack, Text, TextInput } from '@mantine/core';
import { Eye } from 'lucide-react';
import api from '../../../api';
import { notifyLibraryError } from '../../../utils/libraryFeedback.js';
import classes from '../../LibraryWorkspace.module.css';
import ListPagination from '../../ListPagination.jsx';
import CleanupPreviewTable from '../../CleanupPreviewTable.jsx';
import ErrorBoundary from '../../ErrorBoundary.jsx';
import LibraryPreviewModal from '../../LibraryPreviewModal.jsx';

export default function CleanupPreview({ settings }) {
  const [search, setSearch] = useState('');
  const [mode, setMode] = useState('search');
  const [pageSize, setPageSize] = useState(25);
  const [result, setResult] = useState(null);
  const [item, setItem] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const request = useRef(0);
  const rules = JSON.stringify({
    title_rules: settings.title_rules,
    removal_rules: settings.removal_rules,
    year_rules: settings.year_rules,
  });

  useEffect(() => {
    request.current += 1;
    setResult(null);
    setBusy(false);
    setError('');
    return () => {
      request.current += 1;
    };
  }, [rules, search]);

  const preview = async (nextMode, page = 1, size = pageSize) => {
    const id = ++request.current;
    setBusy(true);
    setError('');
    setMode(nextMode);
    try {
      const data = await api.vodLibraryAction('cleanup-preview', {
        scope: 'catalog',
        search: nextMode === 'search' ? search.trim() : '',
        missing_tmdb_only: nextMode === 'missing',
        page,
        page_size: size,
        ...JSON.parse(rules),
      });
      if (id === request.current) setResult(data);
    } catch (e) {
      if (id === request.current) {
        setError(true);
        notifyLibraryError(e, 'Title cleanup preview');
      }
    } finally {
      if (id === request.current) setBusy(false);
    }
  };

  return (
    <Paper withBorder p="md">
      <Stack gap="sm">
        <Text fw={600}>Preview</Text>
        <Group align="flex-end" gap="xs">
          <TextInput
            label="Preview titles containing"
            error={!!error}
            placeholder="Search Library titles"
            value={search}
            maxLength={255}
            onChange={(event) => setSearch(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (
                event.key === 'Enter' &&
                !event.nativeEvent.isComposing &&
                search.trim() &&
                !busy
              ) {
                event.preventDefault();
                preview('search');
              }
            }}
            className={classes.search}
          />
          <Button
            leftSection={<Eye size={16} />}
            disabled={!search.trim() || busy}
            loading={busy && mode === 'search'}
            onClick={() => preview('search')}
          >
            Search
          </Button>
          <Button
            variant="default"
            disabled={busy}
            loading={busy && mode === 'missing'}
            onClick={() => preview('missing')}
          >
            Without TMDB ID
          </Button>
        </Group>
        {result && (
          <>
            <CleanupPreviewTable rows={result.results} onPreview={setItem} />
            <ListPagination
              page={result.page}
              pageSize={pageSize}
              total={result.count}
              onPageChange={(page) => preview(mode, page)}
              onPageSizeChange={(size) => {
                setPageSize(size);
                preview(mode, 1, size);
              }}
              pageSizeOptions={[10, 25, 50]}
              itemLabel="Titles"
              disabled={busy}
            />
          </>
        )}
      </Stack>
      {item && (
        <ErrorBoundary inline>
          <LibraryPreviewModal
            key={`${item.content_type}:${item.content_id}`}
            item={item}
            onClose={() => setItem(null)}
          />
        </ErrorBoundary>
      )}
    </Paper>
  );
}
