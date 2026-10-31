import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import {
  Button,
  Divider,
  Group,
  Loader,
  LoadingOverlay,
  Modal,
  Select,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import {
  Ban,
  LockKeyhole,
  LockKeyholeOpen,
  Pencil,
  RefreshCw,
} from 'lucide-react';
import api from '../api';
import {
  notifyLibraryError,
  notifyLibrarySuccess,
} from '../utils/libraryFeedback.js';
import useAuthStore from '../store/auth';
import useLibraryStore from '../store/useLibraryStore';
import useSettingsStore from '../store/settings';
import useVideoStore from '../store/useVideoStore';
import useProviderDetailsPolling from '../hooks/useProviderDetailsPolling.jsx';
import { copyToClipboard } from '../utils';
import {
  getEpisodeStreamUrl,
  getYouTubeEmbedUrl,
} from '../utils/components/SeriesModalUtils.js';
import { getMovieStreamUrl } from '../utils/components/VODModalUtils.js';
import {
  LibraryContentEditor,
  LibraryDialog,
  LibrarySourceEditor,
} from './LibraryDialogs.jsx';
import {
  PreviewAction as Icon,
  PreviewSummary,
  PreviewSources,
  PreviewEpisodes,
  PreviewBackdrop,
} from './LibraryPreviewContent.jsx';
import classes from './LibraryPreviewModal.module.css';
import ConfirmationDialog from './ConfirmationDialog.jsx';
import { MetadataOriginLegend } from './MetadataOriginBadges.jsx';
import {
  initialMetadataLanguage,
  metadataLanguageLabel,
  metadataLanguageOrder,
} from '../utils/vodMetadataLanguages.js';

// Provider IDs are account-scoped; keep both in the existing proxy contract.
function sourceUrl(content, source, environment, episode = false) {
  const provider = {
    stream_id: episode ? content.stream_id : source.provider_id,
    m3u_account: source.account,
  };
  const url = new URL(
    (episode ? getEpisodeStreamUrl : getMovieStreamUrl)(
      content,
      provider,
      environment
    )
  );
  url.searchParams.set('m3u_account_id', source.account.id);
  return url.toString();
}

export default function LibraryPreviewModal({
  item,
  onClose,
  accountId = '',
  inStack = false,
}) {
  const admin = useAuthStore((state) => state.user?.user_level >= 10);
  const environment = useSettingsStore((state) => state.environment.env_mode);
  const showVideo = useVideoStore((state) => state.showVideo);
  const [contentId, setContentId] = useState(item.content_id);
  const [sourceId, setSourceId] = useState(item.source_id || null);
  const [language, setLanguage] = useState(null);
  const [season, setSeason] = useState(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [version, setVersion] = useState(0);
  const [data, setData] = useState(null);
  const [loadedContentId, setLoadedContentId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [editor, setEditor] = useState(null);
  const [busy, setBusy] = useState(false);
  const [providerStatus, setProviderStatus] = useState(null);
  const [loadingProvider, setLoadingProvider] = useState(false);
  const [trailer, setTrailer] = useState(false);
  const [showLoading, setShowLoading] = useState(false);
  const [blockConfirmation, setBlockConfirmation] = useState(false);
  const request = useRef(0);
  const kind = item.content_type;
  const series = kind === 'series';

  useEffect(() => {
    const generation = ++request.current;
    setLoading(true);
    setError('');
    const params = new URLSearchParams({
      content_type: kind,
      id: contentId,
      page,
      page_size: pageSize,
    });
    if (sourceId) params.set('source_id', sourceId);
    if (accountId) params.set('preferred_account', accountId);
    if (season !== null) params.set('season', season);
    api
      .getVODLibraryDetails(params)
      .then((result) => {
        if (generation === request.current) {
          setData(result);
          setLoadedContentId(contentId);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (generation === request.current) {
          setError(true);
          notifyLibraryError(err, 'Library preview');
          setLoading(false);
        }
      });
    return () => {
      request.current += 1;
    };
  }, [kind, contentId, sourceId, season, page, pageSize, version, accountId]);

  const selected = data?.sources.find(
    (row) => row.source_id === data.selected_source_id
  );
  const canonical = data?.canonical || item;
  const loadProvider = useCallback(
    (id, relationId, options) =>
      series
        ? api.getSeriesInfo(id, relationId, {
            ...options,
            includeEpisodes: false,
          })
        : api.getMovieProviderInfo(id, relationId, options),
    [series]
  );
  const providerFailure = useRef('');
  const providerResult = useCallback(
    (result) => {
      setProviderStatus(result);
      const failure = ['failed', 'unavailable'].includes(result.refresh_status)
        ? `${selected?.source_id}:${result.refresh_status}`
        : '';
      if (failure && providerFailure.current !== failure)
        notifyLibraryError(
          new Error(
            'Provider details could not be loaded. Stored data is still available.'
          )
        );
      providerFailure.current = failure;
      if (result.refresh_status === 'completed') {
        setLoading(true);
        setVersion((value) => value + 1);
      }
    },
    [selected?.source_id]
  );
  const providerId = canonical?.content_id;
  const relationId = selected?.source_id;
  const currentSource =
    loadedContentId === contentId && (!sourceId || sourceId === relationId);
  useEffect(() => {
    if (!providerId || !relationId || !currentSource) return undefined;
    let cancelled = false;
    setLoadingProvider(true);
    const load = async () => {
      try {
        const result = await loadProvider(providerId, relationId, {
          background: true,
        });
        if (!cancelled) {
          // Completed on entry means the stored details are already current.
          // A pending refresh reloads the Library document when polling completes.
          if (result?.refresh_status === 'completed') {
            setProviderStatus(result);
            providerFailure.current = '';
          } else if (result) providerResult(result);
          else setProviderStatus({ refresh_status: 'failed' });
        }
      } catch {
        if (!cancelled) providerResult({ refresh_status: 'failed' });
      } finally {
        if (!cancelled) setLoadingProvider(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [providerId, relationId, currentSource, loadProvider, providerResult]);
  const { retry, retrying } = useProviderDetailsPolling({
    opened: !!selected && currentSource,
    id: canonical?.content_id,
    relationId: selected?.source_id,
    details: providerStatus,
    load: loadProvider,
    onResult: providerResult,
  });
  const chooseSource = (source) => {
    if (source.source_id === selected?.source_id) return;
    setLoading(true);
    setSourceId(source.source_id);
    setSeason(null);
    setPage(1);
    setProviderStatus(null);
    setLoadingProvider(false);
  };
  const saved = (result) => {
    setLoading(true);
    const target = result?.metadata?.id;
    if (target && target !== contentId) {
      setContentId(target);
      setSourceId(editor?.type === 'source' ? editor.source.source_id : null);
      setSeason(null);
      setPage(1);
      setProviderStatus(null);
      setLoadingProvider(false);
    }
    setVersion((value) => value + 1);
    useLibraryStore.getState().fetchContent();
  };
  const protect = async () => {
    setBusy(true);
    setError('');
    try {
      await api.vodLibraryAction('bulk', {
        items: [{ content_type: kind, id: canonical.content_id }],
        operation: canonical.metadata_locked ? 'unlock' : 'lock',
      });
      notifyLibrarySuccess('Metadata protection updated.');
      saved();
    } catch (err) {
      notifyLibraryError(err);
    } finally {
      setBusy(false);
    }
  };
  const toggleBlock = async () => {
    setBusy(true);
    try {
      await api.vodLibraryAction('bulk', {
        items: [{ content_type: kind, id: canonical.content_id }],
        operation: canonical.library_blocked ? 'unblock' : 'block',
      });
      notifyLibrarySuccess(
        canonical.library_blocked
          ? 'Title unblocked.'
          : 'Title blocked globally.'
      );
      setBlockConfirmation(false);
      saved();
    } catch (error) {
      notifyLibraryError(error);
    } finally {
      setBusy(false);
    }
  };
  const play = (content, source, episode = false) => {
    showVideo(sourceUrl(content, source, environment, episode), 'vod', {
      ...content,
      type: episode ? 'episode' : 'movie',
    });
  };
  const copy = (content, source, episode = false) =>
    copyToClipboard(sourceUrl(content, source, environment, episode), {
      successTitle: 'Link Copied!',
      successMessage: 'Stream link copied to clipboard',
    });
  const languages = metadataLanguageOrder(canonical);
  const selectedLanguage =
    language === 'provider' || languages.includes(language)
      ? language
      : initialMetadataLanguage(canonical);
  const providerView = selectedLanguage === 'provider';
  const localized =
    !providerView && canonical?.metadata?.localized?.[selectedLanguage];
  const display = providerView ? selected?.provider || canonical : canonical;
  const metadata = providerView
    ? selected?.provider || canonical?.metadata || {}
    : canonical?.metadata || {};
  const displayTitle =
    (!providerView && canonical?.display_name?.trim()) ||
    localized?.title?.trim() ||
    display?.name ||
    item.name;
  const description =
    localized && Object.hasOwn(localized, 'overview')
      ? localized.overview
      : display?.description;
  const disabled = busy || loading || !!error;
  const providerBusy =
    loadingProvider ||
    retrying ||
    providerStatus?.refresh_status === 'pending' ||
    !providerStatus;
  const missingDetails =
    selected &&
    (!selected.provider?.details_loaded ||
      (series && !(data.seasons || []).length));
  const waiting =
    !error &&
    (loading ||
      !currentSource ||
      !!(missingDetails && providerBusy) ||
      retrying);
  useEffect(() => {
    if (!waiting) {
      setShowLoading(false);
      return undefined;
    }
    const timer = setTimeout(() => setShowLoading(true), 250);
    return () => clearTimeout(timer);
  }, [waiting]);

  const poster =
    (providerView && selected?.provider?.poster_url) || canonical?.poster_url;
  const backdrop =
    (providerView && selected?.provider?.backdrop_url) ||
    canonical?.backdrop_url;
  const Scope = inStack ? Fragment : Modal.Stack;
  return (
    <Scope>
      <LibraryDialog
        title={series ? 'Series preview' : 'Movie preview'}
        size="min(94vw, 90rem)"
        onClose={onClose}
        busy={busy}
        classNames={{
          header: classes.header,
          title: classes.hiddenTitle,
          body: classes.body,
        }}
      >
        <div className={classes.preview} aria-busy={waiting}>
          <PreviewBackdrop src={backdrop} name={displayTitle} />
          <Stack gap="md" className={classes.content} inert={waiting}>
            <Group gap={6} align="center" wrap="wrap" pr="xl">
              {admin && (
                <>
                  <Icon
                    label={
                      canonical?.library_blocked
                        ? 'Unblock title'
                        : 'Block title globally'
                    }
                    icon={Ban}
                    onClick={() => setBlockConfirmation(true)}
                    disabled={disabled}
                    variant={canonical?.library_blocked ? 'light' : 'default'}
                    color={canonical?.library_blocked ? 'red' : 'gray'}
                  />
                  <Icon
                    label={
                      canonical?.metadata_locked
                        ? 'Unlock automatic metadata matching'
                        : 'Lock automatic metadata matching'
                    }
                    icon={
                      canonical?.metadata_locked ? LockKeyhole : LockKeyholeOpen
                    }
                    onClick={protect}
                    disabled={disabled}
                    variant="default"
                    color="gray"
                  />
                  <Button
                    size="xs"
                    variant="default"
                    leftSection={<Pencil size={15} />}
                    onClick={() => setEditor({ type: 'title' })}
                    disabled={disabled || !!canonical?.metadata_locked}
                  >
                    Edit metadata
                  </Button>
                </>
              )}
              <Select
                aria-label="Metadata language"
                value={selectedLanguage}
                onChange={setLanguage}
                data={[
                  ...languages.map((value) => ({
                    value,
                    label: metadataLanguageLabel(value),
                  })),
                  { value: 'provider', label: 'Provider' },
                ]}
                allowDeselect={false}
                size="xs"
                w={200}
              />
            </Group>
            {error && (
              <Button
                variant="subtle"
                size="compact-xs"
                onClick={() => setVersion((value) => value + 1)}
              >
                Retry
              </Button>
            )}
            <PreviewSummary
              title={displayTitle}
              display={display}
              metadata={metadata}
              description={description}
              localized={localized}
              series={series}
              episodeCount={(data?.seasons || []).reduce(
                (count, row) => count + row.count,
                0
              )}
              poster={poster}
              onTrailer={() => setTrailer(true)}
            />
            {selected && (
              <>
                <Group gap="xs" mt="md">
                  <Title order={4}>Sources ({data.sources.length})</Title>
                  <Button
                    variant="subtle"
                    size="xs"
                    leftSection={<RefreshCw size={14} />}
                    onClick={retry}
                    loading={retrying}
                    disabled={
                      loading ||
                      loadingProvider ||
                      providerStatus?.refresh_status === 'pending'
                    }
                  >
                    {series
                      ? 'Refresh provider episodes'
                      : 'Refresh provider details'}
                  </Button>
                  <Group ml="auto">
                    <MetadataOriginLegend />
                  </Group>
                </Group>
                <PreviewSources
                  sources={data.sources}
                  selected={selected}
                  series={series}
                  accountId={accountId}
                  blocked={!!canonical.library_blocked}
                  disabled={disabled}
                  admin={admin}
                  onSelect={chooseSource}
                  onPlay={(source) => play(canonical, source)}
                  onCopy={(source) => copy(canonical, source)}
                  onEdit={(source) =>
                    setEditor({
                      type: 'source',
                      source: { ...canonical, ...source },
                    })
                  }
                />
                {series && (
                  <>
                    <Divider />
                    <PreviewEpisodes
                      key={selected.source_id}
                      data={data}
                      source={selected}
                      season={season}
                      pageSize={pageSize}
                      disabled={disabled}
                      blocked={!!canonical.library_blocked}
                      onSeason={(value) => {
                        if (value === season) return;
                        setLoading(true);
                        setSeason(value);
                        setPage(1);
                      }}
                      onPage={(value) => {
                        if (value !== page) {
                          setLoading(true);
                          setPage(value);
                        }
                      }}
                      onPageSize={(value) => {
                        if (value === pageSize) return;
                        setLoading(true);
                        setPageSize(value);
                        setPage(1);
                      }}
                      onPlay={(episode) => play(episode, selected, true)}
                      onCopy={(episode) => copy(episode, selected, true)}
                    />
                  </>
                )}
              </>
            )}
          </Stack>
          <LoadingOverlay
            visible={showLoading}
            zIndex={3}
            overlayProps={{ backgroundOpacity: 0.55, blur: 2, radius: 'md' }}
            loaderProps={{
              children: (
                <Stack gap="xs" align="center" role="status" aria-live="polite">
                  <Loader size="sm" />
                  <Text size="sm">
                    {loading
                      ? 'Loading title details…'
                      : series
                        ? 'Loading provider episodes…'
                        : 'Loading provider details…'}
                  </Text>
                </Stack>
              ),
            }}
          />
        </div>
      </LibraryDialog>
      {editor?.type === 'title' && (
        <LibraryContentEditor
          item={canonical}
          onClose={() => setEditor(null)}
          onSaved={saved}
        />
      )}
      <ConfirmationDialog
        opened={blockConfirmation}
        onClose={() => setBlockConfirmation(false)}
        onConfirm={toggleBlock}
        loading={busy}
        title={
          canonical.library_blocked ? 'Unblock title?' : 'Block title globally?'
        }
        message={
          canonical.library_blocked
            ? 'Allow this title to be listed and played by clients again?'
            : 'This title and all its sources will not be listed or playable by any client. Metadata and provider data stay unchanged.'
        }
        confirmLabel={canonical.library_blocked ? 'Unblock' : 'Block'}
        confirmColor={canonical.library_blocked ? 'blue' : 'red'}
      />
      {editor?.type === 'source' && (
        <LibrarySourceEditor
          items={[editor.source]}
          onClose={() => setEditor(null)}
          onSaved={saved}
        />
      )}
      {trailer && (
        <LibraryDialog
          title="Trailer"
          size="xl"
          onClose={() => setTrailer(false)}
        >
          <iframe
            title="YouTube trailer"
            src={getYouTubeEmbedUrl(metadata.youtube_trailer)}
            className={classes.trailer}
            allowFullScreen
            referrerPolicy="strict-origin-when-cross-origin"
          />
        </LibraryDialog>
      )}
    </Scope>
  );
}
