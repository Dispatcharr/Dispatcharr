import React, { useState, useEffect, useCallback } from 'react';
import {
  Badge,
  Button,
  Divider,
  Flex,
  Group,
  Image,
  Modal,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { Calendar, Video } from 'lucide-react';
import API from '../api';
import useVideoStore from '../store/useVideoStore';
import useSettingsStore from '../store/settings';
import { getShowVideoUrl } from '../utils/cards/RecordingCardUtils';
import { formatSeasonEpisode } from '../utils/guideUtils';
import {
  format,
  initializeTime,
  diff,
  useDateTimeFormat,
} from '../utils/dateTimeUtils';
import { imdbUrl, tmdbUrl } from '../utils/externalUrls';

const overlayProps = { color: '#000', backgroundOpacity: 0.55, blur: 0 };

function formatDurationMinutes(startTime, endTime) {
  if (!startTime || !endTime) return null;
  const start = initializeTime(startTime);
  const end = initializeTime(endTime);
  const minutes = diff(end, start, 'minute');
  if (minutes >= 60) {
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
  }
  return `${minutes}m`;
}

function resolveImageUrl(detail) {
  if (detail?.tmdb_poster_url) return detail.tmdb_poster_url;
  if (detail?.poster_url) return detail.poster_url;
  if (detail?.images?.length > 0) return detail.images[0].url;
  if (detail?.icon) return detail.icon;
  return null;
}

function formatCredits(actors) {
  if (!actors?.length) return null;
  return actors
    .map((a) => (a.role ? `${a.name} (${a.role})` : a.name))
    .join(', ');
}

export default function ProgramDetailModal({
  program,
  channel,
  opened,
  onClose,
  onRecord,
}) {
  const [detailData, setDetailData] = useState(null);

  const showVideo = useVideoStore((s) => s.showVideo);
  const env_mode = useSettingsStore((s) => s.environment.env_mode);
  const { timeFormat } = useDateTimeFormat();

  useEffect(() => {
    if (!opened || !program) {
      setDetailData(null);
      return;
    }

    // Dummy programs may use UUID-style IDs that aren't real DB PKs
    const programId = program.id;
    if (!programId || typeof programId === 'string') {
      setDetailData(null);
      return;
    }

    let cancelled = false;

    API.getProgramDetail(programId)
      .then((data) => {
        if (!cancelled) setDetailData(data);
      })
      .catch(() => {
        if (!cancelled) setDetailData(null);
      });

    return () => {
      cancelled = true;
    };
  }, [opened, program?.id]);

  const handleWatchLive = useCallback(() => {
    if (!channel) return;
    showVideo(getShowVideoUrl(channel, env_mode), 'live', {
      name: channel.name,
    });
    onClose();
  }, [channel, env_mode, showVideo, onClose]);

  const handleRecord = useCallback(() => {
    if (onRecord) onRecord(program);
  }, [onRecord, program]);

  if (!program) return null;

  // Merge detail data with grid data (detail enriches, grid is baseline)
  const d = detailData || {};
  const seasonEpisodeLabel = formatSeasonEpisode(
    d.season ?? program.season,
    d.episode ?? program.episode
  );
  const hasBadges =
    seasonEpisodeLabel ||
    program.is_live ||
    program.is_new ||
    d.is_previously_shown ||
    program.is_premiere ||
    program.is_finale ||
    d.video_quality ||
    d.rating;

  const categories = d.categories || [];
  const credits = d.credits || {};
  const hasCredits =
    credits.actors?.length > 0 ||
    credits.directors?.length > 0 ||
    credits.writers?.length > 0;
  const starRatings = d.star_ratings || [];
  const description = d.description || program.description;
  const subtitle = d.sub_title ?? program.sub_title;
  const posterUrl =
    resolveImageUrl(d) || program?.custom_properties?.icon || null;
  const duration = formatDurationMinutes(program.start_time, program.end_time);
  const programStart = initializeTime(program.start_time || program.startMs);
  const programEnd = initializeTime(program.end_time || program.endMs);

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={
        channel ? (
          <Text size="sm" fw={600} c="white">
            {channel.channel_number ? `${channel.channel_number} - ` : ''}
            {channel.name}
          </Text>
        ) : null
      }
      size="lg"
      centered
      overlayProps={overlayProps}
      zIndex={9999}
    >
      <Stack gap="md">
        <Flex gap="md" align="stretch">
          {posterUrl && (
            <Image
              src={posterUrl}
              w={140}
              fit="contain"
              radius="sm"
              style={{ flexShrink: 0 }}
              onError={(e) => {
                e.currentTarget.style.display = 'none';
              }}
            />
          )}

          <Stack
            gap="xs"
            style={{ flex: 1, minWidth: 0 }}
            justify={posterUrl ? 'space-between' : 'flex-start'}
          >
            <Stack gap="xs">
              <Title order={3} c="white">
                {program.title}
              </Title>

              {subtitle && (
                <Text size="sm" fs="italic" c="dimmed">
                  {subtitle}
                </Text>
              )}

              {hasBadges && (
                <Group gap="xs" wrap="wrap">
                  {program.is_live && (
                    <Badge size="sm" variant="light" color="red">
                      LIVE
                    </Badge>
                  )}
                  {program.is_new && (
                    <Badge size="sm" variant="light" color="green">
                      NEW
                    </Badge>
                  )}
                  {d.is_previously_shown && (
                    <Badge size="sm" variant="light" color="gray">
                      RERUN
                    </Badge>
                  )}
                  {program.is_premiere && (
                    <Badge size="sm" variant="light" color="violet">
                      PREMIERE
                    </Badge>
                  )}
                  {program.is_finale && (
                    <Badge size="sm" variant="light" color="orange">
                      FINALE
                    </Badge>
                  )}
                  {seasonEpisodeLabel && (
                    <Badge size="sm" variant="light" color="cyan">
                      {seasonEpisodeLabel}
                    </Badge>
                  )}
                  {d.rating && (
                    <Badge size="sm" variant="light" color="yellow">
                      {d.rating}
                    </Badge>
                  )}
                  {d.video_quality && (
                    <Badge size="sm" variant="light" color="indigo">
                      {d.video_quality}
                    </Badge>
                  )}
                </Group>
              )}

              <Group gap="xs" wrap="wrap">
                <Text size="sm" c="dimmed">
                  {format(programStart, timeFormat)} –{' '}
                  {format(programEnd, timeFormat)}
                </Text>
                {duration && (
                  <>
                    <Text size="sm" c="dimmed">
                      ·
                    </Text>
                    <Text size="sm" c="dimmed">
                      {duration}
                    </Text>
                  </>
                )}
                {categories.length > 0 && (
                  <>
                    <Text size="sm" c="dimmed">
                      ·
                    </Text>
                    <Text size="sm" c="dimmed">
                      {categories.join(', ')}
                    </Text>
                  </>
                )}
              </Group>
            </Stack>

            <Group gap="sm">
              {program.isLive && channel && (
                <Button
                  leftSection={<Video size={14} />}
                  variant="filled"
                  color="blue"
                  size="sm"
                  onClick={handleWatchLive}
                >
                  Watch Live
                </Button>
              )}
              {!program.isPast && (
                <Button
                  leftSection={<Calendar size={14} />}
                  variant="filled"
                  color="red"
                  size="sm"
                  onClick={handleRecord}
                >
                  Record
                </Button>
              )}
            </Group>
          </Stack>
        </Flex>

        {description && (
          <>
            <Divider color="#333" />
            <Text size="sm" c="#cbd5e0" style={{ whiteSpace: 'pre-line' }}>
              {description}
            </Text>
          </>
        )}

        {hasCredits && (
          <>
            <Divider color="#333" />
            <Stack gap={4}>
              {credits.actors?.length > 0 && (
                <Text size="sm" c="dimmed">
                  <Text span fw={600}>
                    Cast:{' '}
                  </Text>
                  {formatCredits(credits.actors)}
                </Text>
              )}
              {credits.directors?.length > 0 && (
                <Text size="sm" c="dimmed">
                  <Text span fw={600}>
                    Director:{' '}
                  </Text>
                  {credits.directors.join(', ')}
                </Text>
              )}
              {credits.writers?.length > 0 && (
                <Text size="sm" c="dimmed">
                  <Text span fw={600}>
                    Writer:{' '}
                  </Text>
                  {credits.writers.join(', ')}
                </Text>
              )}
            </Stack>
          </>
        )}

        {(d.country ||
          d.language ||
          d.original_air_date ||
          starRatings.length > 0) && (
          <>
            <Divider color="#333" />
            <Group gap="md" wrap="wrap">
              {d.country && (
                <Text size="sm" c="dimmed">
                  <Text span fw={600}>
                    Country:{' '}
                  </Text>
                  {d.country}
                </Text>
              )}
              {d.language && (
                <Text size="sm" c="dimmed">
                  <Text span fw={600}>
                    Language:{' '}
                  </Text>
                  {d.language}
                </Text>
              )}
              {d.original_air_date && (
                <Text size="sm" c="dimmed">
                  <Text span fw={600}>
                    Original Air:{' '}
                  </Text>
                  {d.original_air_date}
                </Text>
              )}
              {starRatings.map((sr, i) => (
                <Text size="sm" c="dimmed" key={i}>
                  ★ {sr.value}
                  {sr.system ? ` (${sr.system})` : ''}
                </Text>
              ))}
            </Group>
          </>
        )}

        {(d.imdb_id || d.tmdb_id) && (
          <Group gap="xs">
            {d.imdb_id && (
              <Badge
                component="a"
                href={imdbUrl(d.imdb_id)}
                target="_blank"
                rel="noopener noreferrer"
                size="sm"
                variant="light"
                color="yellow"
                style={{ cursor: 'pointer' }}
              >
                IMDb ↗
              </Badge>
            )}
            {d.tmdb_id && (
              <Badge
                component="a"
                href={tmdbUrl(d.tmdb_id, d.tmdb_media_type)}
                target="_blank"
                rel="noopener noreferrer"
                size="sm"
                variant="light"
                color="cyan"
                style={{ cursor: 'pointer' }}
              >
                TMDB ↗
              </Badge>
            )}
          </Group>
        )}
      </Stack>
    </Modal>
  );
}
