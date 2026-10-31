import { useEffect, useRef, useState } from 'react';
import { Button, Loader, Paper, Stack, Text, TextInput } from '@mantine/core';
import api from '../api';
import { notifyLibraryError } from '../utils/libraryFeedback.js';
import CleanupPreviewTable from './CleanupPreviewTable.jsx';
import ListPagination from './ListPagination.jsx';

export default function CategoryCleanupFields({
  accountId,
  categoryId,
  value,
  onChange,
  onValidityChange,
  saveError = false,
}) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const request = useRef(0);
  const rule = JSON.stringify(value);
  useEffect(() => {
    setPage(1);
  }, [rule, accountId, categoryId]);
  useEffect(() => {
    const id = ++request.current;
    setBusy(true);
    setError('');
    onValidityChange?.(false);
    const timer = setTimeout(async () => {
      try {
        const data = await api.vodLibraryAction('cleanup-preview', {
          scope: 'category',
          account: accountId,
          category: categoryId,
          title_cleanup: JSON.parse(rule),
          page,
          page_size: pageSize,
        });
        if (id === request.current) {
          setResult(data);
          onValidityChange?.(true);
        }
      } catch (e) {
        if (id === request.current) {
          setError(true);
          notifyLibraryError(
            e,
            'Title cleanup preview',
            'library-category-cleanup-preview'
          );
          setResult(null);
        }
      } finally {
        if (id === request.current) setBusy(false);
      }
    }, 300);
    return () => {
      clearTimeout(timer);
      request.current += 1;
    };
  }, [accountId, categoryId, rule, page, pageSize, retry, onValidityChange]);
  return (
    <Paper withBorder p="sm">
      <Stack gap="xs">
        <Text fw={600}>Title cleanup</Text>
        <TextInput
          label="Remove from titles (regex)"
          description="Prefixes, text removals and release-year formats configured in Settings → Cleanup are applied before this rule."
          error={!!error || saveError}
          value={value.pattern || ''}
          maxLength={500}
          onChange={(event) =>
            onChange({ ...value, pattern: event.currentTarget.value })
          }
        />
        {busy && <Loader size="xs" aria-label="Loading cleanup preview" />}
        {error && (
          <Button
            variant="subtle"
            size="compact-xs"
            onClick={() => setRetry((n) => n + 1)}
          >
            Retry preview
          </Button>
        )}
        {result && (
          <>
            <CleanupPreviewTable rows={result.results} />
            <ListPagination
              page={result.page}
              pageSize={pageSize}
              total={result.count}
              onPageChange={setPage}
              onPageSizeChange={(size) => {
                setPageSize(size);
                setPage(1);
              }}
              pageSizeOptions={[10, 25, 50]}
              itemLabel="Titles"
              disabled={busy}
            />
          </>
        )}
      </Stack>
    </Paper>
  );
}
