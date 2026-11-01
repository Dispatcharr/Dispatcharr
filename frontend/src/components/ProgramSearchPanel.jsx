import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  Code,
  Flex,
  Group,
  LoadingOverlay,
  Pagination,
  Popover,
  PopoverDropdown,
  PopoverTarget,
  SegmentedControl,
  Select,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { Info, Search, X } from 'lucide-react';
import API from '../api';
import { formatApiError, useDebounce } from '../utils';
import {
  buildProgramSearchParams,
  formatSeasonEpisode,
  formatTime,
  mapSearchResultToGuideProgram,
  PROGRAM_SEARCH_EXAMPLES,
  PROGRAM_SEARCH_FIELDS,
  PROGRAM_SEARCH_MIN_LENGTH,
  PROGRAM_SEARCH_PAGE_SIZE,
  PROGRAM_SEARCH_REGEX_EXAMPLES,
  PROGRAM_SEARCH_WINDOWS,
} from '../utils/guideUtils';
import {
  format,
  getNow,
  getNowMs,
  isSame,
  useDateTimeFormat,
} from '../utils/dateTimeUtils';
import { DESCRIPTION_MODES } from '../utils/forms/SeriesRuleEditorModalUtils';

const NO_RESULTS_WINDOW_TEXT = {
  now: 'airing now',
  '24h': 'in the next 24 hours',
  '7d': 'in the next 7 days',
};

const ProgramSearchResult = React.memo(
  ({ result, index, recording, timeFormat, dateFormat, onSelect }) => {
    const program = mapSearchResultToGuideProgram(result, getNowMs());
    const { programStart, programEnd, isLive } = program;
    const channels = program.channels || [];
    const seasonEpisodeLabel = formatSeasonEpisode(
      program.season,
      program.episode
    );
    const epgLabel = [
      program.epg_name,
      program.epg_source && `(${program.epg_source})`,
    ]
      .filter(Boolean)
      .join(' ');

    const handleKeyDown = (event) => {
      if (event.target !== event.currentTarget) return;
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        onSelect(program, channels[0] || null);
      }
    };

    return (
      <Group
        role="button"
        tabIndex={0}
        align="flex-start"
        p={'10px 20px'}
        style={{
          cursor: 'pointer',
          backgroundColor: index % 2 === 0 ? '#27272a' : '#18181b',
          opacity: channels.length > 0 ? 1 : 0.6,
        }}
        onClick={() => onSelect(program, channels[0] || null)}
        onKeyDown={handleKeyDown}
      >
        <Stack gap={0} w={160}>
          <Text size="sm" fw={500}>
            {formatTime(programStart, dateFormat)}
          </Text>
          <Text size="sm" c="dimmed">
            {format(programStart, timeFormat)} -{' '}
            {isSame(programStart, programEnd, 'day')
              ? ''
              : `${format(programEnd, dateFormat)} `}
            {format(programEnd, timeFormat)}
          </Text>
        </Stack>

        <Stack gap={4} style={{ flex: 1, minWidth: 200 }}>
          <Text fw="bold">{program.title}</Text>
          {program.sub_title && (
            <Text size="sm" fs="italic" c="dimmed">
              {program.sub_title}
            </Text>
          )}
          {channels.length > 0 ? (
            <Group gap="xs">
              {channels.map((channel) => (
                <Group key={channel.id} gap={4} wrap="nowrap">
                  <Button
                    variant="light"
                    color="gray"
                    size="compact-xs"
                    onClick={(event) => {
                      event.stopPropagation();
                      onSelect(program, channel);
                    }}
                  >
                    {channel.channel_number
                      ? `${channel.channel_number} · `
                      : ''}
                    {channel.name}
                  </Button>
                  {channel.channel_group && (
                    <Text size="xs" c="dimmed">
                      {channel.channel_group}
                    </Text>
                  )}
                </Group>
              ))}
            </Group>
          ) : (
            <Tooltip label="No channel uses this EPG entry. Assign it to a channel to watch or record this program.">
              <Text size="xs" c="dimmed">
                No channel{epgLabel && ` · ${epgLabel}`}
              </Text>
            </Tooltip>
          )}
        </Stack>

        <Group gap="xs">
          {isLive && (
            <Badge size="sm" variant="light" color="teal">
              Airing now
            </Badge>
          )}
          {recording && (
            <Badge size="sm" variant="light" color={isLive ? 'red' : 'yellow'}>
              {isLive ? 'Recording' : 'Scheduled'}
            </Badge>
          )}
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
        </Group>
      </Group>
    );
  }
);

const ProgramSearchPanel = React.memo(
  ({ visible, recordingsByProgramId, onSelect }) => {
    const [query, setQuery] = useState('');
    const [search, setSearch] = useState({
      query: '',
      field: 'title',
      window: '24h',
      mode: 'contains',
      page: 1,
      anchor: null,
    });
    const [data, setData] = useState(null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState(null);
    const inputRef = useRef(null);
    const resultsRef = useRef(null);

    const { timeFormat, dateFormat } = useDateTimeFormat();
    const debouncedQuery = useDebounce(query, 400);
    const isIdle = search.query.length < PROGRAM_SEARCH_MIN_LENGTH;

    // Changes other than the page start over at page 1 with a fresh time anchor
    const updateSearch = useCallback((key, value) => {
      setSearch((prev) =>
        prev[key] === value
          ? prev
          : { ...prev, [key]: value, page: 1, anchor: getNow().toISOString() }
      );
    }, []);

    useEffect(() => {
      if (visible) inputRef.current?.focus();
    }, [visible]);

    useEffect(() => {
      updateSearch('query', debouncedQuery.trim());
    }, [debouncedQuery, updateSearch]);

    useEffect(() => {
      if (search.query.length < PROGRAM_SEARCH_MIN_LENGTH) {
        setIsLoading(false);
        return undefined;
      }

      const controller = new AbortController();
      setIsLoading(true);
      setError(null);
      API.searchPrograms(buildProgramSearchParams(search), {
        signal: controller.signal,
      })
        .then((response) => {
          if (controller.signal.aborted) return;
          setData(response);
          if (resultsRef.current) resultsRef.current.scrollTop = 0;
        })
        .catch((err) => {
          if (err?.name === 'AbortError' || controller.signal.aborted) return;
          // A shrunken result set no longer has this page
          if (err?.status === 404 && search.page > 1) {
            setSearch((prev) => ({ ...prev, page: 1 }));
            return;
          }
          setError(err);
          setData(null);
        })
        .finally(() => {
          if (!controller.signal.aborted) setIsLoading(false);
        });

      return () => controller.abort();
    }, [search]);

    const handleQueryKeyDown = (e) => {
      if (e.key === 'Enter') {
        updateSearch('query', query.trim());
      }
    };

    const handleClearQuery = () => {
      setQuery('');
      updateSearch('query', '');
    };

    const handlePageChange = (page) => {
      setSearch((prev) => ({ ...prev, page }));
    };

    const handleRetry = () => {
      setSearch((prev) => ({ ...prev }));
    };

    const count = data?.count ?? 0;
    const startIdx = (search.page - 1) * PROGRAM_SEARCH_PAGE_SIZE + 1;
    const endIdx = Math.min(search.page * PROGRAM_SEARCH_PAGE_SIZE, count);
    const paginationString = `Showing ${startIdx}-${endIdx} of ${count}`;

    return (
      <Box
        style={{
          flexDirection: 'column',
          backgroundColor: '#18181B',
          zIndex: 20,
        }}
        display={visible ? 'flex' : 'none'}
        pos="absolute"
        top={0}
        right={0}
        bottom={0}
        left={0}
      >
        <Flex gap="md" align="center" p={'12px 20px'}>
          <TextInput
            ref={inputRef}
            placeholder="Search programs..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleQueryKeyDown}
            w={'250px'}
            leftSection={<Search size={16} />}
            rightSectionWidth={query ? 56 : 32}
            rightSection={
              <Group gap={4} wrap="nowrap">
                <Popover width={330} position="top" withArrow shadow="md">
                  <PopoverTarget>
                    <ActionIcon
                      variant="subtle"
                      size="xs"
                      color="gray"
                      aria-label="Search syntax"
                    >
                      <Info size={14} />
                    </ActionIcon>
                  </PopoverTarget>
                  <PopoverDropdown p="sm">
                    <Text size="xs" fw={600} mb="xs" c="dimmed">
                      SEARCH EXAMPLES
                    </Text>
                    <Stack gap={6}>
                      {(search.mode === 'regex'
                        ? PROGRAM_SEARCH_REGEX_EXAMPLES
                        : PROGRAM_SEARCH_EXAMPLES
                      ).map(({ label, example }) => (
                        <Group key={label} gap="xs" wrap="nowrap">
                          <Text
                            size="xs"
                            c="dimmed"
                            style={{ minWidth: '90px' }}
                          >
                            {label}
                          </Text>
                          <Code size="xs">{example}</Code>
                        </Group>
                      ))}
                    </Stack>
                  </PopoverDropdown>
                </Popover>
                {query && (
                  <ActionIcon
                    onClick={handleClearQuery}
                    aria-label="Clear search"
                    variant="subtle"
                    color="gray"
                    size="sm"
                  >
                    <X size={14} />
                  </ActionIcon>
                )}
              </Group>
            }
          />

          <SegmentedControl
            data={PROGRAM_SEARCH_FIELDS}
            value={search.field}
            onChange={(value) => updateSearch('field', value)}
          />

          <SegmentedControl
            data={DESCRIPTION_MODES}
            value={search.mode}
            onChange={(value) => updateSearch('mode', value)}
          />

          <Select
            data={PROGRAM_SEARCH_WINDOWS}
            value={search.window}
            onChange={(value) => updateSearch('window', value)}
            allowDeselect={false}
            w={'160px'}
            aria-label="When"
          />

          {!isIdle && data && (
            <Text size="sm" c="dimmed">
              {count} {count === 1 ? 'program' : 'programs'}
            </Text>
          )}
        </Flex>

        <Box
          ref={resultsRef}
          style={{ flex: 1, overflowY: 'auto' }}
          pos="relative"
        >
          <LoadingOverlay visible={isLoading} />
          {isIdle ? (
            <Box p={'30px'} ta="center">
              <Text size="lg">
                Type at least {PROGRAM_SEARCH_MIN_LENGTH} characters to search
              </Text>
            </Box>
          ) : error ? (
            <Box p={'12px 20px'}>
              {error.status === 400 ? (
                <Alert color="orange" variant="light">
                  Invalid regex
                </Alert>
              ) : (
                <Alert color="red" variant="light">
                  <Group justify="space-between">
                    <Text size="sm">
                      Search failed. {formatApiError(error)}
                    </Text>
                    <Button variant="subtle" size="xs" onClick={handleRetry}>
                      Retry
                    </Button>
                  </Group>
                </Alert>
              )}
            </Box>
          ) : data && count === 0 ? (
            <Box p={'30px'} ta="center">
              <Text size="lg">
                No programs match "{search.query}"{' '}
                {NO_RESULTS_WINDOW_TEXT[search.window]}
              </Text>
            </Box>
          ) : (
            data?.results.map((result, index) => (
              <ProgramSearchResult
                key={result.id}
                result={result}
                index={index}
                recording={recordingsByProgramId.get(result.id)}
                timeFormat={timeFormat}
                dateFormat={dateFormat}
                onSelect={onSelect}
              />
            ))
          )}
        </Box>

        {!isIdle && !error && count > 0 && (
          <Group gap={5} justify="center" p={8}>
            <Pagination
              total={Math.ceil(count / PROGRAM_SEARCH_PAGE_SIZE)}
              value={search.page}
              onChange={handlePageChange}
              size="xs"
              withEdges
              style={{ paddingRight: 20 }}
            />
            <Text size="xs">{paginationString}</Text>
          </Group>
        )}
      </Box>
    );
  }
);

export default ProgramSearchPanel;
