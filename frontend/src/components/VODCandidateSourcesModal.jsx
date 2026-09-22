import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  ScrollArea,
  Stack,
  Table,
  TableTbody,
  TableTd,
  TableTh,
  TableThead,
  TableTr,
  Text,
} from '@mantine/core';
import API from '../api.js';
import { videoFeatureLabel } from '../utils/vodMetadataOptions.js';

const REASON_LABELS = {
  eligible: 'Eligible',
  category_not_allowed: 'Category not allowed',
  stream_filter_include: 'Included by content filter',
  stream_filter_exclude: 'Excluded by content filter',
  content_filter_default_exclude: 'Excluded by unmatched-content default',
  audio_excluded: 'Audio language excluded',
  subtitle_excluded: 'Subtitle language excluded',
  language_not_matched: 'Language rules not matched',
  language_unknown: 'Language metadata unknown',
  resolution_unknown: 'Resolution unknown',
  resolution_below_minimum: 'Below minimum resolution',
  resolution_above_maximum: 'Above maximum resolution',
  feature_excluded: 'Video feature excluded',
  feature_unknown: 'Video features unknown',
  feature_not_matched: 'Required feature not matched',
  provider_inactive: 'Provider inactive',
  different_edition: 'Belongs to a different edition',
};

const metadataList = (metadata, primary, fallback) => {
  const value = metadata?.[primary] || (fallback && metadata?.[fallback]) || [];
  return Array.isArray(value) && value.length ? value.join(', ') : '—';
};

const sourceResolution = (metadata) => {
  const value = metadata?.resolution || metadata?.height;
  if (!value) return '—';
  const text = String(value);
  return /^\d+$/.test(text) ? `${text}p` : text;
};

const VODCandidateSourcesModal = ({
  opened,
  onClose,
  profileId,
  contentType,
  canonicalId,
  currentRelationId,
  editionKey,
  title,
  onSwitch,
}) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [switching, setSwitching] = useState('');

  useEffect(() => {
    if (!opened || !profileId || !canonicalId) return;
    let cancelled = false;
    setLoading(true);
    setError('');
    API.getVODAccessPolicyCandidates(profileId, {
      type: contentType,
      canonical_id: canonicalId,
      ...(currentRelationId ? { current_relation_id: currentRelationId } : {}),
      ...(editionKey ? { edition_key: editionKey } : {}),
    })
      .then((response) => {
        if (!cancelled) setData(response);
      })
      .catch((requestError) => {
        if (!cancelled) {
          setError(
            requestError?.body?.detail ||
              requestError?.message ||
              'Could not load source order.'
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    canonicalId,
    contentType,
    currentRelationId,
    editionKey,
    opened,
    profileId,
  ]);

  const heading = useMemo(
    () => title || data?.canonical_name || 'Compact source order',
    [data?.canonical_name, title]
  );

  const switchSource = async (row, mode) => {
    if (!onSwitch) return;
    const key = `${row.relation_id}:${mode}`;
    setSwitching(key);
    setError('');
    try {
      await onSwitch(row.relation_id, mode);
      onClose();
    } catch (requestError) {
      setError(
        requestError?.body?.error ||
          requestError?.message ||
          'Could not switch source.'
      );
    } finally {
      setSwitching('');
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={heading}
      size="95vw"
      centered
    >
      <Stack>
        <Alert color="blue">
          Eligible sources for this edition are shown in the exact profile
          order. Runtime capacity is checked again when playback opens a
          provider connection; sources from other editions and excluded sources
          remain visible in gray with the reason.
        </Alert>
        {onSwitch && (
          <Text size="sm" c="dimmed">
            “Next request” keeps the current buffered response and applies the
            source at the next Range request. “Switch now” ends the current
            response and depends on the player reconnecting automatically. VOD
            files can use different byte layouts, so a mid-playback source
            switch may resume at a different position or require reopening the
            title.
          </Text>
        )}
        {error && <Alert color="red">{error}</Alert>}
        {loading ? (
          <Group justify="center" py="xl">
            <Loader size="sm" />
            <Text c="dimmed">Loading source order…</Text>
          </Group>
        ) : (
          <ScrollArea h="min(65vh, 620px)">
            <Table striped highlightOnHover withTableBorder stickyHeader>
              <TableThead>
                <TableTr>
                  <TableTh>Order</TableTh>
                  <TableTh>Source</TableTh>
                  <TableTh>M3U account / category</TableTh>
                  <TableTh>DUB</TableTh>
                  <TableTh>SUB</TableTh>
                  <TableTh>Resolution</TableTh>
                  <TableTh>Format</TableTh>
                  <TableTh>Features</TableTh>
                  <TableTh>Decision</TableTh>
                  {onSwitch && <TableTh>Switch source</TableTh>}
                </TableTr>
              </TableThead>
              <TableTbody>
                {!data?.results?.length && (
                  <TableTr>
                    <TableTd colSpan={onSwitch ? 10 : 9}>
                      <Text ta="center" c="dimmed" py="lg">
                        No sources found for this title.
                      </Text>
                    </TableTd>
                  </TableTr>
                )}
                {(data?.results || []).map((row) => {
                  const metadata = row.metadata || {};
                  const features = metadata.video_features || [];
                  return (
                    <TableTr
                      key={row.relation_id}
                      style={{ opacity: row.allowed ? 1 : 0.48 }}
                    >
                      <TableTd>
                        <Group gap={5} wrap="nowrap">
                          {row.position ? (
                            <Badge variant="light">#{row.position}</Badge>
                          ) : (
                            <Badge color="gray" variant="outline">
                              Excluded
                            </Badge>
                          )}
                          {row.current && <Badge color="green">Playing</Badge>}
                        </Group>
                      </TableTd>
                      <TableTd>
                        <Text size="sm" fw={500} lineClamp={2}>
                          {row.source_name || 'Unknown source'}
                        </Text>
                        {row.provider_asset_id && (
                          <Text size="xs" c="dimmed">
                            Provider ID: {row.provider_asset_id}
                          </Text>
                        )}
                      </TableTd>
                      <TableTd>
                        <Text size="sm">{row.m3u_account_name}</Text>
                        <Text size="xs" c="dimmed">
                          {row.category_name || 'No category'}
                        </Text>
                      </TableTd>
                      <TableTd>
                        {metadataList(metadata, 'audio_languages', 'languages')}
                      </TableTd>
                      <TableTd>
                        {metadataList(metadata, 'subtitle_languages')}
                      </TableTd>
                      <TableTd>{sourceResolution(metadata)}</TableTd>
                      <TableTd>
                        {row.container_extension ||
                          metadata.container_extension ||
                          '—'}
                      </TableTd>
                      <TableTd>
                        {features.length
                          ? features.map(videoFeatureLabel).join(', ')
                          : '—'}
                      </TableTd>
                      <TableTd>
                        <Text size="sm">
                          {REASON_LABELS[row.reason] || row.reason || '—'}
                        </Text>
                        {row.rule_id && (
                          <Text size="xs" c="dimmed">
                            Rule: {row.rule_id}
                          </Text>
                        )}
                      </TableTd>
                      {onSwitch && (
                        <TableTd>
                          {row.allowed && !row.current ? (
                            <Group gap="xs" wrap="nowrap">
                              <Button
                                size="compact-xs"
                                variant="default"
                                loading={
                                  switching ===
                                  `${row.relation_id}:next_request`
                                }
                                onClick={() =>
                                  switchSource(row, 'next_request')
                                }
                              >
                                Next request
                              </Button>
                              <Button
                                size="compact-xs"
                                color="orange"
                                variant="light"
                                loading={switching === `${row.relation_id}:now`}
                                onClick={() => switchSource(row, 'now')}
                              >
                                Switch now
                              </Button>
                            </Group>
                          ) : (
                            <Text size="xs" c="dimmed">
                              {row.current ? 'Current source' : 'Not eligible'}
                            </Text>
                          )}
                        </TableTd>
                      )}
                    </TableTr>
                  );
                })}
              </TableTbody>
            </Table>
          </ScrollArea>
        )}
        {data && (
          <Text size="xs" c="dimmed">
            {data.eligible_count} eligible of {data.count} sources · Profile:{' '}
            {data.profile_name}
          </Text>
        )}
      </Stack>
    </Modal>
  );
};

export default VODCandidateSourcesModal;
