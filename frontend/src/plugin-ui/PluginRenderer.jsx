import React, { useMemo, useState, useCallback, useEffect, useRef } from 'react';
import {
  Box,
  Stack,
  Group,
  Grid,
  GridCol,
  Card,
  Text,
  Title,
  Divider,
  Badge,
  Button,
  Tabs,
  Accordion,
  Modal,
  Drawer,
  SimpleGrid,
  ScrollArea,
  Table,
  Progress,
  Loader,
  RingProgress,
  Timeline,
  Stepper,
  Image,
  Paper,
  JsonInput,
  Checkbox,
  Switch,
  Radio,
  RadioGroup,
  Select,
  MultiSelect,
  SegmentedControl,
  TextInput,
  Textarea,
  PasswordInput,
  NumberInput,
  ColorInput,
  FileInput,
  Slider,
  RangeSlider,
  Pagination,
  ActionIcon,
  Tooltip,
  Popover,
  Menu,
  LoadingOverlay,
  Skeleton,
  Affix,
  CopyButton,
  Anchor,
  ThemeIcon,
  Avatar,
  HoverCard,
  Highlight,
  Code,
  Kbd,
} from '@mantine/core';
import { DatePickerInput, TimeInput, DateTimePicker } from '@mantine/dates';
import { useForm } from '@mantine/form';
import {
  LineChart as ReLineChart,
  Line,
  BarChart as ReBarChart,
  Bar,
  PieChart as RePieChart,
  Pie,
  Cell,
  Tooltip as ReTooltip,
  Legend as ReLegend,
  CartesianGrid,
  XAxis,
  YAxis,
  AreaChart as ReAreaChart,
  Area,
  ResponsiveContainer,
  RadarChart as ReRadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  ComposedChart as ReComposedChart,
  ScatterChart as ReScatterChart,
  Scatter,
  RadialBarChart as ReRadialBarChart,
  RadialBar,
  Treemap as ReTreemap,
  ReferenceLine,
  ReferenceArea,
  ReferenceDot,
  Brush,
} from 'recharts';
import { useDisclosure } from '@mantine/hooks';
import { Dropzone } from '@mantine/dropzone';
import {
  DndContext,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import {
  SortableContext,
  verticalListSortingStrategy,
  useSortable,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { notifications } from '@mantine/notifications';
import {
  GripVertical,
  Check,
  X,
  Search,
  ChevronDown,
  ChevronRight,
  Play,
  Copy as CopyIcon,
  ExternalLink,
  Settings2,
} from 'lucide-react';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getGroupedRowModel,
  getExpandedRowModel,
  flexRender,
} from '@tanstack/react-table';
import * as LucideIcons from 'lucide-react';
import { usePluginUI } from './PluginContext';
import usePluginDataSource from './hooks/usePluginDataSource';
import { applyTemplate, ensureArray, getByPath, uniqueId, deepMerge, toNumber, safeEntries } from './utils';

const DEFAULT_CARD_PADDING = 'sm';

const resolveIcon = (iconName) => {
  if (!iconName) return null;
  if (typeof iconName === 'function') return iconName;
  const formatted = iconName
    .replace(/[-_](\w)/g, (_, char) => char.toUpperCase())
    .replace(/^(\w)/, (match) => match.toUpperCase());
  return LucideIcons[iconName] || LucideIcons[formatted] || null;
};

const listsMatchById = (a, b, resolver) => {
  if (a === b) return true;
  const left = ensureArray(a);
  const right = ensureArray(b);
  if (left.length !== right.length) return false;
  for (let index = 0; index < left.length; index += 1) {
    const leftValue = left[index];
    const rightValue = right[index];
    const leftId = resolver ? resolver(leftValue) : leftValue?.id ?? leftValue;
    const rightId = resolver ? resolver(rightValue) : rightValue?.id ?? rightValue;
    if (leftId !== rightId) {
      return false;
    }
  }
  return true;
};

const renderChildren = (children, context) => {
  if (!children) return null;
  return ensureArray(children).map((child, index) => (
    <PluginNode key={child?.id || index} node={child} context={context} />
  ));
};

const renderDynamicContent = (value, context) => {
  if (value === null || value === undefined) {
    return null;
  }

  if (React.isValidElement(value) || typeof value === 'string' || typeof value === 'number') {
    return value;
  }

  if (Array.isArray(value)) {
    return renderChildren(value, context);
  }

  if (typeof value === 'object') {
    if (value.type) {
      const rendered = renderChildren([value], context);
      return Array.isArray(rendered) && rendered.length === 1 ? rendered[0] : rendered;
    }
    if (value.content !== undefined) {
      return renderDynamicContent(value.content, context);
    }
  }

  return String(value);
};

const wrapWithTooltip = (node, element, context) => {
  const tooltipConfig = node?.tooltip;
  if (!tooltipConfig) {
    return element;
  }

  const config =
    typeof tooltipConfig === 'string'
      ? { label: tooltipConfig }
      : { withArrow: true, ...tooltipConfig };

  const label = config.label ?? config.content;
  if (!label) {
    return element;
  }

  const { withinPortal = true, ...rest } = config;
  const tooltipProps = { ...rest, withinPortal, label: renderDynamicContent(label, context) };

  return (
    <Tooltip {...tooltipProps}>
      <Box component="span" style={{ display: 'inline-flex', alignItems: 'center' }}>
        {element}
      </Box>
    </Tooltip>
  );
};

const wrapWithPopover = (node, element, context) => {
  const popoverConfig = node?.popover || node?.popOver;
  if (!popoverConfig) {
    return element;
  }

  const config =
    typeof popoverConfig === 'string'
      ? { content: popoverConfig }
      : { withinPortal: true, trapFocus: false, ...popoverConfig };

  const { content, children: popoverChildren, targetProps, ...rest } = config;
  const dropdownContent = renderDynamicContent(content ?? popoverChildren, context);

  if (!dropdownContent) {
    return element;
  }

  return (
    <Popover {...rest}>
      <Popover.Target>
        <Box
          component="span"
          style={{ display: 'inline-flex', alignItems: 'center' }}
          {...targetProps}
        >
          {element}
        </Box>
      </Popover.Target>
      <Popover.Dropdown>{dropdownContent}</Popover.Dropdown>
    </Popover>
  );
};

const wrapWithHoverCard = (node, element, context) => {
  const hoverCardConfig = node?.hoverCard || node?.hovercard;
  if (!hoverCardConfig) {
    return element;
  }

  const config =
    typeof hoverCardConfig === 'string'
      ? { content: hoverCardConfig }
      : { withinPortal: true, openDelay: 150, closeDelay: 100, ...hoverCardConfig };

  const { content, dropdown, children: hoverChildren, targetProps, ...rest } = config;
  const dropdownContent = renderDynamicContent(dropdown ?? hoverChildren ?? content, context);

  if (!dropdownContent) {
    return element;
  }

  return (
    <HoverCard {...rest}>
      <HoverCard.Target>
        <Box
          component="span"
          style={{ display: 'inline-flex', alignItems: 'center' }}
          {...targetProps}
        >
          {element}
        </Box>
      </HoverCard.Target>
      <HoverCard.Dropdown>{dropdownContent}</HoverCard.Dropdown>
    </HoverCard>
  );
};

const resolveNodeLoadingState = (node, context) => {
  if (typeof node?.loading === 'boolean') {
    return node.loading;
  }
  if (typeof node?.isLoading === 'boolean') {
    return node.isLoading;
  }
  if (node?.id && context?.loadingStates && typeof context.loadingStates[node.id] === 'boolean') {
    return context.loadingStates[node.id];
  }
  if (typeof context?.loading === 'boolean') {
    return context.loading;
  }
  return false;
};

const wrapWithLoadingOverlay = (node, element, context) => {
  const overlayConfig = node?.loadingOverlay;
  if (!overlayConfig) {
    return element;
  }

  const config = overlayConfig === true ? { type: 'overlay' } : { type: 'overlay', ...overlayConfig };
  const loadingFlag =
    typeof config.loading === 'boolean' ? config.loading : resolveNodeLoadingState(node, context);

  if (!loadingFlag) {
    return element;
  }

  if ((config.type || 'overlay').toLowerCase() === 'skeleton') {
    const lines = Math.max(Number(config.lines) || 3, 1);
    const height = config.lineHeight || config.height || 16;
    const keepContent = config.keepContent;
    const dim = config.dimContent ?? 0.3;
    return (
      <Stack gap={config.spacing ?? 8}>
        {Array.from({ length: lines }).map((_, idx) => (
          <Skeleton
            key={idx}
            height={height}
            radius={config.radius ?? 'sm'}
            width={config.width}
            animate={config.animate !== false}
          />
        ))}
        {keepContent ? (
          <Box style={{ opacity: config.dimContent === false ? 1 : dim }}>{element}</Box>
        ) : null}
      </Stack>
    );
  }

  return (
    <Box style={{ position: 'relative' }}>
      <LoadingOverlay
        visible
        radius={config.radius ?? 'md'}
        zIndex={config.zIndex ?? 10}
        loaderProps={config.loaderProps}
        overlayProps={config.overlayProps}
        transitionProps={{ transition: 'fade', duration: 150, ...config.transitionProps }}
      />
      {element}
    </Box>
  );
};

const enhanceNodeElement = (node, element, context) => {
  let enhanced = element;
  enhanced = wrapWithTooltip(node, enhanced, context);
  enhanced = wrapWithPopover(node, enhanced, context);
  enhanced = wrapWithHoverCard(node, enhanced, context);
  enhanced = wrapWithLoadingOverlay(node, enhanced, context);
  return enhanced;
};

const FOCUSABLE_SELECTOR =
  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';


const resolveAffixPosition = (affixConfig) => {
  if (!affixConfig) {
    return undefined;
  }

  const offset = affixConfig.offset ?? 16;
  const presetPositions = {
    'top-left': { top: offset, left: offset },
    'top-right': { top: offset, right: offset },
    'bottom-left': { bottom: offset, left: offset },
    'bottom-right': { bottom: offset, right: offset },
    top: { top: offset, left: offset },
    bottom: { bottom: offset, right: offset },
  };

  if (affixConfig.position && typeof affixConfig.position === 'object') {
    return affixConfig.position;
  }

  if (typeof affixConfig.position === 'string') {
    return presetPositions[affixConfig.position] || {
      bottom: offset,
      right: offset,
    };
  }

  return {
    bottom: offset,
    right: offset,
  };
};

const buildThemeIcon = (config, fallbackIcon) => {
  if (!config && !fallbackIcon) {
    return null;
  }

  if (config === false) {
    return null;
  }

  const data =
    typeof config === 'string'
      ? { icon: config }
      : config || { icon: fallbackIcon };

  const IconComponent = resolveIcon(data.icon || fallbackIcon);
  if (!IconComponent) {
    return null;
  }

  const size = data.size || 36;
  return (
    <ThemeIcon
      color={data.color}
      variant={data.variant || 'light'}
      radius={data.radius || 'xl'}
      size={size}
      gradient={data.gradient}
    >
      <IconComponent size={data.iconSize || Math.max(16, size * 0.5)} />
    </ThemeIcon>
  );
};

const buildAvatar = (config, fallbackLabel = '') => {
  if (!config) {
    return null;
  }

  if (config === false) {
    return null;
  }

  const data = typeof config === 'string' ? { initials: config } : config;
  const size = data.size || 36;
  const avatarProps = {
    src: data.src,
    radius: data.radius ?? 'xl',
    size,
    color: data.color,
    variant: data.variant,
    gradient: data.gradient,
    alt: data.alt || fallbackLabel,
  };

  const initials = data.initials || (fallbackLabel ? fallbackLabel.trim().split(/\s+/).map((word) => word[0] || '').join('').slice(0, 2) : undefined);
  const IconComponent = resolveIcon(data.icon);

  return (
    <Avatar {...avatarProps}>
      {IconComponent ? <IconComponent size={data.iconSize || Math.max(16, size * 0.5)} /> : initials}
    </Avatar>
  );
};

const buildAvatarGroup = (config, fallbackLabel = '') => {
  if (!config) {
    return null;
  }

  const groupConfig = Array.isArray(config)
    ? { members: config }
    : config;

  const members = ensureArray(groupConfig.members || groupConfig.items);
  if (!members.length) {
    return null;
  }

  return (
    <Avatar.Group spacing={groupConfig.spacing || 'sm'}>
      {members.map((member, idx) => (
        <React.Fragment key={member?.id || member?.value || idx}>
          {buildAvatar(member, fallbackLabel)}
        </React.Fragment>
      ))}
    </Avatar.Group>
  );
};

const resolveFormatter = (formatter, context, node) => {
  if (!formatter) {
    return undefined;
  }
  if (typeof formatter === 'function') {
    return formatter;
  }
  if (typeof formatter === 'string') {
    if (node?.formatters && typeof node.formatters[formatter] === 'function') {
      return node.formatters[formatter];
    }
    if (context?.formatters && typeof context.formatters[formatter] === 'function') {
      return context.formatters[formatter];
    }
  }
  return undefined;
};

const buildAxisProps = (config, defaults, context, node) => {
  const axisConfig = { ...(defaults || {}), ...(config || {}) };
  if (axisConfig.tickFormatter) {
    const formatter = resolveFormatter(axisConfig.tickFormatter, context, node);
    if (formatter) {
      axisConfig.tickFormatter = formatter;
    }
  }
  if (axisConfig.domainFormatter) {
    const formatter = resolveFormatter(axisConfig.domainFormatter, context, node);
    if (formatter) {
      axisConfig.domain = formatter(axisConfig.domain, axisConfig, node) ?? axisConfig.domain;
    }
  }
  return axisConfig;
};

const renderDefs = (defsConfig) => {
  const defs = ensureArray(defsConfig).filter(Boolean);
  if (!defs.length) {
    return null;
  }

  return (
    <defs>
      {defs.map((definition) => {
        const kind = (definition.kind || definition.type || '').toLowerCase();
        const key = definition.id || definition.key;
        if (!key) return null;
        switch (kind) {
          case 'lineargradient':
            return (
              <linearGradient
                key={key}
                id={definition.id}
                x1={definition.x1 ?? '0%'}
                y1={definition.y1 ?? '0%'}
                x2={definition.x2 ?? '100%'}
                y2={definition.y2 ?? '0%'}
              >
                {ensureArray(definition.stops).map((stop, idx) => (
                  <stop
                    key={`${key}-stop-${idx}`}
                    offset={stop.offset ?? `${(idx / ensureArray(definition.stops).length) * 100}%`}
                    stopColor={stop.color}
                    stopOpacity={stop.opacity}
                  />
                ))}
              </linearGradient>
            );
          case 'radialgradient':
            return (
              <radialGradient
                key={key}
                id={definition.id}
                cx={definition.cx ?? '50%'}
                cy={definition.cy ?? '50%'}
                r={definition.r ?? '50%'}
                fx={definition.fx}
                fy={definition.fy}
              >
                {ensureArray(definition.stops).map((stop, idx) => (
                  <stop
                    key={`${key}-stop-${idx}`}
                    offset={stop.offset ?? `${(idx / ensureArray(definition.stops).length) * 100}%`}
                    stopColor={stop.color}
                    stopOpacity={stop.opacity}
                  />
                ))}
              </radialGradient>
            );
          default:
            return null;
        }
      })}
    </defs>
  );
};

const renderReferenceElements = (referenceConfig, context) => {
  if (!referenceConfig) {
    return null;
  }

  const { lines, areas, dots } = referenceConfig;
  return (
    <>
      {ensureArray(lines).map((line, idx) => (
        <ReferenceLine key={line.id || `ref-line-${idx}`} {...line} />
      ))}
      {ensureArray(areas).map((area, idx) => (
        <ReferenceArea key={area.id || `ref-area-${idx}`} {...area} />
      ))}
      {ensureArray(dots).map((dot, idx) => (
        <ReferenceDot key={dot.id || `ref-dot-${idx}`} {...dot} />
      ))}
    </>
  );
};

const renderBrush = (brushConfig, fallbackDataKey) => {
  if (!brushConfig) {
    return null;
  }

  const config = brushConfig === true ? {} : brushConfig;
  return (
    <Brush
      dataKey={config.dataKey || fallbackDataKey}
      height={config.height || 24}
      travellerWidth={config.travellerWidth || 10}
      stroke={config.stroke || 'var(--mantine-color-blue-5)'}
    />
  );
};

const useActionHandler = () => {
  const { runAction } = usePluginUI();
  return useCallback(
    async (actionConfig = {}, params = {}, options = {}) => {
      const actionId = actionConfig.action || actionConfig.id;
      if (!actionId) {
        console.warn('Action missing id');
        return null;
      }
      const { skipConfirm, ...runOptions } = options || {};
      if (!skipConfirm && actionConfig.confirm) {
        const confirm = actionConfig.confirm;
        let confirmMessage = 'Are you sure?';
        if (typeof confirm === 'string') {
          confirmMessage = confirm;
        } else if (typeof confirm === 'object') {
          confirmMessage = confirm.message || confirm.text || confirm.title || confirmMessage;
        }
        const proceed = window.confirm(confirmMessage);
        if (!proceed) {
          return null;
        }
      }
      const response = await runAction(actionId, params, runOptions);
      if (response?.success && !options.silent) {
        const result = response.result || {};
        const message =
          result.message || actionConfig.successMessage || 'Action executed successfully';
        notifications.show({
          title: result.title || actionConfig.label || 'Plugin action',
          message,
          color: 'green',
        });
        const undoPayload = response.undo || result.undo;
        if (undoPayload) {
          const undoConfig =
            typeof undoPayload === 'string'
              ? { action: undoPayload }
              : undoPayload;
          const undoId = undoConfig.id || `undo-${actionId}`;
          notifications.show({
            id: undoId,
            title: undoConfig.title || 'Undo available',
            color: undoConfig.color || 'teal',
            autoClose: undoConfig.autoClose ?? 7000,
            message: (
              <Group justify="space-between" align="center" gap="sm">
                <Text size="sm">{undoConfig.message || 'Revert this change?'}</Text>
                <Button
                  size="xs"
                  variant={undoConfig.variant || 'light'}
                  color={undoConfig.buttonColor || 'teal'}
                  onClick={() => {
                    runAction(
                      undoConfig.action,
                      undoConfig.params || {},
                      undoConfig.options || {}
                    );
                    notifications.hide(undoId);
                  }}
                >
                  {undoConfig.label || 'Undo'}
                </Button>
              </Group>
            ),
          });
        }
      } else if (response && response.success === false && !options.silent) {
        notifications.show({
          title: actionConfig.label || 'Plugin action',
          message: response.error || 'Action failed',
          color: 'red',
        });
      }
      return response;
    },
    [runAction]
  );
};

const TextNode = ({ node }) => {
  const Component = node.variant ? Text[node.variant] || Text : Text;
  const style = node.style || {};
  const content = node.richText ? (
    <Text dangerouslySetInnerHTML={{ __html: node.content || '' }} style={style} />
  ) : (
    <Text style={style} size={node.size} c={node.color} fw={node.weight} ta={node.align}>
      {node.content}
    </Text>
  );
  if (node.badge) {
    return (
      <Group gap="xs" align="center">
        {content}
        <Badge color={node.badge.color || 'blue'}>{node.badge.label}</Badge>
      </Group>
    );
  }
  return content;
};

const TitleNode = ({ node }) => {
  const order = node.order || 3;
  return (
    <Title order={order} c={node.color} ta={node.align}>
      {node.content}
    </Title>
  );
};

const CardNode = ({ node, context }) => {
  const padding = node.padding || DEFAULT_CARD_PADDING;
  const shadow = node.shadow || 'sm';
  return (
    <Card padding={padding} shadow={shadow} withBorder radius={node.radius || 'md'}>
      {node.title && (
        <Group justify="space-between" mb="sm" align="flex-start">
          <div>
            <Text fw={600}>{node.title}</Text>
            {node.subtitle && (
              <Text size="sm" c="dimmed">
                {node.subtitle}
              </Text>
            )}
          </div>
          {node.badge && (
            <Badge color={node.badge.color || 'gray'}>{node.badge.label}</Badge>
          )}
        </Group>
      )}
      {renderChildren(node.children, context)}
    </Card>
  );
};

const StackNode = ({ node, context }) => (
  <Stack gap={node.spacing || node.gap || 'sm'}>{renderChildren(node.children, context)}</Stack>
);

const GroupNode = ({ node, context }) => (
  <Group gap={node.spacing || node.gap || 'sm'} justify={node.justify} align={node.align} wrap={node.wrap ? 'wrap' : 'nowrap'}>
    {renderChildren(node.children, context)}
  </Group>
);

const BoxNode = ({ node, context }) => {
  const padding = node.padding ?? node.p ?? 'sm';
  const radius = node.radius ?? 'sm';
  const border = node.withBorder ?? node.border;
  const background = node.background ?? node.bg;
  return (
    <Box
      p={padding}
      radius={radius}
      bg={background}
      style={
        border
          ? {
              border: typeof border === 'string' ? border : '1px solid var(--mantine-color-dark-5)',
              ...node.style,
            }
          : node.style
      }
    >
      {renderChildren(node.children, context)}
    </Box>
  );
};

const GridNode = ({ node, context }) => {
  const cols = ensureArray(node.columns || node.children);
  return (
    <Grid gutter={node.gutter || 'md'} grow={node.grow}>
      {cols.map((col, idx) => (
        <GridCol span={col.span || col.size || 12} key={col.id || idx}>
          {renderChildren(col.children || (idx < (node.children?.length || 0) ? [node.children[idx]] : []), context)}
        </GridCol>
      ))}
    </Grid>
  );
};

const SimpleGridNode = ({ node, context }) => {
  const children = ensureArray(node.children);
  return (
    <SimpleGrid
      cols={node.cols || node.columns || 3}
      spacing={node.spacing || 'sm'}
      verticalSpacing={node.verticalSpacing || node.spacing || 'sm'}
      breakpoints={node.breakpoints}
    >
      {children.map((child, idx) => (
        <Box key={child?.id || idx}>{renderChildren(child, context)}</Box>
      ))}
    </SimpleGrid>
  );
};

const VideoPlayerNode = ({ node, context }) => {
  const templateScope = useMemo(() => {
    const scope = {};
    if (context && typeof context === 'object') {
      Object.assign(scope, context);
      if (context.values && typeof context.values === 'object') {
        scope.values = context.values;
      }
      if (context.form) {
        scope.form = context.form;
      }
    }
    return scope;
  }, [context]);

  const coerceUrl = useCallback(
    (value, fallback = '') => {
      if (value === null || value === undefined) return fallback;
      if (typeof value === 'string') {
        const resolved = applyTemplate(value, templateScope);
        return resolved !== undefined && resolved !== null && resolved !== ''
          ? resolved
          : fallback;
      }
      return String(value);
    },
    [templateScope]
  );

  const boundUrl = useMemo(() => {
    if (!node.valuePath) return '';
    const raw = getByPath(templateScope, node.valuePath);
    return coerceUrl(raw);
  }, [coerceUrl, node.valuePath, templateScope]);

  const fallbackUrl = useMemo(() => {
    if (node.urlTemplate) {
      const resolved = coerceUrl(node.urlTemplate);
      if (resolved) return resolved;
    }
    if (node.url) {
      const resolved = coerceUrl(node.url);
      if (resolved) return resolved;
    }
    if (node.defaultUrl) {
      const resolved = coerceUrl(node.defaultUrl);
      if (resolved) return resolved;
    }
    return '';
  }, [coerceUrl, node.defaultUrl, node.url, node.urlTemplate]);

  const allowInput = node.allowInput !== false;

  const initialUrl = boundUrl || fallbackUrl;
  const [inputUrl, setInputUrl] = useState(initialUrl);
  const [inputDirty, setInputDirty] = useState(false);
  const [activeUrl, setActiveUrl] = useState(null);
  const [error, setError] = useState(null);
  const videoRef = useRef(null);

  useEffect(() => {
    const next = boundUrl || fallbackUrl;
    if (!allowInput) {
      if (next && next !== inputUrl) {
        setInputUrl(next);
      }
      return;
    }
    if (!inputDirty && next && next !== inputUrl) {
      setInputUrl(next);
    }
  }, [allowInput, boundUrl, fallbackUrl, inputDirty, inputUrl]);

  useEffect(() => {
    const candidate = boundUrl || fallbackUrl;
    if (!allowInput && candidate) {
      setActiveUrl(candidate);
    }
  }, [allowInput, boundUrl, fallbackUrl]);

  useEffect(() => {
    const videoEl = videoRef.current;
    if (!videoEl) return () => {};
    const handleError = () => {
      const mediaError = videoEl.error;
      if (!mediaError) {
        setError('Unable to play video');
        return;
      }
      switch (mediaError.code) {
        case mediaError.MEDIA_ERR_ABORTED:
          setError('Video playback aborted');
          break;
        case mediaError.MEDIA_ERR_NETWORK:
          setError('Network error while loading video');
          break;
        case mediaError.MEDIA_ERR_DECODE:
          setError('Video decode error – codec not supported');
          break;
        case mediaError.MEDIA_ERR_SRC_NOT_SUPPORTED:
          setError('Video format not supported by this browser');
          break;
        default:
          setError(mediaError.message || 'Unknown video error');
      }
    };
    videoEl.addEventListener('error', handleError);
    return () => {
      videoEl.removeEventListener('error', handleError);
      videoEl.pause();
      videoEl.removeAttribute('src');
      videoEl.load();
    };
  }, []);

  useEffect(() => {
    if (!activeUrl || !videoRef.current) return;
    const videoEl = videoRef.current;
    setError(null);
    videoEl.pause();
    videoEl.src = activeUrl;
    videoEl.load();
    videoEl
      .play()
      .then(() => setError(null))
      .catch((err) => {
        setError(err?.message || 'Auto-play prevented. Use the player controls.');
      });
  }, [activeUrl]);

  const handlePlay = () => {
    const candidateUrl = allowInput ? inputUrl : boundUrl || fallbackUrl;
    const trimmed = (candidateUrl || '').trim();
    if (!trimmed) {
      setError('Enter a video URL first.');
      return;
    }
    setActiveUrl(trimmed);
  };

  return (
    <Stack gap="sm">
      <Box>
        <video
          ref={videoRef}
          controls
          preload="none"
          style={{ width: '100%', borderRadius: 12, background: 'black' }}
          poster={node.poster}
        >
          <track kind="captions" />
        </video>
      </Box>
      {node.helper && (
        <Text size="xs" c="dimmed">
          {node.helper}
        </Text>
      )}
      {error && (
        <Text size="xs" c="red">
          {error}
        </Text>
      )}
      {allowInput ? (
        <Group align="flex-end">
          <TextInput
            label={node.inputLabel || 'Video URL'}
            placeholder={node.placeholder || 'https://example.com/video.mp4'}
            value={inputUrl}
            onChange={(event) => {
              setInputDirty(true);
              setInputUrl(event.currentTarget.value);
            }}
            style={{ flex: 1 }}
          />
          <Button onClick={handlePlay} size={node.buttonSize || 'sm'} leftSection={<Play size={14} />}>
            {node.playLabel || 'Play'}
          </Button>
        </Group>
      ) : (
        <Group align="flex-start" justify="space-between">
          <Stack gap={2} style={{ flex: 1 }}>
            <Text size="xs" c="dimmed">
              {node.inputLabel || 'Video URL'}
            </Text>
            <Text size="sm" style={{ wordBreak: 'break-all' }}>
              {boundUrl || fallbackUrl || inputUrl}
            </Text>
          </Stack>
          <Button onClick={handlePlay} size={node.buttonSize || 'sm'} leftSection={<Play size={14} />}>
            {node.playLabel || 'Play'}
          </Button>
        </Group>
      )}
    </Stack>
  );
};

const PaginationNode = ({ node }) => {
  const total = Math.max(Number(node.total) || 1, 1);
  const siblings = node.siblings ?? 1;
  const boundaries = node.boundaries ?? 1;
  const initialPage = Math.min(Math.max(Number(node.page) || 1, 1), total);
  const [page, setPage] = useState(initialPage);

  return (
    <Pagination
      value={page}
      onChange={(value) => {
        setPage(value);
        if (typeof node.onChange === 'function') {
          node.onChange(value);
        }
      }}
      total={total}
      radius={node.radius || 'md'}
      size={node.size || 'sm'}
      siblings={siblings}
      boundaries={boundaries}
      withControls={node.withControls !== false}
      withEdges={node.withEdges}
    />
  );
};

const ListNode = ({ node }) => {
  const items = ensureArray(node.items);
  return (
    <Stack gap="xs">
      {items.map((item, idx) => (
        <Group key={item.id || idx} justify="space-between">
          <Text>{item.label}</Text>
          {item.badge && <Badge color={item.badge.color || 'blue'}>{item.badge.label}</Badge>}
        </Group>
      ))}
    </Stack>
  );
};

const StatusLight = ({ node, context }) => {
  const sourceOptions = useMemo(
    () => ({
      override: node.dataSource || {},
    }),
    [node.dataSource]
  );

  const { data: sourceData } = usePluginDataSource(node.source, sourceOptions);

  const templateScope = useMemo(() => {
    const scope = {};
    if (context && typeof context === 'object') {
      scope.context = context;
      Object.assign(scope, context);
    }
    if (node.scope && typeof node.scope === 'object') {
      scope.scope = node.scope;
      Object.assign(scope, node.scope);
    }
    if (typeof node.source === 'string') {
      scope[node.source] = sourceData;
    }
    scope.data = sourceData;
    return scope;
  }, [context, node.scope, node.source, sourceData]);

  const statusConfig = node.status || node;

  const resolveField = useCallback(
    (value, path) => {
      if (path) {
        const resolved = getByPath(templateScope, path);
        if (resolved !== undefined) {
          return resolved;
        }
      }
      if (value === null || value === undefined) return value;
      if (typeof value === 'string') {
        return applyTemplate(value, templateScope);
      }
      return value;
    },
    [templateScope]
  );

  const label = resolveField(statusConfig.label, statusConfig.labelPath);
  const description = resolveField(statusConfig.description, statusConfig.descriptionPath);
  const color = resolveField(statusConfig.color, statusConfig.colorPath);

  return (
    <Group gap="xs" align="center">
      <Box
        style={{
          width: 12,
          height: 12,
          borderRadius: 12,
          backgroundColor: color || 'var(--mantine-color-green-5)',
        }}
      />
      <Text size="sm">{label || 'Status'}</Text>
      {description && (
        <Text size="xs" c="dimmed">
          {description}
        </Text>
      )}
    </Group>
  );
};

const ProgressNode = ({ node }) => {
  if (node.variant === 'ring' || node.variant === 'radial') {
    return (
      <RingProgress
        size={node.size || 120}
        thickness={node.thickness || 12}
        sections={[{ value: node.value || 0, color: node.color || 'blue' }]}
        label={
          <Text ta="center" fw={700} size="sm">
            {node.label || `${node.value ?? 0}%`}
          </Text>
        }
      />
    );
  }
  if (node.variant === 'steps') {
    const steps = ensureArray(node.steps);
    return (
      <Stepper active={node.activeStep || 0} orientation={node.orientation || 'horizontal'}>
        {steps.map((step, idx) => {
          const IconComp = resolveIcon(step.icon);
          return (
            <Stepper.Step
              key={step.id || idx}
              label={step.label}
              description={step.description}
              icon={IconComp ? <IconComp size={14} /> : undefined}
            />
          );
        })}
      </Stepper>
    );
  }
  if (node.variant === 'loader' || node.variant === 'spinner') {
    return <Loader size={node.size || 'sm'} color={node.color || 'blue'} />;
  }
  return (
    <Progress value={node.value || 0} color={node.color || 'blue'} striped={node.striped} animated={node.animated} />
  );
};

const LogStreamNode = ({ node }) => {
  const override = useMemo(() => {
    const base = node.dataSource || {};
    const defaults = ensureArray(base.default || node.default || [
      {
        timestamp: '00:00:00',
        level: 'INFO',
        message: 'Waiting for log entries…',
      },
    ]);
    return deepMerge(base, {
      default: defaults,
      subscribe: false,
      limit: node.limit || base.limit,
    });
  }, [node.dataSource, node.default, node.limit]);

  const pollInterval = node.pollInterval ?? node.refreshInterval ?? 5;
  const dataSourceOptions = useMemo(() => {
    const options = {
      override,
      lazy: node.lazy,
    };
    if (pollInterval > 0) {
      options.refreshInterval = pollInterval;
    }
    return options;
  }, [override, node.lazy, pollInterval]);

  const { data } = usePluginDataSource(node.source, dataSourceOptions);
  const items = ensureArray(data);

  const formatEntry = (entry) => {
    if (typeof entry === 'string') {
      return entry;
    }
    if (entry && typeof entry === 'object') {
      const timestamp = entry.timestamp || entry.time || '';
      const level = entry.level ? `[${entry.level}]` : '';
      const message = entry.message ?? entry.text ?? JSON.stringify(entry);
      return [timestamp, level, message].filter(Boolean).join(' ');
    }
    return String(entry ?? '');
  };

  return (
    <ScrollArea h={node.height || 240} type="always">
      <Stack gap={4} p="xs">
        {items.map((entry, idx) => (
          <Text size="xs" ff="monospace" key={idx}>
            {formatEntry(entry)}
          </Text>
        ))}
      </Stack>
    </ScrollArea>
  );
};

const ChartNode = ({ node, context }) => {
  const sourceOptions = useMemo(
    () => ({
      override: node.dataSource || {},
    }),
    [node.dataSource]
  );
  const { data, loading } = usePluginDataSource(node.source, sourceOptions);
  const dataset = ensureArray(data);
  const height = node.height || 260;
  const chartType = (node.chartType || node.type || 'line').toLowerCase();

  if (loading && !dataset.length) {
    return (
      <Group justify="center">
        <Loader size="sm" />
      </Group>
    );
  }

  const defaultXKey = node.xKey || node.x || 'x';
  const defaultYKey = node.yKey || 'y';

  const xAxisProps = buildAxisProps(
    node.xAxis,
    {
      dataKey: defaultXKey,
      type: node.xAxis?.type || node.xType,
      scale: node.xAxis?.scale,
    },
    context,
    node
  );

  const yAxisConfigsInput = node.yAxis || node.yAxes;
  const yAxisConfigs = ensureArray(yAxisConfigsInput && ensureArray(yAxisConfigsInput).length ? yAxisConfigsInput : [{}]).map(
    (axis, index) =>
      buildAxisProps(
        axis,
        {
          dataKey: axis?.dataKey || defaultYKey,
          yAxisId: axis?.yAxisId ?? axis?.id ?? index,
        },
        context,
        node
      )
  );

  const tooltipConfig = typeof node.tooltip === 'object' ? { ...node.tooltip } : {};
  const tooltipFormatter = resolveFormatter(node.tooltipFormatter ?? tooltipConfig.formatter, context, node);
  if (tooltipFormatter) {
    tooltipConfig.formatter = tooltipFormatter;
  }
  const tooltipLabelFormatter = resolveFormatter(node.tooltipLabelFormatter ?? tooltipConfig.labelFormatter, context, node);
  if (tooltipLabelFormatter) {
    tooltipConfig.labelFormatter = tooltipLabelFormatter;
  }
  const tooltipElement = node.tooltip === false ? null : <ReTooltip {...tooltipConfig} />;

  const legendConfig = typeof node.legend === 'object' ? { ...node.legend } : {};
  const legendFormatter = resolveFormatter(node.legendFormatter ?? legendConfig.formatter, context, node);
  if (legendFormatter) {
    legendConfig.formatter = legendFormatter;
  }
  const legendElement = node.legend === false ? null : <ReLegend {...legendConfig} />;

  const defsElement = renderDefs(node.defs);
  const referenceElements = renderReferenceElements(node.reference, context);
  const brushElement = renderBrush(node.brush, xAxisProps.dataKey || defaultXKey);

  const gridConfig = node.grid;
  const gridElement =
    gridConfig === false
      ? null
      : (
          <CartesianGrid
            strokeDasharray="3 3"
            {...(typeof gridConfig === 'object' ? gridConfig : {})}
          />
        );

  const chartProps = {
    data: dataset,
    syncId: node.syncId,
    margin: node.margin,
    barCategoryGap: node.barCategoryGap,
    barGap: node.barGap,
    stackOffset: node.stackOffset,
  };

  const renderCommon = (includeAxes = true) => (
    <>
      {defsElement}
      {gridElement}
      {includeAxes && <XAxis {...xAxisProps} />}
      {includeAxes &&
        yAxisConfigs.map((axisProps, idx) => (
          <YAxis
            key={axisProps.yAxisId || idx}
            {...axisProps}
            yAxisId={axisProps.yAxisId ?? idx}
          />
        ))}
      {tooltipElement}
      {legendElement}
      {referenceElements}
    </>
  );

  const lineSeries = ensureArray(
    node.series || node.lines || [
      {
        dataKey: defaultYKey,
        color: node.color || '#4dabf7',
      },
    ]
  );

  const areaSeries = ensureArray(
    node.series || node.areas || [
      {
        dataKey: defaultYKey,
        color: node.color || '#4dabf7',
      },
    ]
  );

  const barSeries = ensureArray(
    node.series || node.bars || [
      {
        dataKey: defaultYKey,
        color: node.color || '#4dabf7',
      },
    ]
  );

  const pieSeries = ensureArray(
    node.series && node.series.length
      ? node.series
      : [
          {
            data: dataset,
            dataKey: node.valueKey || defaultYKey,
            nameKey: node.labelKey || defaultXKey,
            innerRadius: node.innerRadius,
            outerRadius: node.outerRadius,
            label: node.showLabels,
          },
        ]
  );

  const composedSeries = ensureArray(node.series || []);
  const scatterSeries = ensureArray(node.series || [{ data: dataset, name: node.label || 'Data' }]);

  const renderLineChart = () => (
    <ResponsiveContainer width="100%" height={height}>
      <ReLineChart {...chartProps} {...node.chartProps}>
        {renderCommon(true)}
        {lineSeries.map((series, idx) => (
          <Line
            key={series.id || series.dataKey || idx}
            type={series.type || node.lineType || 'monotone'}
            dataKey={series.dataKey || series.id}
            data={series.data}
            stroke={series.stroke || series.color || node.color || '#4dabf7'}
            strokeWidth={series.strokeWidth || 2}
            dot={series.dots ?? series.dot ?? false}
            activeDot={series.activeDot}
            connectNulls={series.connectNulls ?? node.connectNulls}
            yAxisId={series.yAxisId}
            stackId={series.stackId}
            isAnimationActive={series.animation ?? node.animation}
          />
        ))}
        {brushElement}
      </ReLineChart>
    </ResponsiveContainer>
  );

  const renderAreaChart = () => (
    <ResponsiveContainer width="100%" height={height}>
      <ReAreaChart {...chartProps} {...node.chartProps}>
        {renderCommon(true)}
        {areaSeries.map((series, idx) => (
          <Area
            key={series.id || series.dataKey || idx}
            type={series.type || node.areaType || 'monotone'}
            dataKey={series.dataKey || series.id}
            data={series.data}
            stroke={series.stroke || series.color || node.color || '#4dabf7'}
            fill={series.fill || series.color || node.fill || 'rgba(77, 171, 247, 0.4)'}
            fillOpacity={series.fillOpacity}
            strokeWidth={series.strokeWidth || 2}
            stackId={series.stackId}
            yAxisId={series.yAxisId}
            isAnimationActive={series.animation ?? node.animation}
          />
        ))}
        {brushElement}
      </ReAreaChart>
    </ResponsiveContainer>
  );

  const renderBarChart = () => (
    <ResponsiveContainer width="100%" height={height}>
      <ReBarChart {...chartProps} {...node.chartProps}>
        {renderCommon(true)}
        {barSeries.map((series, idx) => (
          <Bar
            key={series.id || series.dataKey || idx}
            dataKey={series.dataKey || series.id}
            data={series.data}
            fill={series.color || series.fill || node.color || '#4dabf7'}
            stackId={series.stackId}
            barSize={series.barSize}
            radius={series.radius}
            yAxisId={series.yAxisId}
            isAnimationActive={series.animation ?? node.animation}
          />
        ))}
        {brushElement}
      </ReBarChart>
    </ResponsiveContainer>
  );

  const renderComposedChart = () => (
    <ResponsiveContainer width="100%" height={height}>
      <ReComposedChart {...chartProps} {...node.chartProps}>
        {renderCommon(true)}
        {composedSeries.map((series, idx) => {
          const key = series.id || series.dataKey || idx;
          const kind = (series.kind || series.type || 'line').toLowerCase();
          const commonProps = {
            key,
            dataKey: series.dataKey || series.id,
            data: series.data,
            yAxisId: series.yAxisId,
            stackId: series.stackId,
            isAnimationActive: series.animation ?? node.animation,
          };
          switch (kind) {
            case 'area':
              return (
                <Area
                  {...commonProps}
                  type={series.areaType || 'monotone'}
                  stroke={series.stroke || series.color || node.color || '#4dabf7'}
                  fill={series.fill || series.color || node.fill || 'rgba(77, 171, 247, 0.4)'}
                  strokeWidth={series.strokeWidth || 2}
                />
              );
            case 'bar':
              return (
                <Bar
                  {...commonProps}
                  fill={series.fill || series.color || node.color || '#4dabf7'}
                  barSize={series.barSize}
                  radius={series.radius}
                />
              );
            case 'scatter':
              return (
                <Scatter
                  {...commonProps}
                  fill={series.fill || series.color || node.color || '#4dabf7'}
                  shape={series.shape}
                />
              );
            default:
              return (
                <Line
                  {...commonProps}
                  type={series.lineType || 'monotone'}
                  stroke={series.stroke || series.color || node.color || '#4dabf7'}
                  strokeWidth={series.strokeWidth || 2}
                  dot={series.dots ?? false}
                  activeDot={series.activeDot}
                  connectNulls={series.connectNulls ?? node.connectNulls}
                />
              );
          }
        })}
        {brushElement}
      </ReComposedChart>
    </ResponsiveContainer>
  );

  const renderPieChart = () => (
    <ResponsiveContainer width="100%" height={height}>
      <RePieChart {...node.chartProps}>
        {defsElement}
        {tooltipElement}
        {legendElement}
        {pieSeries.map((series, idx) => (
          <Pie
            key={series.id || series.dataKey || idx}
            data={ensureArray(series.data || dataset)}
            dataKey={series.dataKey || node.valueKey || defaultYKey}
            nameKey={series.nameKey || node.labelKey || defaultXKey}
            innerRadius={
              series.innerRadius ?? node.innerRadius ?? (chartType === 'donut' || chartType === 'doughnut' ? 60 : 0)
            }
            outerRadius={series.outerRadius ?? node.outerRadius ?? Math.min(height / 2, 160)}
            startAngle={series.startAngle ?? node.startAngle}
            endAngle={series.endAngle ?? node.endAngle}
            padAngle={series.padAngle ?? node.padAngle}
            cornerRadius={series.cornerRadius ?? node.cornerRadius}
            label={series.label ?? node.showLabels}
          >
            {ensureArray(series.data || dataset).map((entry, entryIdx) => (
              <Cell
                key={`${series.id || idx}-cell-${entryIdx}`}
                fill={entry.color || series.colors?.[entryIdx] || node.colors?.[entryIdx] || series.color || node.color || '#4dabf7'}
              />
            ))}
          </Pie>
        ))}
      </RePieChart>
    </ResponsiveContainer>
  );

  const renderRadarChart = () => (
    <ResponsiveContainer width="100%" height={height}>
      <ReRadarChart data={dataset} {...node.chartProps}>
        <PolarGrid />
        <PolarAngleAxis dataKey={node.xKey || 'subject'} {...node.polarAngleAxis} />
        <PolarRadiusAxis {...node.polarRadiusAxis} />
        <Radar
          name={node.label || 'Series'}
          dataKey={defaultYKey}
          stroke={node.color || '#4dabf7'}
          fill={node.color || '#4dabf7'}
          fillOpacity={node.fillOpacity ?? 0.6}
        />
        {tooltipElement}
        {legendElement}
      </ReRadarChart>
    </ResponsiveContainer>
  );

  const renderScatterChart = () => (
    <ResponsiveContainer width="100%" height={height}>
      <ReScatterChart {...chartProps} {...node.chartProps}>
        {renderCommon(true)}
        {scatterSeries.map((series, idx) => (
          <Scatter
            key={series.id || series.name || idx}
            name={series.name}
            data={ensureArray(series.data || dataset)}
            fill={series.fill || series.color || node.color || '#4dabf7'}
            line={series.line}
            shape={series.shape}
            xAxisId={series.xAxisId}
            yAxisId={series.yAxisId}
            zAxisId={series.zAxisId}
          />
        ))}
        {brushElement}
      </ReScatterChart>
    </ResponsiveContainer>
  );

  const renderRadialBarChart = () => (
    <ResponsiveContainer width="100%" height={height}>
      <ReRadialBarChart
        data={dataset}
        innerRadius={node.innerRadius || 20}
        outerRadius={node.outerRadius || 140}
        startAngle={node.startAngle ?? 90}
        endAngle={node.endAngle ?? -270}
        {...node.chartProps}
      >
        {defsElement}
        {tooltipElement}
        {legendElement}
        <RadialBar
          dataKey={node.valueKey || defaultYKey}
          cornerRadius={node.cornerRadius ?? 4}
          background={node.radialBackground}
          fill={node.color || '#4dabf7'}
        />
      </ReRadialBarChart>
    </ResponsiveContainer>
  );

  const renderTreemap = () => (
    <ResponsiveContainer width="100%" height={height}>
      <ReTreemap
        data={ensureArray(node.series?.[0]?.data || node.data || dataset)}
        dataKey={node.valueKey || 'value'}
        nameKey={node.labelKey || 'name'}
        stroke={node.stroke || '#fff'}
        fill={node.color || '#4dabf7'}
        isAnimationActive={node.animation}
        {...node.chartProps}
      >
        {tooltipElement}
        {legendElement}
      </ReTreemap>
    </ResponsiveContainer>
  );

  const renderHeatmap = () => {
    const rows = ensureArray(dataset);
    return (
      <ScrollArea h={height}>
        <Stack gap={4}>
          {rows.map((row, rowIndex) => (
            <Group key={row.id || rowIndex} gap={4} wrap="nowrap">
              {ensureArray(row.values || row).map((cell, cellIndex) => {
                const value = typeof cell === 'object' ? cell.value : cell;
                const intensity = toNumber(value, 0);
                const max = node.max ?? 100;
                const background = `rgba(77, 171, 247, ${Math.min(intensity / max, 1)})`;
                return (
                  <Box
                    key={cell.id || cellIndex}
                    style={{
                      width: node.cellSize || 24,
                      height: node.cellSize || 24,
                      background,
                      borderRadius: 4,
                    }}
                    title={String(value)}
                  />
                );
              })}
            </Group>
          ))}
        </Stack>
      </ScrollArea>
    );
  };

  switch (chartType) {
    case 'line':
      return renderLineChart();
    case 'area':
      return renderAreaChart();
    case 'bar':
      return renderBarChart();
    case 'composed':
      return renderComposedChart();
    case 'pie':
    case 'donut':
    case 'doughnut':
      return renderPieChart();
    case 'radar':
      return renderRadarChart();
    case 'scatter':
      return renderScatterChart();
    case 'radialbar':
    case 'radial-bar':
      return renderRadialBarChart();
    case 'treemap':
      return renderTreemap();
    case 'heatmap':
      return renderHeatmap();
    default:
      return renderLineChart();
  }
};

const ActionButtonNode = ({ node, context }) => {
  const handleAction = useActionHandler();
  const params = useMemo(() => node.params || {}, [node.params]);
  const label = node.label || node.text || 'Run';
  const icon = resolveIcon(node.icon);

  const actionOptions = useMemo(
    () => node.actionOptions || node.options || {},
    [node.actionOptions, node.options]
  );

  const confirmConfig = useMemo(() => {
    if (!node.confirm) return null;
    if (typeof node.confirm === 'string') {
      return { message: node.confirm };
    }
    if (typeof node.confirm === 'object') {
      return node.confirm;
    }
    return null;
  }, [node.confirm]);

  const [opened, { open, close }] = useDisclosure(false);
  const [submitting, setSubmitting] = useState(false);

  const execute = useCallback(async () => {
    try {
      setSubmitting(true);
      await handleAction(node, params, { ...actionOptions, skipConfirm: true });
      close();
    } finally {
      setSubmitting(false);
    }
  }, [actionOptions, close, handleAction, node, params]);

  const handleClick = () => {
    if (confirmConfig) {
      open();
    } else {
      handleAction(node, params, actionOptions);
    }
  };

  const confirmTitle = confirmConfig?.title || node.label || 'Confirm action';
  const confirmMessage =
    confirmConfig?.message || confirmConfig?.text ||
    (typeof node.confirm === 'string' ? node.confirm : 'Are you sure?');
  const confirmLabel = confirmConfig?.confirmLabel || confirmConfig?.confirmText || 'Confirm';
  const cancelLabel = confirmConfig?.cancelLabel || confirmConfig?.cancelText || 'Cancel';

  const button = (
    <Button
      size={node.size || 'xs'}
      color={node.color || 'blue'}
      variant={node.variant || 'filled'}
      onClick={node.menu ? undefined : handleClick}
      leftSection={icon ? React.createElement(icon, { size: 16 }) : undefined}
      disabled={node.disabled}
      loading={node.loading === true}
    >
      {label}
    </Button>
  );

  const menuConfig = node.menu;
  const buttonWithMenu = useMemo(() => {
    if (!menuConfig) {
      return button;
    }

    const config = typeof menuConfig === 'object' ? menuConfig : { items: ensureArray(menuConfig) };
    const items = ensureArray(config.items ?? []);
    if (!items.length) {
      return button;
    }

    return (
      <Menu
        withinPortal={config.withinPortal !== false}
        shadow={config.shadow || 'md'}
        width={config.width}
        position={config.position || 'bottom-end'}
        offset={config.offset}
        closeOnItemClick={config.closeOnItemClick !== false}
        trigger={config.trigger || 'click'}
      >
        <Menu.Target>{button}</Menu.Target>
        <Menu.Dropdown>
          {items.map((item, idx) => {
            if (!item) {
              return null;
            }
            if (item.type === 'divider') {
              return <Menu.Divider key={`divider-${idx}`} />;
            }
            const ItemIcon = resolveIcon(item.icon);
            const key = item.id || item.key || idx;
            const onItemClick = async (event) => {
              if (item.preventDefault) {
                event.preventDefault();
              }
              if (item.href) {
                if (item.openInNewTab !== false && item.target !== '_self') {
                  window.open(item.href, item.target || '_blank', item.windowFeatures);
                }
                return;
              }
              if (item.onClick && typeof item.onClick === 'function') {
                item.onClick(event, { context, params, node });
                return;
              }
              if (item.action || item.id) {
                await handleAction(item, item.params || {}, item.options || {});
              }
            };

            const itemProps = {
              key,
              icon: ItemIcon ? <ItemIcon size={14} /> : undefined,
              color: item.color,
              leftSection: item.leftSection,
              rightSection: item.rightSection,
              disabled: item.disabled,
            };

            if (item.href) {
              return (
                <Menu.Item
                  component={Anchor}
                  href={item.href}
                  target={item.target || (item.openInNewTab ? '_blank' : undefined)}
                  rel={item.rel}
                  {...itemProps}
                  onClick={onItemClick}
                >
                  {item.label}
                </Menu.Item>
              );
            }

            return (
              <Menu.Item {...itemProps} onClick={onItemClick}>
                {item.label}
              </Menu.Item>
            );
          })}
        </Menu.Dropdown>
      </Menu>
    );
  }, [button, context, handleAction, menuConfig, node, params]);

  return (
    <>
      {buttonWithMenu}
      {confirmConfig && (
        <Modal
          opened={opened}
          onClose={() => (submitting ? null : close())}
          title={confirmTitle}
          centered
        >
          <Stack gap="md">
            <Text size="sm">{confirmMessage}</Text>
            <Group justify="flex-end" gap="sm">
              <Button variant="default" onClick={close} disabled={submitting}>
                {cancelLabel}
              </Button>
              <Button color={node.color || 'red'} onClick={execute} loading={submitting}>
                {confirmLabel}
              </Button>
            </Group>
          </Stack>
        </Modal>
      )}
    </>
  );
};

const ButtonGroupNode = ({ node, context }) => {
  const buttons = ensureArray(node.buttons);

  const handleKeyDown = (event) => {
    if (!['ArrowRight', 'ArrowLeft', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
      return;
    }
    const elements = Array.from(
      event.currentTarget.querySelectorAll('[data-roving-button="true"]')
    );
    if (!elements.length) return;
    const direction = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : -1;
    const currentIndex = elements.findIndex((el) => el === document.activeElement);
    const nextIndex = currentIndex === -1 ? 0 : (currentIndex + direction + elements.length) % elements.length;
    const nextElement = elements[nextIndex];
    if (nextElement) {
      const focusable = nextElement.querySelector(FOCUSABLE_SELECTOR);
      (focusable || nextElement).focus?.();
    }
    event.preventDefault();
  };

  const group = (
    <Group
      gap={node.gap || node.spacing || 'xs'}
      role={node.role || 'toolbar'}
      onKeyDown={handleKeyDown}
    >
      {buttons.map((btn, idx) => {
        const key = btn?.id || idx;
        const element = enhanceNodeElement(btn, <ActionButtonNode node={btn} context={context} />, context);
        return (
          <span key={key} data-roving-button="true" style={{ display: 'inline-flex' }}>
            {element}
          </span>
        );
      })}
    </Group>
  );

  if (!node.affix) {
    return group;
  }

  const affixConfig = typeof node.affix === 'object' ? node.affix : {};
  const position = resolveAffixPosition(affixConfig);
  const content = affixConfig.paper ? (
    <Paper shadow={affixConfig.paper.shadow ?? 'md'} radius={affixConfig.paper.radius ?? 'xl'} p={affixConfig.paper.padding ?? 'xs'}>
      {group}
    </Paper>
  ) : (
    group
  );

  return (
    <Affix position={position} zIndex={affixConfig.zIndex ?? 300} withinPortal={affixConfig.withinPortal !== false}>
      {content}
    </Affix>
  );
};

const CopyNode = ({ node, context }) => {
  const scope = useMemo(() => ({ ...(context || {}), data: context?.data, values: context?.values }), [context]);
  const resolvedValue = useMemo(() => {
    if (typeof node.value === 'string') {
      const templated = applyTemplate(node.value, scope);
      return templated ?? node.value ?? '';
    }
    return node.value ?? '';
  }, [node.value, scope]);

  const CopyIconComponent = resolveIcon(node.copyIcon) || CopyIcon;
  const CopiedIconComponent = resolveIcon(node.copiedIcon) || Check;
  const label = node.label || 'Copy';
  const copiedLabel = node.copiedLabel || 'Copied';

  return (
    <CopyButton value={resolvedValue} timeout={node.timeout ?? 2000} disabled={node.disabled}>
      {({ copied, copy }) => {
        if (node.variant === 'icon' || node.iconOnly) {
          const IconComp = copied ? CopiedIconComponent : CopyIconComponent;
          return (
            <ActionIcon
              size={node.size || 'sm'}
              color={(copied && (node.copiedColor || node.successColor)) || node.color || 'gray'}
              variant={node.variantStyle || 'subtle'}
              onClick={copy}
            >
              {IconComp ? <IconComp size={node.iconSize || 16} /> : null}
            </ActionIcon>
          );
        }

        return (
          <Button
            size={node.size || 'xs'}
            variant={node.variant || 'light'}
            color={(copied && (node.copiedColor || node.successColor)) || node.color || 'blue'}
            leftSection={
              node.showIcon !== false && CopyIconComponent ? (
                <CopyIconComponent size={node.iconSize || 16} />
              ) : undefined
            }
            onClick={copy}
          >
            {copied ? copiedLabel : label}
          </Button>
        );
      }}
    </CopyButton>
  );
};

const LinkNode = ({ node, context }) => {
  const scope = useMemo(() => ({ ...(context || {}), values: context?.values, data: context?.data }), [context]);
  const href = useMemo(() => {
    if (typeof node.href === 'string') {
      const templated = applyTemplate(node.href, scope);
      return templated ?? node.href;
    }
    return node.href || '#';
  }, [node.href, scope]);
  const label = node.label || node.text || href;
  const LeftIcon = resolveIcon(node.icon);
  const fallbackRight = node.external !== false ? ExternalLink : null;
  const RightIcon = resolveIcon(node.rightIcon || (node.external !== false ? 'ExternalLink' : null)) || fallbackRight;

  return (
    <Anchor
      href={href}
      target={node.target || (node.external !== false ? '_blank' : undefined)}
      rel={node.rel || (node.external !== false ? 'noopener noreferrer' : undefined)}
      size={node.size || 'sm'}
      underline={node.underline ?? 'hover'}
      c={node.color}
    >
      <Group gap={node.gap || 6} wrap="nowrap">
        {LeftIcon ? <LeftIcon size={node.iconSize || 14} /> : null}
        <span>{label}</span>
        {RightIcon ? <RightIcon size={node.iconSize || 14} /> : null}
      </Group>
    </Anchor>
  );
};

const HighlightNode = ({ node, context }) => {
  const scope = useMemo(() => ({ ...(context || {}), values: context?.values }), [context]);
  const content = useMemo(() => {
    if (typeof node.content === 'string') {
      const templated = applyTemplate(node.content, scope);
      return templated ?? node.content;
    }
    if (node.text) {
      const templated = applyTemplate(node.text, scope);
      return templated ?? node.text;
    }
    return node.children || '';
  }, [node.children, node.content, node.text, scope]);
  const targets = ensureArray(node.highlight || node.query || node.targets || []);

  return (
    <Highlight
      highlight={targets.length ? targets : undefined}
      highlightColor={node.color || 'yellow'}
      size={node.size || 'sm'}
      fw={node.weight || 500}
    >
      {typeof content === 'string' ? content : renderDynamicContent(content, context)}
    </Highlight>
  );
};

const CodeNode = ({ node, context }) => {
  const content = renderDynamicContent(node.content ?? node.value ?? node.children ?? '', context);
  return (
    <Code block={node.block} color={node.color} radius={node.radius || 'sm'}>
      {content}
    </Code>
  );
};

const KbdNode = ({ node }) => {
  const keys = ensureArray(node.keys || node.value || node.shortcut || node.content).filter(Boolean);
  const separator = node.separator || '+';

  if (keys.length <= 1) {
    return <Kbd>{keys[0] || ''}</Kbd>;
  }

  return (
    <Group gap={4} wrap="nowrap">
      {keys.map((key, idx) => (
        <React.Fragment key={`${key}-${idx}`}>
          <Kbd>{key}</Kbd>
          {idx < keys.length - 1 && (
            <Text size="xs" c="dimmed">
              {separator}
            </Text>
          )}
        </React.Fragment>
      ))}
    </Group>
  );
};

const HoverCardNode = ({ node, context }) => {
  const config = node.config || node;
  const targetContent = config.target || config.trigger || config.label || 'Hover';
  const dropdownContent =
    config.dropdown || config.content || config.children || (node !== config ? node.children : null);

  return (
    <HoverCard
      withinPortal={config.withinPortal !== false}
      openDelay={config.openDelay ?? 150}
      closeDelay={config.closeDelay ?? 120}
      position={config.position || 'top'}
      shadow={config.shadow || 'md'}
    >
      <HoverCard.Target>
        <Box component="span" style={{ display: 'inline-flex', alignItems: 'center' }}>
          {renderDynamicContent(targetContent, context)}
        </Box>
      </HoverCard.Target>
      <HoverCard.Dropdown>
        {renderDynamicContent(dropdownContent ?? node.children ?? node.text, context)}
      </HoverCard.Dropdown>
    </HoverCard>
  );
};

const RichCardList = ({ node, context }) => {
  const dataSourceOptions = useMemo(
    () => ({
      override: node.dataSource || {},
    }),
    [node.dataSource]
  );
  const { data, loading } = usePluginDataSource(node.source, dataSourceOptions);

  const items = useMemo(() => {
    if (Array.isArray(data)) return data;
    if (Array.isArray(data?.items)) return data.items;
    if (Array.isArray(data?.cards)) return data.cards;
    return [];
  }, [data]);

  const cols = node.columns || 3;

  const cardDefaults = useMemo(
    () => ({
      padding: node.cardProps?.padding ?? 'sm',
      radius: node.cardProps?.radius ?? 'md',
      withBorder: node.cardProps?.withBorder ?? true,
      shadow: node.cardProps?.shadow,
    }),
    [node.cardProps]
  );

  if (loading && items.length === 0) {
    return (
      <Group justify="center">
        <Loader size="sm" />
      </Group>
    );
  }
  return (
    <SimpleGrid cols={cols} spacing="sm" verticalSpacing="sm" breakpoints={node.breakpoints}>
      {items.map((item, idx) => {
        const themeIconNode = buildThemeIcon(item.themeIcon, item.icon);
        const avatarNode = buildAvatar(item.avatar, item.title || item.subtitle);
        const avatarGroupNode = buildAvatarGroup(item.avatarGroup, item.title || item.subtitle);
        const leadVisual = avatarGroupNode || avatarNode || themeIconNode;

        return (
          <Card
            key={item.id || idx}
            padding={item.padding || cardDefaults.padding}
            radius={item.radius || cardDefaults.radius}
            withBorder={item.withBorder ?? cardDefaults.withBorder}
            shadow={item.shadow || cardDefaults.shadow}
          >
            <Stack gap="xs">
              {node.showImage !== false && item.image ? (
                <Image
                  src={item.image}
                  alt={item.imageAlt || item.title || 'item'}
                  radius={item.imageRadius || node.imageRadius || 'sm'}
                  h={item.imageHeight || node.imageHeight || 140}
                  fit={item.imageFit || node.imageFit || 'cover'}
                />
              ) : null}
              <Group justify="space-between" align="flex-start">
                <Group gap="sm" align="flex-start">
                  {leadVisual}
                  <Stack gap={2}>
                    <Text fw={600}>{item.title}</Text>
                    {item.subtitle && (
                      <Text size="sm" c="dimmed">
                        {item.subtitle}
                      </Text>
                    )}
                  </Stack>
                </Group>
                {item.badge && (
                  <Badge color={item.badge.color || 'blue'}>{item.badge.label}</Badge>
                )}
              </Group>
              {item.description && <Text size="sm">{item.description}</Text>}
              {item.meta && typeof item.meta === 'object' && (
                <Stack gap={4}>
                  {safeEntries(item.meta).map(([key, value]) => (
                    <Group key={key} gap={6} justify="space-between">
                      <Text size="xs" c="dimmed">
                        {key}
                      </Text>
                      <Text size="xs">{String(value)}</Text>
                    </Group>
                  ))}
                </Stack>
              )}
              {item.actions && <ButtonGroupNode node={{ buttons: item.actions }} context={context} />}
            </Stack>
          </Card>
        );
      })}
    </SimpleGrid>
  );
};

const TableNode = ({ node, context }) => {
  const handleAction = useActionHandler();
  const dataSourceOptions = useMemo(
    () => ({
      override: node.dataSource || {},
    }),
    [node.dataSource]
  );
  const { data, loading } = usePluginDataSource(node.source, dataSourceOptions);

  const rows = useMemo(() => {
    if (!data) return [];
    if (Array.isArray(data)) return data;
    if (Array.isArray(data?.rows)) return data.rows;
    if (Array.isArray(data?.items)) return data.items;
    return [data];
  }, [data]);

  const selectionConfig = typeof node.selection === 'object' ? node.selection : {};
  const selectionEnabled = node.selection === false ? false : Boolean(node.selection ?? selectionConfig.enabled ?? node.bulkActions?.length);
  const bulkActions = ensureArray(selectionConfig.bulkActions || node.bulkActions);

  const virtualizationConfig = typeof node.virtualize === 'object' ? node.virtualize : node.virtualize ? {} : null;
  const virtualize = Boolean(virtualizationConfig);
  const virtualHeight = virtualizationConfig?.height || node.bodyHeight || node.height;

  const serverSide = node.serverSide === true;

  const [sorting, setSorting] = useState(node.initialSort || []);
  const [globalFilter, setGlobalFilter] = useState('');
  const [pageIndex, setPageIndex] = useState(0);
  const [pageSize, setPageSize] = useState(node.pageSize || node.pagination?.pageSize || 10);
  const [expandedRow, setExpandedRow] = useState(null);
  const [rowSelection, setRowSelection] = useState({});
  const [columnVisibility, setColumnVisibility] = useState(node.columnVisibility || {});
  const [columnPinning, setColumnPinning] = useState(node.columnPinning || { left: [], right: [] });
  const [columnSizing, setColumnSizing] = useState(node.columnSizing || {});
  const [columnFilters, setColumnFilters] = useState([]);
  const [grouping, setGrouping] = useState(node.grouping || node.initialGrouping || []);
  const [editingValues, setEditingValues] = useState({});
  const [editingBusy, setEditingBusy] = useState({});

  const toggleExpand = useCallback((rowId) => {
    setExpandedRow((prev) => (prev === rowId ? null : rowId));
  }, []);

  const customFilterFns = useMemo(
    () => ({
      arrIncludes: (row, columnId, filterValue) => {
        if (!filterValue || !filterValue.length) return true;
        const rowValue = row.getValue(columnId);
        const values = Array.isArray(rowValue) ? rowValue : [rowValue];
        return ensureArray(filterValue).every((value) => values.includes(value));
      },
      between: (row, columnId, filterValue) => {
        if (!filterValue) return true;
        const [min, max] = filterValue;
        const rawValue = Number(row.getValue(columnId));
        if (Number.isNaN(rawValue)) return false;
        if (min !== undefined && min !== '' && rawValue < Number(min)) return false;
        if (max !== undefined && max !== '' && rawValue > Number(max)) return false;
        return true;
      },
    }),
    []
  );

  const buildActions = useCallback(
    (actions, row, value) => {
      const scope = { row, value, context };
      const resolved = ensureArray(actions).map((action) => {
        const next = { ...action };
        if (action.params) {
          next.params = applyTemplate(action.params, scope);
        } else if (!next.params) {
          next.params = { rowId: row.id };
        }
        if (action.confirm) {
          if (typeof action.confirm === 'string') {
            next.confirm = applyTemplate(action.confirm, scope);
          } else if (typeof action.confirm === 'object') {
            const confirmConfig = { ...action.confirm };
            if (confirmConfig.message) {
              confirmConfig.message = applyTemplate(confirmConfig.message, scope);
            }
            if (confirmConfig.text) {
              confirmConfig.text = applyTemplate(confirmConfig.text, scope);
            }
            if (confirmConfig.title) {
              confirmConfig.title = applyTemplate(confirmConfig.title, scope);
            }
            if (confirmConfig.confirmLabel) {
              confirmConfig.confirmLabel = applyTemplate(confirmConfig.confirmLabel, scope);
            }
            if (confirmConfig.cancelLabel) {
              confirmConfig.cancelLabel = applyTemplate(confirmConfig.cancelLabel, scope);
            }
            next.confirm = confirmConfig;
          }
        }
        return next;
      });
      return <ButtonGroupNode node={{ buttons: resolved }} context={context} />;
    },
    [context]
  );

  const commitEdit = useCallback(
    async ({ row, columnId, value: nextValue, columnConfig, editKey }) => {
      const actionConfig = columnConfig?.onEditAction || node.onEditAction;
      if (!actionConfig) return;
      const actionNode = typeof actionConfig === 'string' ? { action: actionConfig } : actionConfig;
      setEditingBusy((prev) => ({ ...prev, [editKey]: true }));
      try {
        await handleAction(actionNode, {
          value: nextValue,
          columnId,
          column: columnConfig,
          row,
          rowId: row?.id ?? row?.key,
        });
      } finally {
        setEditingBusy((prev) => {
          const next = { ...prev };
          delete next[editKey];
          return next;
        });
      }
    },
    [handleAction, node.onEditAction]
  );

  const getEditKey = useCallback((rowId, columnId) => `${rowId}::${columnId}`, []);

  const renderEditableCell = useCallback(
    (info, col) => {
      const value = info.getValue();
      const row = info.row.original;
      const rowId = info.row.id;
      const columnId = info.column.id;
      const editKey = getEditKey(rowId, columnId);
      const currentValue = editingValues[editKey] ?? value ?? '';
      const isBusy = Boolean(editingBusy[editKey]);
      const editorType = (col.editor || col.editType || 'text').toLowerCase();

      const stop = (event) => event.stopPropagation();

      const handleValueChange = (nextVal) => {
        setEditingValues((prev) => ({ ...prev, [editKey]: nextVal }));
      };

      const finalize = async () => {
        if (col.saveOnBlur === false) return;
        await commitEdit({ row, columnId, value: editingValues[editKey] ?? value, columnConfig: col, editKey });
        if (col.resetAfterSave !== false) {
          setEditingValues((prev) => {
            const next = { ...prev };
            delete next[editKey];
            return next;
          });
        }
      };

      const handleKeyDown = async (event) => {
        if (event.key === 'Enter' && (col.saveOnEnter ?? true)) {
          event.preventDefault();
          await commitEdit({ row, columnId, value: editingValues[editKey] ?? value, columnConfig: col, editKey });
        }
      };

      const commonProps = {
        size: col.editorSize || 'xs',
        disabled: isBusy,
        onClick: stop,
        onKeyDown: handleKeyDown,
        onBlur: finalize,
      };

      if (editorType === 'number') {
        return (
          <NumberInput
            value={currentValue === null || currentValue === undefined ? undefined : Number(currentValue)}
            min={col.min}
            max={col.max}
            step={col.step}
            {...commonProps}
            onChange={(val) => handleValueChange(val)}
          />
        );
      }

      if (editorType === 'select') {
        const options = ensureArray(col.options).map((opt) =>
          typeof opt === 'object'
            ? { value: String(opt.value ?? opt.id), label: opt.label ?? String(opt.value ?? opt.id) }
            : { value: String(opt), label: String(opt) }
        );
        return (
          <Select
            data={options}
            value={currentValue ? String(currentValue) : null}
            {...commonProps}
            onChange={(val) => {
              handleValueChange(val);
              if (col.saveOnChange) {
                commitEdit({ row, columnId, value: val, columnConfig: col, editKey });
              }
            }}
            clearable={col.clearable}
            searchable={col.searchable}
          />
        );
      }

      if (editorType === 'checkbox' || editorType === 'switch') {
        const checked = Boolean(currentValue);
        const Component = editorType === 'switch' ? Switch : Checkbox;
        return (
          <Component
            checked={checked}
            onClick={stop}
            onChange={(event) => {
              const nextVal = editorType === 'switch' ? event.currentTarget.checked : event.currentTarget.checked;
              handleValueChange(nextVal);
              if (col.saveOnChange !== false) {
                commitEdit({ row, columnId, value: nextVal, columnConfig: col, editKey });
              }
            }}
          />
        );
      }

      return (
        <TextInput
          value={currentValue ?? ''}
          placeholder={col.placeholder}
          {...commonProps}
          onChange={(event) => handleValueChange(event.currentTarget.value)}
        />
      );
    },
    [commitEdit, editingBusy, editingValues, getEditKey]
  );

  const columns = useMemo(() => {
    const defs = [];

    if (selectionEnabled) {
      defs.push({
        id: '__select',
        header: ({ table }) => (
          <Checkbox
            size="xs"
            checked={table.getIsAllPageRowsSelected()}
            indeterminate={table.getIsSomePageRowsSelected()}
            onChange={table.getToggleAllPageRowsSelectedHandler()}
          />
        ),
        cell: ({ row }) => (
          <Checkbox
            size="xs"
            checked={row.getIsSelected()}
            indeterminate={row.getIsSomeSelected()}
            onChange={row.getToggleSelectedHandler()}
            onClick={(event) => event.stopPropagation()}
          />
        ),
        enableSorting: false,
        enableColumnFilter: false,
        enableResizing: false,
        size: 36,
      });
    }

    if (node.expandable) {
      defs.push({
        id: '__expand',
        header: '',
        size: 36,
        enableSorting: false,
        cell: ({ row }) => (
          <ActionIcon
            size="sm"
            variant="subtle"
            onClick={(event) => {
              event.stopPropagation();
              toggleExpand(row.id);
            }}
          >
            {expandedRow === row.id ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          </ActionIcon>
        ),
      });
    }

    const columnSpecs = ensureArray(node.columns);

    columnSpecs.forEach((col) => {
      const filterFn = typeof col.filterFn === 'function' ? col.filterFn : col.filterFn || col.filter;
      defs.push({
        id: col.id || col.accessor || col.field,
        accessorKey: col.accessor || col.field || col.id,
        header: col.label || col.title || col.id,
        enableSorting: col.sortable !== false,
        enableColumnFilter: col.filter !== false,
        filterFn: typeof filterFn === 'string' ? filterFn : undefined,
        meta: { config: col },
        aggregationFn: col.aggregationFn,
        enableHiding: col.hideable !== false,
        enableColumnPinning: col.pinnable !== false,
        enableResizing: col.resizable !== false,
        size: col.width,
        minSize: col.minWidth,
        maxSize: col.maxWidth,
        cell: (info) => {
          if (col.editable) {
            return renderEditableCell(info, col);
          }
          const value = info.getValue();
          const row = info.row.original;
          if (col.actions || col.type === 'actions') {
            return buildActions(col.actions || node.rowActions, row, value);
          }
          if (col.badge) {
            const badgeConfig = typeof col.badge === 'object' ? col.badge : {};
            const badgeColor = badgeConfig.colors?.[value] || badgeConfig.color || 'gray';
            return <Badge color={badgeColor}>{value}</Badge>;
          }
          if (col.render === 'progress') {
            return <Progress value={toNumber(value)} color={col.color || 'blue'} striped={col.striped} />;
          }
          if (col.render === 'status') {
            return <StatusLight node={{ status: typeof value === 'object' ? value : { label: value } }} />;
          }
          if (col.format === 'datetime' && value) {
            return new Date(value).toLocaleString();
          }
          if (col.format === 'date' && value) {
            return new Date(value).toLocaleDateString();
          }
          if (col.format === 'time' && value) {
            return new Date(value).toLocaleTimeString();
          }
          if (col.template) {
            return applyTemplate(col.template, { row, value });
          }
          if (col.render === 'json') {
            try {
              return (
                <JsonInput
                  value={JSON.stringify(value, null, 2)}
                  readOnly
                  autosize
                  minRows={2}
                  formatOnBlur
                />
              );
            } catch {
              return String(value);
            }
          }
          const displayValue = value ?? col.emptyValue ?? '';
          if (col.prefix || col.suffix) {
            return `${col.prefix ?? ''}${displayValue}${col.suffix ?? ''}`;
          }
          return String(displayValue);
        },
      });
    });

    if (node.rowActions && !columnSpecs.some((col) => col.type === 'actions')) {
      defs.push({
        id: '__actions',
        header: '',
        enableSorting: false,
        cell: ({ row }) => buildActions(node.rowActions, row.original, null),
      });
    }

    return defs;
  }, [buildActions, expandedRow, node.columns, node.rowActions, node.expandable, renderEditableCell, selectionEnabled, toggleExpand]);

  const table = useReactTable({
    data: rows,
    columns,
    state: {
      sorting,
      globalFilter,
      pagination: {
        pageIndex,
        pageSize,
      },
      rowSelection,
      columnVisibility,
      columnPinning,
      columnSizing,
      columnFilters,
      grouping,
    },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    onRowSelectionChange: setRowSelection,
    onColumnVisibilityChange: setColumnVisibility,
    onColumnPinningChange: setColumnPinning,
    onColumnSizingChange: setColumnSizing,
    onColumnFiltersChange: setColumnFilters,
    onGroupingChange: setGrouping,
    getRowId: (originalRow, index) =>
      originalRow?.id?.toString?.() || originalRow?.key?.toString?.() || `${index}`,
    filterFns: customFilterFns,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getGroupedRowModel: getGroupedRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
    globalFilterFn: 'includesString',
    enableRowSelection: selectionEnabled,
    enableColumnResizing: node.resizable !== false,
    columnResizeMode: node.columnResizeMode || 'onChange',
    manualPagination: serverSide,
    manualSorting: serverSide,
    manualFiltering: serverSide,
    manualGrouping: serverSide,
    autoResetPageIndex: !serverSide,
  });

  const tableRows = table.getRowModel().rows;

  useEffect(() => {
    if (!serverSide) return;
    const payload = {
      sorting,
      pagination: { pageIndex, pageSize },
      columnFilters,
      columnVisibility,
      columnPinning,
      grouping,
    };
    if (typeof node.onStateChange === 'function') {
      node.onStateChange(payload, { table, context });
    } else if (node.onStateChangeAction) {
      const actionConfig =
        typeof node.onStateChangeAction === 'string'
          ? { action: node.onStateChangeAction }
          : node.onStateChangeAction;
      handleAction(actionConfig, payload, node.onStateChangeOptions || {});
    }
  }, [columnFilters, columnPinning, columnVisibility, context, handleAction, grouping, node.onStateChange, node.onStateChangeAction, node.onStateChangeOptions, pageIndex, pageSize, serverSide, sorting, table]);

  const renderColumnFilterControl = (header) => {
    const column = header.column;
    const columnMeta = column.columnDef.meta?.config || {};
    const filterType = (columnMeta.filterType || columnMeta.filter || column.columnDef.filterType || '').toLowerCase();
    const filterValue = column.getFilterValue();
    const stop = (event) => event.stopPropagation();

    if (filterType === 'select') {
      const options = ensureArray(columnMeta.options).map((opt) =>
        typeof opt === 'object'
          ? { value: String(opt.value ?? opt.id), label: opt.label ?? String(opt.value ?? opt.id) }
          : { value: String(opt), label: String(opt) }
      );
      return (
        <Select
          size="xs"
          data={options}
          value={filterValue ? String(filterValue) : null}
          onChange={(val) => column.setFilterValue(val || undefined)}
          placeholder={columnMeta.filterPlaceholder || 'Select'}
          clearable
          onClick={stop}
        />
      );
    }

    if (filterType === 'multi-select') {
      const options = ensureArray(columnMeta.options).map((opt) =>
        typeof opt === 'object'
          ? { value: String(opt.value ?? opt.id), label: opt.label ?? String(opt.value ?? opt.id) }
          : { value: String(opt), label: String(opt) }
      );
      return (
        <MultiSelect
          size="xs"
          data={options}
          value={Array.isArray(filterValue) ? filterValue.map(String) : []}
          onChange={(val) => column.setFilterValue(val.length ? val : undefined)}
          placeholder={columnMeta.filterPlaceholder || 'Filter'}
          searchable
          onClick={stop}
        />
      );
    }

    if (filterType === 'between') {
      const [min, max] = Array.isArray(filterValue) ? filterValue : ['', ''];
      return (
        <Group gap={4} wrap="nowrap">
          <NumberInput
            size="xs"
            value={min === undefined ? undefined : Number(min)}
            placeholder="Min"
            onClick={stop}
            onChange={(val) => column.setFilterValue([val, max])}
          />
          <NumberInput
            size="xs"
            value={max === undefined ? undefined : Number(max)}
            placeholder="Max"
            onClick={stop}
            onChange={(val) => column.setFilterValue([min, val])}
          />
        </Group>
      );
    }

    return (
      <TextInput
        size="xs"
        value={filterValue ?? ''}
        onChange={(event) => column.setFilterValue(event.currentTarget.value || undefined)}
        placeholder={columnMeta.filterPlaceholder || 'Filter'}
        onClick={stop}
      />
    );
  };

  const renderExpanded = (row) => {
    if (!node.expandable) return null;
    const fields = ensureArray(node.expandable.fields);
    if (fields.length > 0) {
      return (
        <Stack gap="xs" mt="xs">
          {fields.map((field) => (
            <Group key={field.path || field.id || field.label} gap="sm" align="flex-start">
              <Text fw={600} size="sm">
                {field.label || field.path}
              </Text>
              <Text size="sm">
                {String(getByPath(row.original, field.path || field.id || field.label) ?? '')}
              </Text>
            </Group>
          ))}
        </Stack>
      );
    }
    return (
      <JsonInput
        value={JSON.stringify(row.original, null, 2)}
        readOnly
        autosize
        minRows={3}
        formatOnBlur
      />
    );
  };

  const pageCount = table.getPageCount();
  const selectedRows = table.getSelectedRowModel().rows;

  const mappedBulkActions = bulkActions.map((action) => ({
    ...action,
    params: {
      ...(action.params || {}),
      rows: selectedRows.map((row) => row.original),
      rowIds: selectedRows.map((row) => row.id),
    },
  }));

  const columnToggleMenu = node.columnControls === false
    ? null
    : (
        <Menu withinPortal>
          <Menu.Target>
            <ActionIcon variant="subtle" aria-label="Toggle columns">
              <Settings2 size={16} />
            </ActionIcon>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Label>Columns</Menu.Label>
            {table
              .getAllLeafColumns()
              .filter((column) => column.getCanHide())
              .map((column) => (
                <Menu.Item
                  key={column.id}
                  closeMenuOnClick={false}
                  onClick={(event) => {
                    event.preventDefault();
                    column.toggleVisibility();
                  }}
                >
                  <Group gap={6} align="center">
                    <Checkbox readOnly checked={column.getIsVisible()} />
                    <Text size="sm">{column.columnDef.header || column.id}</Text>
                  </Group>
                </Menu.Item>
              ))}
          </Menu.Dropdown>
        </Menu>
      );

  const stickyHeader = node.sticky?.header ?? node.sticky === 'header';
  const stickyOffset = node.sticky?.offset ?? 0;

  const renderRowCells = (row) =>
    row.getVisibleCells().map((cell) => (
      <Table.Td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</Table.Td>
    ));

  const renderTableBody = () => {
    return (
      <Table.Tbody>
        {loading && rows.length === 0 && (
          <Table.Tr>
            <Table.Td colSpan={table.getAllLeafColumns().length}>
              <Group justify="center" my="md">
                <Loader size="sm" />
              </Group>
            </Table.Td>
          </Table.Tr>
        )}
        {tableRows.map((row) => (
          <React.Fragment key={row.id}>
            <Table.Tr>
              {renderRowCells(row)}
            </Table.Tr>
            {expandedRow === row.id && node.expandable && (
              <Table.Tr>
                <Table.Td colSpan={row.getVisibleCells().length}>{renderExpanded(row)}</Table.Td>
              </Table.Tr>
            )}
          </React.Fragment>
        ))}
      </Table.Tbody>
    );
  };

  const tableElement = (
    <Table
      withColumnBorders={node.columnBorders}
      highlightOnHover={node.highlight !== false}
      striped={node.striped !== false && node.striped !== undefined}
      stickyHeader={stickyHeader}
      stickyHeaderOffset={stickyOffset}
      style={{ tableLayout: node.tableLayout || 'auto' }}
    >
      <Table.Thead>
        {table.getHeaderGroups().map((headerGroup) => (
          <Table.Tr key={headerGroup.id}>
            {headerGroup.headers.map((header) => {
              const sortStatus = header.column.getIsSorted();
              const sortIndicator = sortStatus === 'asc' ? '▲' : sortStatus === 'desc' ? '▼' : null;
              return (
                <Table.Th
                  key={header.id}
                  w={header.getSize()}
                  onClick={header.column.getCanSort() ? header.column.getToggleSortingHandler() : undefined}
                  style={{ cursor: header.column.getCanSort() ? 'pointer' : 'default', position: 'relative' }}
                >
                  <Stack gap={4}>
                    <Group gap={4} align="center">
                      <Box>{flexRender(header.column.columnDef.header, header.getContext())}</Box>
                      {sortIndicator ? <Text size="xs">{sortIndicator}</Text> : null}
                    </Group>
                    {header.column.getCanFilter() && node.columnFilters !== false
                      ? renderColumnFilterControl(header)
                      : null}
                  </Stack>
                  {header.column.getCanResize() ? (
                    <Box
                      onMouseDown={header.getResizeHandler()}
                      onTouchStart={header.getResizeHandler()}
                      style={{
                        position: 'absolute',
                        right: 0,
                        top: 0,
                        height: '100%',
                        width: 6,
                        cursor: 'col-resize',
                        userSelect: 'none',
                      }}
                    />
                  ) : null}
                </Table.Th>
              );
            })}
          </Table.Tr>
        ))}
      </Table.Thead>
      {renderTableBody()}
    </Table>
  );

  return (
    <Stack gap="sm">
      {(node.filterable !== false || columnToggleMenu || (selectionEnabled && selectedRows.length > 0 && mappedBulkActions.length > 0)) && (
        <Group justify="space-between" align="flex-start" gap="sm">
          {node.filterable !== false ? (
            <TextInput
              label={node.filterLabel || 'Filter'}
              placeholder={node.filterPlaceholder || 'Search'}
              value={globalFilter}
              onChange={(event) => {
                const value = event.currentTarget.value;
                setGlobalFilter(value);
                table.setGlobalFilter(value);
                setPageIndex(0);
              }}
              style={{ flex: 1 }}
            />
          ) : (
            <Box />
          )}
          <Group gap="xs">
            {columnToggleMenu}
          </Group>
        </Group>
      )}

      {selectionEnabled && selectedRows.length > 0 && mappedBulkActions.length > 0 && (
        <Group justify="space-between" align="center">
          <Text size="sm">{selectedRows.length} selected</Text>
          <ButtonGroupNode node={{ buttons: mappedBulkActions }} context={context} />
        </Group>
      )}

      {virtualize ? (
        <Box
          style={{
            maxHeight: virtualHeight || 360,
            overflowY: 'auto',
            overflowX: 'auto',
            borderRadius: 8,
            border: '1px solid var(--mantine-color-gray-3)',
          }}
        >
          {tableElement}
        </Box>
      ) : (
        tableElement
      )}

      {node.pagination !== false && pageCount > 1 && (
        <Group justify="space-between" align="center">
          <Select
            label="Page size"
            value={String(pageSize)}
            data={(node.pageSizes || [10, 20, 50, 100]).map((size) => ({ value: String(size), label: `${size}` }))}
            onChange={(val) => {
              const size = Number(val || pageSize);
              setPageSize(size);
              setPageIndex(0);
              table.setPageSize(size);
            }}
            style={{ width: 140 }}
          />
          <Pagination
            value={pageIndex + 1}
            total={pageCount}
            onChange={(page) => {
              setPageIndex(page - 1);
              table.setPageIndex(page - 1);
            }}
          />
        </Group>
      )}
    </Stack>
  );
};

const FormField = ({ field, form }) => {
  const commonProps = {
    label: field.label,
    description: field.help_text,
    placeholder: field.placeholder,
    required: field.required,
    withAsterisk: field.required,
  };
  const fieldName = field.id;
  const value = form.values[fieldName];
  const optionsSourceId = field.optionsSource || field.optionsResource || field.optionsDataSource;
  const rawOptionsSourceConfig = field.optionsSourceOptions || field.optionsDataSourceConfig || null;

  const staticOptions = useMemo(() => ensureArray(field.options), [field.options]);

  const resourceConfig = useMemo(() => {
    if (!optionsSourceId) {
      return null;
    }
    const base = {
      id: `form-options:${optionsSourceId}`,
      type: 'resource',
      resource: optionsSourceId,
    };
    if (rawOptionsSourceConfig && typeof rawOptionsSourceConfig === 'object') {
      return { ...base, ...rawOptionsSourceConfig };
    }
    return base;
  }, [optionsSourceId, rawOptionsSourceConfig]);

  const dataSourceConfig = useMemo(() => {
    if (resourceConfig) {
      return resourceConfig;
    }
    return {
      id: `form-options-static:${fieldName}`,
      type: 'static',
      data: staticOptions,
    };
  }, [fieldName, resourceConfig, staticOptions]);

  const optionsDataSourceOptions = useMemo(() => {
    if (resourceConfig) {
      return {
        override: rawOptionsSourceConfig || undefined,
      };
    }
    return { lazy: true };
  }, [rawOptionsSourceConfig, resourceConfig]);

  const optionsSource = usePluginDataSource(
    dataSourceConfig,
    optionsDataSourceOptions
  );

  const optionsData = optionsSource?.data;

  const normalizeOption = useCallback((option) => {
    if (option === null || option === undefined) return null;
    if (typeof option === 'string') {
      return { value: option, label: option };
    }
    if (typeof option === 'object') {
      const valueCandidate =
        option.value ?? option.id ?? option.key ?? option.slug ?? option.name;
      if (valueCandidate === undefined || valueCandidate === null) {
        return null;
      }
      const label = option.label ?? option.name ?? String(valueCandidate);
      const normalized = {
        value: String(valueCandidate),
        label,
      };
      if (option.description) {
        normalized.description = option.description;
      }
      return normalized;
    }
    return null;
  }, []);

  const resolvedOptions = useMemo(() => {
    const collected = [];
    const pushOptions = (items) => {
      ensureArray(items).forEach((entry) => {
        const normalized = normalizeOption(entry);
        if (normalized) {
          collected.push(normalized);
        }
      });
    };

    const baseOptions = optionsData ?? staticOptions;
    if (Array.isArray(baseOptions)) {
      pushOptions(baseOptions);
    } else if (baseOptions && typeof baseOptions === 'object') {
      if (Array.isArray(baseOptions.items)) {
        pushOptions(baseOptions.items);
      }
      if (Array.isArray(baseOptions.options)) {
        pushOptions(baseOptions.options);
      }
    }

    return collected;
  }, [normalizeOption, optionsData, staticOptions]);

  switch ((field.type || 'text').toLowerCase()) {
    case 'textarea':
    case 'multiline':
      return <Textarea {...commonProps} autosize minRows={field.minRows || 3} {...form.getInputProps(fieldName)} />;
    case 'password':
      return <PasswordInput {...commonProps} {...form.getInputProps(fieldName)} />;
    case 'search':
      return <TextInput {...commonProps} leftSection={<Search size={14} />} {...form.getInputProps(fieldName)} />;
    case 'number':
      return (
        <NumberInput
          {...commonProps}
          min={field.min}
          max={field.max}
          step={field.step}
          allowDecimal={field.allowDecimal}
          {...form.getInputProps(fieldName)}
        />
      );
    case 'slider':
      return (
        <Slider
          {...commonProps}
          value={value}
          min={field.min ?? 0}
          max={field.max ?? 100}
          step={field.step ?? 1}
          onChange={(val) => form.setFieldValue(fieldName, val)}
        />
      );
    case 'range':
    case 'range-slider':
      return (
        <RangeSlider
          {...commonProps}
          value={value || [field.min ?? 0, field.max ?? 100]}
          min={field.min ?? 0}
          max={field.max ?? 100}
          step={field.step ?? 1}
          onChange={(val) => form.setFieldValue(fieldName, val)}
        />
      );
    case 'checkbox':
      return <Checkbox {...commonProps} checked={!!value} {...form.getInputProps(fieldName, { type: 'checkbox' })} />;
    case 'switch':
    case 'boolean':
      return <Switch {...commonProps} checked={!!value} {...form.getInputProps(fieldName, { type: 'checkbox' })} />;
    case 'radio':
      return (
        <RadioGroup {...commonProps} {...form.getInputProps(fieldName)}>
          {resolvedOptions.map((option) => (
            <Radio key={option.value} value={String(option.value)} label={option.label} />
          ))}
        </RadioGroup>
      );
    case 'select':
      return (
        <Select
          {...commonProps}
          data={resolvedOptions}
          searchable={field.searchable}
          nothingFoundMessage="No options"
          comboboxProps={{ withinPortal: true }}
          {...form.getInputProps(fieldName)}
        />
      );
    case 'multi-select':
    case 'multiselect':
      return (
        <MultiSelect
          {...commonProps}
          data={resolvedOptions}
          searchable={field.searchable}
          clearable
          comboboxProps={{ withinPortal: true }}
          {...form.getInputProps(fieldName)}
        />
      );
    case 'segmented':
      return (
        <SegmentedControl
          {...commonProps}
          data={resolvedOptions}
          value={value}
          onChange={(val) => form.setFieldValue(fieldName, val)}
        />
      );
    case 'date':
      return (
        <DatePickerInput
          {...commonProps}
          value={value ? (value instanceof Date ? value : new Date(value)) : null}
          popoverProps={{ withinPortal: true }}
          onChange={(val) => form.setFieldValue(fieldName, val || null)}
        />
      );
    case 'time':
      return (
        <TimeInput
          {...commonProps}
          value={value}
          onChange={(event) => form.setFieldValue(fieldName, event.currentTarget.value)}
        />
      );
    case 'datetime':
      return (
        <DateTimePicker
          {...commonProps}
          value={value ? (value instanceof Date ? value : new Date(value)) : null}
          popoverProps={{ withinPortal: true }}
          onChange={(val) => form.setFieldValue(fieldName, val || null)}
        />
      );
    case 'daterange':
      return (
        <DatePickerInput
          type="range"
          {...commonProps}
          value={ensureArray(value).map((v) => (v ? (v instanceof Date ? v : new Date(v)) : null))}
          popoverProps={{ withinPortal: true }}
          onChange={(val) => form.setFieldValue(fieldName, val)}
        />
      );
    case 'color':
      return <ColorInput {...commonProps} {...form.getInputProps(fieldName)} />;
    case 'json':
      return <JsonInput autosize minRows={4} {...commonProps} {...form.getInputProps(fieldName)} />;
    case 'file':
      if (field.dropzone) {
        return (
          <Stack gap="xs">
            {field.label && (
              <Text size="sm" fw={600}>
                {field.label}
              </Text>
            )}
            <Dropzone
              accept={field.accept}
              multiple={field.multiple}
              onDrop={(files) => {
                if (field.multiple) {
                  form.setFieldValue(fieldName, files);
                } else {
                  form.setFieldValue(fieldName, files[0] || null);
                }
              }}
            >
              <Group justify="center" mih={80}>
                <Text size="sm" c="dimmed">
                  {field.placeholder || 'Drag and drop files here'}
                </Text>
              </Group>
            </Dropzone>
            <FileInput
              {...commonProps}
              clearable
              accept={field.accept}
              multiple={field.multiple}
              value={value}
              onChange={(val) => form.setFieldValue(fieldName, val)}
            />
          </Stack>
        );
      }
      return (
        <FileInput
          {...commonProps}
          accept={field.accept}
          multiple={field.multiple}
          value={value}
          onChange={(val) => form.setFieldValue(fieldName, val)}
        />
      );
    case 'chips':
    case 'tags':
      return (
        <MultiSelect
          {...commonProps}
          data={ensureArray(field.options).map((opt) => ({ value: String(opt.value), label: opt.label }))}
          value={ensureArray(value)}
          onChange={(val) => form.setFieldValue(fieldName, val)}
          searchable
          creatable
          getCreateLabel={(query) => `+ Add ${query}`}
          onCreate={(query) => {
            const next = [...ensureArray(form.values[fieldName]), query];
            form.setFieldValue(fieldName, next);
            return { value: query, label: query };
          }}
        />
      );
    default:
      return <TextInput {...commonProps} {...form.getInputProps(fieldName)} />;
  }
};

const FormNode = ({ node, context }) => {
  const defaults = node.defaults || node.initialValues || {};
  const form = useForm({
    initialValues: defaults,
  });
  const handleAction = useActionHandler();
  const fields = ensureArray(node.fields);
  const steps = ensureArray(node.steps);
  const isWizard = steps.length > 0;
  const [activeStep, setActiveStep] = useState(0);
  const requiresFormData =
    node.encode === 'formdata' ||
    fields.some((field) => {
      const type = (field.type || '').toLowerCase();
      return type === 'file' || type === 'upload';
    });

  useEffect(() => {
    if (!node.unsavedGuard) return undefined;
    const message =
      typeof node.unsavedGuard === 'string'
        ? node.unsavedGuard
        : node.unsavedGuard?.message || 'You have unsaved changes. Are you sure you want to leave?';
    const handler = (event) => {
      if (!form.isDirty || !form.isDirty()) {
        return undefined;
      }
      event.preventDefault();
      event.returnValue = message;
      return message;
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [form, node.unsavedGuard]);

  const submitHandler = form.onSubmit(async (values) => {
    const merged = deepMerge(node.params || {}, values);
    const paramValues = {};
    let formData = requiresFormData ? new FormData() : null;

    safeEntries(merged).forEach(([key, value]) => {
      const isFile = typeof File !== 'undefined' && value instanceof File;
      const isFileList = typeof FileList !== 'undefined' && value instanceof FileList;
      const isFileArray =
        Array.isArray(value) && value.length > 0 && typeof File !== 'undefined' && value[0] instanceof File;

      if (!isFile && !isFileList && !isFileArray) {
        paramValues[key] = value;
      }

      if (formData) {
        if (isFileList) {
          Array.from(value).forEach((file) => formData.append(key, file));
        } else if (isFileArray) {
          value.forEach((file) => formData.append(key, file));
        } else if (isFile) {
          formData.append(key, value);
        } else if (value !== undefined && value !== null) {
          formData.append(key, value);
        } else {
          formData.append(key, '');
        }
      }
    });

    const response = await handleAction(node, paramValues, {
      formData,
    });
    if (response?.success && node.resetOnSuccess) {
      form.setValues(defaults);
      if (form.resetDirty) {
        form.resetDirty(defaults);
      }
      if (isWizard) {
        setActiveStep(0);
      }
    }
  });

  const childContext = useMemo(
    () => ({
      ...(context || {}),
      form,
      values: form.values,
      activeStep,
    }),
    [activeStep, context, form, form.values]
  );

  const getFieldsForStep = (index) => {
    const step = steps[index];
    if (!step) return fields;
    const ids = ensureArray(step.fields);
    if (!ids.length) {
      return fields;
    }
    return fields.filter((field) => ids.includes(field.id));
  };

  const validateStep = async () => {
    if (!isWizard || node.validatePerStep === false) {
      return true;
    }
    const currentFields = getFieldsForStep(activeStep);
    const fieldIds = currentFields.map((field) => field.id);
    const validations = await Promise.all(
      fieldIds.map(async (fieldId) => {
        if (form.validateField) {
          const validation = form.validateField(fieldId);
          return validation?.hasError === false;
        }
        const errors = form.validate();
        return !errors[fieldId];
      })
    );
    return validations.every(Boolean);
  };

  const goNext = async () => {
    if (await validateStep()) {
      setActiveStep((prev) => Math.min(prev + 1, steps.length - 1));
    }
  };

  const goBack = () => {
    setActiveStep((prev) => Math.max(prev - 1, 0));
  };

  const renderFields = (fieldsToRender) =>
    fieldsToRender.map((field) => <FormField field={field} form={form} key={field.id} />);

  const wizardControls = isWizard ? (
    <Group justify="space-between">
      <Button variant="default" onClick={goBack} disabled={activeStep === 0} size={node.buttonSize || 'sm'}>
        {node.prevLabel || 'Back'}
      </Button>
      {activeStep === steps.length - 1 ? (
        <Button type="submit" size={node.submitSize || 'sm'}>
          {node.submitLabel || 'Submit'}
        </Button>
      ) : (
        <Button onClick={goNext} size={node.buttonSize || 'sm'}>
          {node.nextLabel || 'Next'}
        </Button>
      )}
    </Group>
  ) : null;

  return (
    <form onSubmit={submitHandler}>
      <Stack gap="sm">
        {isWizard ? (
          <>
            <Stepper active={activeStep} onStepClick={setActiveStep} allowNextStepsSelect={node.allowStepSelect ?? true} orientation={node.orientation || 'horizontal'}>
              {steps.map((step, idx) => {
                const StepIcon = resolveIcon(step.icon);
                return (
                  <Stepper.Step
                    key={step.id || idx}
                    label={step.label}
                    description={step.description}
                    icon={StepIcon ? <StepIcon size={14} /> : undefined}
                  />
                );
              })}
            </Stepper>
            <Stack gap="sm">
              {renderFields(getFieldsForStep(activeStep))}
              {renderChildren(steps[activeStep]?.children, childContext)}
              {node.actions && activeStep === steps.length - 1 && (
                <ButtonGroupNode node={{ buttons: node.actions }} context={context} />
              )}
            </Stack>
            {wizardControls}
            {renderChildren(node.children, childContext)}
          </>
        ) : (
          <>
            {renderFields(fields)}
            {renderChildren(node.children, childContext)}
            <Group justify={node.alignButtons || 'flex-end'}>
              {node.actions && <ButtonGroupNode node={{ buttons: node.actions }} context={context} />}
              <Button type="submit" size={node.submitSize || 'sm'}>
                {node.submitLabel || 'Submit'}
              </Button>
            </Group>
          </>
        )}
      </Stack>
    </form>
  );
};

const SettingsFormNode = ({ node }) => {
  const { settings, saveSettings } = usePluginUI();
  const mergedDefaults = useMemo(
    () => ({ ...node.defaults, ...settings }),
    [node.defaults, settings]
  );
  const form = useForm({
    initialValues: mergedDefaults,
  });

  return (
    <form
      onSubmit={form.onSubmit(async (values) => {
        const result = await saveSettings(values);
        if (result) {
          notifications.show({
            title: node.successTitle || 'Settings saved',
            message: node.successMessage || 'Plugin settings updated',
            color: 'green',
          });
        }
      })}
    >
      <Stack gap="sm">
        {ensureArray(node.fields).map((field) => (
          <FormField field={field} form={form} key={field.id} />
        ))}
        <Group justify="flex-end">
          <Button type="submit" size={node.submitSize || 'sm'}>
            {node.submitLabel || 'Save Settings'}
          </Button>
        </Group>
      </Stack>
    </form>
  );
};

const ModalNode = ({ node, context }) => {
  const [opened, handlers] = useDisclosure(false);
  const triggerRef = useRef(null);
  const contentRef = useRef(null);
  const lastFocusedRef = useRef(null);

  const openModal = () => {
    lastFocusedRef.current = document.activeElement;
    handlers.open();
  };

  useEffect(() => {
    if (opened && contentRef.current) {
      const focusable = contentRef.current.querySelector(FOCUSABLE_SELECTOR);
      if (focusable) {
        focusable.focus();
      }
    }
  }, [opened]);

  useEffect(() => {
    if (!opened && lastFocusedRef.current) {
      const element = lastFocusedRef.current;
      requestAnimationFrame(() => {
        element.focus?.();
      });
    }
  }, [opened]);

  return (
    <>
      <Button
        ref={triggerRef}
        size={node.trigger?.size || 'xs'}
        variant={node.trigger?.variant || 'light'}
        onClick={openModal}
      >
        {node.trigger?.label || 'Open'}
      </Button>
      <Modal
        opened={opened}
        onClose={handlers.close}
        title={node.title || node.trigger?.label}
        size={node.size || 'lg'}
      >
        <div ref={contentRef}>{renderChildren(node.children, context)}</div>
      </Modal>
    </>
  );
};

const DrawerNode = ({ node, context }) => {
  const [opened, handlers] = useDisclosure(false);
  const triggerRef = useRef(null);
  const contentRef = useRef(null);
  const lastFocusedRef = useRef(null);

  const openDrawer = () => {
    lastFocusedRef.current = document.activeElement;
    handlers.open();
  };

  useEffect(() => {
    if (opened && contentRef.current) {
      const focusable = contentRef.current.querySelector(FOCUSABLE_SELECTOR);
      if (focusable) {
        focusable.focus();
      }
    }
  }, [opened]);

  useEffect(() => {
    if (!opened && lastFocusedRef.current) {
      const element = lastFocusedRef.current;
      requestAnimationFrame(() => element.focus?.());
    }
  }, [opened]);

  return (
    <>
      <Button
        ref={triggerRef}
        size={node.trigger?.size || 'xs'}
        variant={node.trigger?.variant || 'light'}
        onClick={openDrawer}
      >
        {node.trigger?.label || 'Open'}
      </Button>
      <Drawer
        opened={opened}
        onClose={handlers.close}
        title={node.title}
        position={node.position || 'right'}
        size={node.size || 'md'}
      >
        <div ref={contentRef}>{renderChildren(node.children, context)}</div>
      </Drawer>
    </>
  );
};

const TabsNode = ({ node, context }) => {
  const tabs = ensureArray(node.tabs || node.children);
  const defaultValue = node.defaultTab || tabs[0]?.id;
  const [value, setValue] = useState(defaultValue);

  useEffect(() => {
    if (!value && tabs[0]?.id) {
      setValue(tabs[0].id);
    }
  }, [tabs, value]);

  const maxVisible = node.maxVisible || tabs.length;
  const visibleTabs = tabs.slice(0, maxVisible);
  const overflowTabs = tabs.slice(maxVisible);

  const renderTabLabel = (tab) => {
    const IconComp = resolveIcon(tab.icon);
    return (
      <Tabs.Tab
        value={tab.id}
        key={tab.id}
        leftSection={IconComp ? <IconComp size={14} /> : undefined}
      >
        {tab.label}
      </Tabs.Tab>
    );
  };

  return (
    <Tabs
      value={value}
      onChange={setValue}
      keepMounted={node.keepMounted ?? false}
      variant={node.variant || 'default'}
      color={node.color}
      orientation={node.orientation || 'horizontal'}
    >
      <Tabs.List
        style={{
          overflowX: node.scrollable !== false ? 'auto' : undefined,
          flexWrap: node.wrap ? 'wrap' : 'nowrap',
          gap: node.listGap,
        }}
      >
        {visibleTabs.map((tab) => renderTabLabel(tab))}
        {overflowTabs.length > 0 && (
          <Menu withinPortal position={node.morePosition || 'bottom-end'}>
            <Menu.Target>
              <ActionIcon variant="subtle" aria-label={node.moreLabel || 'More tabs'}>
                <ChevronDown size={14} />
              </ActionIcon>
            </Menu.Target>
            <Menu.Dropdown>
              <Menu.Label>{node.moreLabel || 'More'}</Menu.Label>
              {overflowTabs.map((tab) => (
                <Menu.Item key={tab.id} onClick={() => setValue(tab.id)}>
                  {tab.label}
                </Menu.Item>
              ))}
            </Menu.Dropdown>
          </Menu>
        )}
      </Tabs.List>
      {tabs.map((tab) => (
        <Tabs.Panel value={tab.id} key={tab.id} p={node.panelPadding || 'sm'}>
          {renderChildren(tab.children, context)}
        </Tabs.Panel>
      ))}
    </Tabs>
  );
};

const AccordionNode = ({ node, context }) => {
  const items = ensureArray(node.items || node.children);
  return (
    <Accordion multiple={node.multiple} defaultValue={ensureArray(node.defaultValue)}>
      {items.map((item) => (
        <Accordion.Item value={item.id || uniqueId('accordion')} key={item.id || uniqueId('accordion')}>
          <Accordion.Control>{item.label}</Accordion.Control>
          <Accordion.Panel>{renderChildren(item.children, context)}</Accordion.Panel>
        </Accordion.Item>
      ))}
    </Accordion>
  );
};

const TimelineNode = ({ node }) => {
  const dataSourceOptions = useMemo(
    () => ({
      override: node.dataSource || {},
    }),
    [node.dataSource]
  );
  const timelineSource = usePluginDataSource(node.source, dataSourceOptions);
  const items = ensureArray((timelineSource && timelineSource.data) || node.items);
  return (
    <Timeline active={node.active ?? items.length} bulletSize={node.bulletSize || 20} lineWidth={node.lineWidth || 2}>
      {items.map((item, idx) => {
        const IconComp = resolveIcon(item.icon);
        return (
          <Timeline.Item
            key={item.id || idx}
            title={item.title}
            bullet={IconComp ? <IconComp size={12} /> : undefined}
          >
            {item.description && <Text size="sm">{item.description}</Text>}
            {item.time && (
              <Text size="xs" c="dimmed">
                {item.time}
              </Text>
            )}
          </Timeline.Item>
        );
      })}
    </Timeline>
  );
};

const TreeNode = ({ node }) => {
  const renderTree = (items, level = 0) => (
    <Stack gap={4} pl={level ? 'md' : 0}>
      {ensureArray(items).map((item, idx) => {
        const IconComp = resolveIcon(item.icon);
        return (
          <Box key={item.id || idx}>
            <Group gap="xs" align="flex-start">
              {IconComp && <IconComp size={14} />}
              <div>
                <Text fw={500}>{item.label}</Text>
                {item.description && (
                  <Text size="xs" c="dimmed">
                    {item.description}
                  </Text>
                )}
              </div>
            </Group>
            {item.children && renderTree(item.children, level + 1)}
          </Box>
        );
      })}
    </Stack>
  );

  return <>{renderTree(node.items || node.children)}</>;
};

const SortableListNode = ({ node }) => {
  const dataSourceOptions = useMemo(
    () => ({
      override: node.dataSource || {},
    }),
    [node.dataSource]
  );
  const { data, refresh } = usePluginDataSource(node.source, dataSourceOptions);
  const items = ensureArray(data);
  const [localItems, setLocalItems] = useState(items);
  const sensors = useSensors(useSensor(PointerSensor));
  const handleAction = useActionHandler();
  const fallbackIdsRef = useRef(new Map());

  const resolveItemId = useCallback(
    (value) => {
      if (value && typeof value === 'object') {
        const candidate =
          value.id ?? value.key ?? value.value ?? value.label ?? value.title ?? value.name;
        if (candidate !== undefined && candidate !== null) {
          return String(candidate);
        }
        if (fallbackIdsRef.current.has(value)) {
          return fallbackIdsRef.current.get(value);
        }
        const generated = uniqueId('sortable');
        fallbackIdsRef.current.set(value, generated);
        return generated;
      }
      if (value === null || value === undefined) {
        return 'sortable-null';
      }
      return String(value);
    },
    []
  );

  const itemsWithIds = useMemo(
    () => localItems.map((entry) => ({ item: entry, id: resolveItemId(entry) })),
    [localItems, resolveItemId]
  );

  const reorder = useCallback(
    async (activeId, overId) => {
      const current = itemsWithIds;
      const oldIndex = current.findIndex((entry) => entry.id === activeId);
      const newIndex = current.findIndex((entry) => entry.id === overId);
      if (oldIndex === -1 || newIndex === -1) return;
      const updatedEntries = [...current];
      const [moved] = updatedEntries.splice(oldIndex, 1);
      updatedEntries.splice(newIndex, 0, moved);
      const updatedItems = updatedEntries.map((entry) => entry.item);
      setLocalItems(updatedItems);
      if (node.action) {
        await handleAction(node.action, {
          order: updatedEntries.map((entry) => {
            const value = entry.item;
            if (value && typeof value === 'object' && value.id !== undefined) {
              return value.id;
            }
            return entry.id;
          }),
        });
        refresh();
      }
    },
    [itemsWithIds, node.action, handleAction, refresh]
  );

  useEffect(() => {
    setLocalItems((prev) => (listsMatchById(prev, items, resolveItemId) ? prev : items));
  }, [items, resolveItemId]);

  const SortableItem = ({ item, itemId }) => {
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
      id: itemId,
    });
    const style = {
      transform: CSS.Transform.toString(transform),
      transition,
      opacity: isDragging ? 0.6 : 1,
    };
    return (
      <Card ref={setNodeRef} withBorder padding="xs" style={style}>
        <Group gap="xs" justify="space-between">
          <Group gap="xs" {...attributes} {...listeners}>
            <GripVertical size={16} />
            <Text>{item.label || item.title}</Text>
          </Group>
          {item.badge && <Badge color={item.badge.color || 'blue'}>{item.badge.label}</Badge>}
        </Group>
      </Card>
    );
  };

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={(event) => {
        const { active, over } = event;
        if (active?.id && over?.id && active.id !== over.id) {
          reorder(active.id, over.id);
        }
      }}
    >
      <SortableContext items={itemsWithIds.map((entry) => entry.id)} strategy={verticalListSortingStrategy}>
        <Stack gap="xs">
          {itemsWithIds.map(({ item: entry, id }) => (
            <SortableItem item={entry} itemId={id} key={id} />
          ))}
        </Stack>
      </SortableContext>
    </DndContext>
  );
};

const CarouselNode = ({ node, context }) => {
  const slides = ensureArray(node.items || node.slides || node.children);
  if (!slides.length) {
    return null;
  }

  const slideGap = node.slideGap || node.gap || 'md';
  const slideSize = node.slideSize || node.itemWidth || '100%';
  const slideMinWidth = typeof slideSize === 'number' ? `${slideSize}px` : slideSize;
  const height = node.height;
  const align = node.align || 'stretch';

  const renderSlideContent = (slide, idx) => {
    if (!slide) return null;
    if (slide.type || slide.children) {
      return renderChildren(slide.children || [slide], context);
    }
    if (slide.image) {
      return (
        <Stack gap="xs">
          <Image
            src={slide.image}
            alt={slide.alt || slide.title || `slide-${idx}`}
            radius={slide.radius || node.imageRadius || 'md'}
            fit={slide.fit || node.imageFit || 'cover'}
            h={slide.height || node.imageHeight}
          />
          {slide.title && <Text fw={600}>{slide.title}</Text>}
          {slide.description && <Text size="sm" c="dimmed">{slide.description}</Text>}
          {slide.actions && <ButtonGroupNode node={{ buttons: slide.actions }} context={context} />}
        </Stack>
      );
    }
    if (typeof slide === 'string' || typeof slide === 'number') {
      return <Text>{slide}</Text>;
    }
    return renderChildren(slide, context);
  };

  return (
    <ScrollArea
      offsetScrollbars
      scrollbarSize={node.scrollbarSize || 8}
      type={node.scrollType || 'hover'}
      styles={{ viewport: { paddingBottom: '0.25rem' } }}
    >
      <Group
        gap={slideGap}
        wrap="nowrap"
        align={align}
        style={{
          minHeight: height,
          padding: node.padding,
        }}
      >
        {slides.map((slide, idx) => (
          <Box
            key={slide?.id || idx}
            style={{
              minWidth: slideMinWidth,
              flex: node.fullWidth ? '1 0 auto' : '0 0 auto',
            }}
          >
            <Paper
              withBorder={node.withBorder ?? false}
              shadow={node.shadow}
              radius={node.radius || 'md'}
              p={node.slidePadding || node.padding || 0}
              style={{ height: '100%' }}
            >
              {renderSlideContent(slide, idx)}
            </Paper>
          </Box>
        ))}
      </Group>
    </ScrollArea>
  );
};

const SplitNode = ({ node, context }) => {
  const orientation = (node.orientation || node.direction || 'horizontal').toLowerCase();
  const persistKey = node.persistKey;

  const computeDefaultSizes = useCallback(() => {
    const initial = ensureArray(node.sizes);
    if (initial.length >= 2) {
      const total = initial.reduce((sum, value) => sum + value, 0) || 1;
      return initial.map((value) => (value / total) * 100);
    }
    const primary = node.initialPrimary ?? 50;
    return [primary, 100 - primary];
  }, [node.initialPrimary, node.sizes]);

  const [sizes, setSizes] = useState(() => computeDefaultSizes());

  useEffect(() => {
    if (!persistKey) return;
    try {
      const stored = window.localStorage.getItem(`plugin-split:${persistKey}`);
      if (stored) {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed) && parsed.length === 2) {
          setSizes(parsed);
        }
      }
    } catch (err) {
      // ignore storage errors
    }
  }, [persistKey]);

  const containerRef = useRef(null);
  const draggingRef = useRef(false);

  useEffect(() => () => {
    document.removeEventListener('pointermove', handlePointerMove);
    document.removeEventListener('pointerup', handlePointerUp);
  });

  const updateSizes = (primaryPercent) => {
    const minPrimary = node.minSizes?.[0] ?? node.minPrimary ?? 5;
    const minSecondary = node.minSizes?.[1] ?? node.minSecondary ?? 5;
    const nextPrimary = Math.min(100 - minSecondary, Math.max(minPrimary, primaryPercent));
    const next = [nextPrimary, 100 - nextPrimary];
    setSizes(next);
    if (persistKey) {
      try {
        window.localStorage.setItem(`plugin-split:${persistKey}`, JSON.stringify(next));
      } catch (err) {
        // ignore storage write errors
      }
    }
  };

  const handlePointerMove = (event) => {
    if (!draggingRef.current || !containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const total = orientation === 'vertical' ? rect.height : rect.width;
    if (!total) return;
    const offset =
      orientation === 'vertical'
        ? event.clientY - rect.top
        : event.clientX - rect.left;
    const percent = (offset / total) * 100;
    updateSizes(percent);
  };

  const handlePointerUp = () => {
    draggingRef.current = false;
    document.removeEventListener('pointermove', handlePointerMove);
    document.removeEventListener('pointerup', handlePointerUp);
  };

  const handlePointerDown = (event) => {
    event.preventDefault();
    draggingRef.current = true;
    document.addEventListener('pointermove', handlePointerMove);
    document.addEventListener('pointerup', handlePointerUp);
  };

  const primaryContent = node.primary || node.first || node.children?.[0];
  const secondaryContent = node.secondary || node.second || node.children?.[1];

  const dividerThickness = node.dividerSize || 6;
  const dividerStyles = orientation === 'vertical'
    ? { height: dividerThickness, width: '100%', cursor: 'row-resize' }
    : { width: dividerThickness, height: '100%', cursor: 'col-resize' };

  return (
    <Box
      ref={containerRef}
      style={{
        display: 'flex',
        flexDirection: orientation === 'vertical' ? 'column' : 'row',
        width: '100%',
        height: node.height || '100%',
        minHeight: node.minHeight,
        borderRadius: node.radius,
        overflow: node.overflow || 'hidden',
      }}
    >
      <Box
        style={{
          flexBasis: `${sizes[0]}%`,
          flexGrow: 0,
          flexShrink: 0,
          minWidth: orientation === 'horizontal' ? node.minSizes?.[0] : undefined,
          minHeight: orientation === 'vertical' ? node.minSizes?.[0] : undefined,
        }}
      >
        {renderChildren(primaryContent, context)}
      </Box>
      <Box
        onPointerDown={handlePointerDown}
        style={{
          background: node.dividerColor || 'var(--mantine-color-gray-3)',
          ...dividerStyles,
        }}
      />
      <Box
        style={{
          flexBasis: `${sizes[1]}%`,
          flexGrow: 1,
          overflow: node.secondaryOverflow || 'auto',
        }}
      >
        {renderChildren(secondaryContent, context)}
      </Box>
    </Box>
  );
};

const SpotlightNode = ({ node, context }) => {
  const handleAction = useActionHandler();
  const actions = useMemo(() => {
    return ensureArray(node.actions).map((action) => {
      const Icon = resolveIcon(action.icon);
      return {
        id: action.id || action.action || uniqueId('spotlight'),
        label: action.label || action.title || action.id,
        description: action.description,
        onTrigger: () => handleAction(action, action.params || {}, action.options || {}),
        keywords: ensureArray(action.keywords)
          .map((keyword) => String(keyword).toLowerCase())
          .join(' '),
        group: action.group,
        icon: Icon ? <Icon size={16} /> : undefined,
      };
    });
  }, [handleAction, node.actions]);

  const [opened, { open, close }] = useDisclosure(false);
  const [query, setQuery] = useState('');

  useEffect(() => {
    if (node.autoOpen) {
      requestAnimationFrame(() => open());
    }
  }, [node.autoOpen, open]);

  const shortcuts = useMemo(
    () => ensureArray(node.shortcut || node.hotkey || node.hotkeys || ['mod+k']),
    [node.hotkey, node.hotkeys, node.shortcut]
  );

  useEffect(() => {
    const handler = (event) => {
      const key = event.key.toLowerCase();
      const isMac = typeof navigator !== 'undefined' && /mac/i.test(navigator.platform);
      const isMod = isMac ? event.metaKey : event.ctrlKey;
      const normalizedShortcut = shortcuts.map((shortcut) => shortcut.replace(/\s+/g, '').toLowerCase());
      if (normalizedShortcut.includes('mod+k') && isMod && key === 'k') {
        event.preventDefault();
        open();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, shortcuts]);

  const normalizedQuery = query.trim().toLowerCase();
  const filteredActions = useMemo(() => {
    const limited = node.limit && node.limit > 0 ? node.limit : undefined;
    const matches = actions.filter((action) => {
      if (!normalizedQuery) return true;
      const haystack = [action.label, action.description, action.keywords]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return haystack.includes(normalizedQuery);
    });
    return typeof limited === 'number' ? matches.slice(0, limited) : matches;
  }, [actions, normalizedQuery, node.limit]);

  const executeAction = (entry) => {
    entry.onTrigger?.();
    close();
    setQuery('');
  };

  const childCtx = useMemo(
    () => ({
      ...(context || {}),
      spotlight: {
        open,
        close,
      },
    }),
    [context, open, close]
  );

  const triggerConfig = node.trigger;
  const TriggerIcon = triggerConfig && triggerConfig.icon ? resolveIcon(triggerConfig.icon) : null;
  const triggerButton = triggerConfig === false
    ? null
    : (
        <Button
          size={triggerConfig?.size || 'xs'}
          variant={triggerConfig?.variant || 'light'}
          onClick={open}
          leftSection={TriggerIcon ? <TriggerIcon size={14} /> : undefined}
          mb={triggerConfig?.mb}
        >
          {triggerConfig?.label || node.label || 'Open command palette'}
        </Button>
      );

  return (
    <>
      <Stack gap="xs">
        {triggerButton}
        {renderChildren(node.children, childCtx)}
      </Stack>
      <Modal
        opened={opened}
        onClose={() => {
          close();
          setQuery('');
        }}
        title={node.title || node.placeholder || 'Search commands'}
        centered
        size={node.size || 'md'}
        overlayProps={{ opacity: 0.55, blur: 4 }}
      >
        <Stack gap="sm">
          <TextInput
            value={query}
            onChange={(event) => setQuery(event.currentTarget.value)}
            placeholder={node.placeholder || 'Search commands'}
            leftSection={<Search size={14} />}
            autoFocus
          />
          <ScrollArea h={node.listHeight || 260} type="auto">
            <Stack gap="xs">
              {filteredActions.length === 0 && (
                <Text size="sm" c="dimmed">
                  {node.emptyMessage || 'No results'}
                </Text>
              )}
              {filteredActions.map((action) => (
                <Button
                  key={action.id}
                  variant="light"
                  color="gray"
                  justify="flex-start"
                  leftSection={action.icon}
                  onClick={() => executeAction(action)}
                >
                  <Stack gap={2} align="flex-start" style={{ flex: 1 }}>
                    <Text size="sm" fw={600}>
                      {action.label}
                    </Text>
                    {action.description && (
                      <Text size="xs" c="dimmed">
                        {action.description}
                      </Text>
                    )}
                  </Stack>
                </Button>
              ))}
            </Stack>
          </ScrollArea>
        </Stack>
      </Modal>
    </>
  );
};

const TOUR_STYLE_ID = 'plugin-tour-highlight-style';

const ensureTourStyles = () => {
  if (typeof document === 'undefined') return;
  if (document.getElementById(TOUR_STYLE_ID)) return;
  const style = document.createElement('style');
  style.id = TOUR_STYLE_ID;
  style.innerHTML = '[data-tour-active="true"] { outline: 2px solid var(--mantine-color-blue-5); outline-offset: 4px; border-radius: 6px; }';
  document.head.appendChild(style);
};

const TourNode = ({ node }) => {
  const steps = ensureArray(node.steps);
  const [opened, { open, close }] = useDisclosure(node.autoStart || false);
  const [active, setActive] = useState(0);

  useEffect(() => {
    ensureTourStyles();
  }, []);

  useEffect(() => {
    if (!opened) {
      document.querySelectorAll('[data-tour-active="true"]').forEach((el) => {
        el.removeAttribute('data-tour-active');
      });
      return;
    }
    const step = steps[active];
    document.querySelectorAll('[data-tour-active="true"]').forEach((el) => {
      el.removeAttribute('data-tour-active');
    });
    if (step?.selector) {
      const element = document.querySelector(step.selector);
      if (element) {
        element.setAttribute('data-tour-active', 'true');
        if (step.scroll !== false) {
          element.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      }
    }
  }, [active, opened, steps]);

  const next = () => setActive((prev) => Math.min(prev + 1, steps.length - 1));
  const previous = () => setActive((prev) => Math.max(prev - 1, 0));
  const finish = () => {
    close();
    document.querySelectorAll('[data-tour-active="true"]').forEach((el) => {
      el.removeAttribute('data-tour-active');
    });
  };

  if (!steps.length) {
    return node.trigger === false ? null : (
      <Button size={node.triggerSize || 'xs'} variant={node.triggerVariant || 'light'} onClick={open}>
        {node.triggerLabel || 'Start tour'}
      </Button>
    );
  }

  const current = steps[active];

  return (
    <>
      {node.trigger !== false && (
        <Button size={node.triggerSize || 'xs'} variant={node.triggerVariant || 'light'} onClick={open}>
          {node.triggerLabel || 'Start tour'}
        </Button>
      )}
      <Modal opened={opened} onClose={finish} title={current?.title || node.title || 'Product tour'} centered>
        <Stack gap="sm">
          <Text size="sm">{current?.description || node.description}</Text>
          {current?.content && <Text size="sm">{current.content}</Text>}
          <Group justify="space-between" align="center">
            <Button variant="subtle" onClick={previous} disabled={active === 0} size="xs">
              {node.prevLabel || 'Back'}
            </Button>
            <Group gap="xs">
              <Text size="xs">
                {active + 1} / {steps.length}
              </Text>
              {active === steps.length - 1 ? (
                <Button size="xs" onClick={finish}>
                  {node.finishLabel || 'Finish'}
                </Button>
              ) : (
                <Button size="xs" onClick={next}>
                  {node.nextLabel || 'Next'}
                </Button>
              )}
            </Group>
          </Group>
        </Stack>
      </Modal>
    </>
  );
};

const BarcodeNode = ({ node }) => {
  const canvasRef = useRef(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let mounted = true;
    const generate = async () => {
      try {
        const module = await import('jsbarcode');
        const JsBarcode = module.default || module;
        if (canvasRef.current) {
          JsBarcode(canvasRef.current, node.value || '', {
            format: node.format || 'CODE128',
            lineColor: node.lineColor || '#000',
            background: node.background || '#fff',
            width: node.barWidth || 2,
            height: node.height || 80,
            displayValue: node.displayValue !== false,
            margin: node.margin ?? 8,
            text: node.text,
            fontSize: node.fontSize,
            ...node.options,
          });
          setError(null);
        }
      } catch (err) {
        if (mounted) {
          setError('Barcode generation unavailable');
        }
      }
    };
    generate();
    return () => {
      mounted = false;
    };
  }, [node.background, node.barWidth, node.displayValue, node.fontSize, node.format, node.height, node.lineColor, node.margin, node.options, node.text, node.value]);

  return (
    <Stack gap={4} align="center">
      <canvas ref={canvasRef} style={{ maxWidth: '100%' }} />
      {error && (
        <Text size="xs" c="red">
          {error}
        </Text>
      )}
    </Stack>
  );
};

const StatCardNode = ({ node, context }) => {
  const sourceOptions = useMemo(
    () => ({
      override: node.dataSource || {},
    }),
    [node.dataSource]
  );

  const { data: sourceData } = usePluginDataSource(node.source, sourceOptions);

  const templateScope = useMemo(() => {
    const scope = {};
    if (context && typeof context === 'object') {
      scope.context = context;
      Object.assign(scope, context);
    }
    if (node.scope && typeof node.scope === 'object') {
      scope.scope = node.scope;
      Object.assign(scope, node.scope);
    }
    if (typeof node.source === 'string') {
      scope[node.source] = sourceData;
    }
    scope.data = sourceData;
    return scope;
  }, [context, node.scope, node.source, sourceData]);

  const formatValue = (input) => {
    if (input === null || input === undefined) return undefined;
    if (typeof input === 'string') {
      const templated = applyTemplate(input, templateScope);
      return templated !== undefined ? templated : input;
    }
    return input;
  };

  const resolveMetric = () => {
    const path = node.metricPath || node.metric || node.path;
    if (path) {
      const resolved = getByPath(templateScope, path);
      if (resolved !== undefined && resolved !== null) {
        return resolved;
      }
    }
    const templated = formatValue(node.value);
    if (templated !== undefined && templated !== null && templated !== '') {
      return templated;
    }
    return undefined;
  };

  const metricValue = resolveMetric();
  const fallbackDisplay = formatValue(
    node.fallback ?? node.defaultValue ?? node.placeholder ?? node.emptyValue
  );
  const displayValue =
    metricValue === undefined || metricValue === null || metricValue === ''
      ? fallbackDisplay ?? '—'
      : metricValue;

  const deltaRaw = formatValue(node.delta);
  const deltaValue =
    deltaRaw === undefined || deltaRaw === null || deltaRaw === '' ? null : deltaRaw;
  const deltaNumber =
    deltaValue !== null && !Number.isNaN(Number.parseFloat(deltaValue))
      ? Number.parseFloat(deltaValue)
      : null;
  const isPositiveDelta = deltaNumber !== null ? deltaNumber >= 0 : null;

  const IconComp = resolveIcon(node.icon);
  const formattedLabel = formatValue(node.label) || node.label || 'Metric';
  const themeIconNode = buildThemeIcon(node.themeIcon, node.icon);
  const avatarNode = buildAvatar(node.avatar, formattedLabel);
  const avatarGroupNode = buildAvatarGroup(node.avatarGroup, formattedLabel);
  const rightVisual = avatarGroupNode || avatarNode || themeIconNode || (IconComp ? <IconComp size={32} /> : null);

  return (
    <Paper withBorder radius="md" p="md">
      <Group justify="space-between" align="flex-start" gap="md">
        <div>
          <Text size="sm" c="dimmed">
            {formattedLabel}
          </Text>
          <Group gap="sm" align="baseline">
            <Text size={node.size || 'xl'} fw={700}>
              {displayValue}
            </Text>
            {node.unit && (
              <Text size="sm" c="dimmed">
                {node.unit}
              </Text>
            )}
          </Group>
          {deltaValue !== null && (
            <Group gap={4} mt={4} align="center">
              {deltaNumber !== null && deltaNumber !== 0 ? (
                isPositiveDelta ? (
                  <Check size={14} color="lime" />
                ) : (
                  <X size={14} color="red" />
                )
              ) : null}
              <Text size="xs" c={isPositiveDelta === false ? 'red' : 'teal'}>
                {deltaValue}
              </Text>
            </Group>
          )}
          {node.helper && (
            <Text size="xs" c="dimmed" mt={6}>
              {formatValue(node.helper)}
            </Text>
          )}
        </div>
        {rightVisual}
      </Group>
    </Paper>
  );
};

const COMPONENTS = {
  text: TextNode,
  title: TitleNode,
  card: CardNode,
  stack: StackNode,
  group: GroupNode,
  box: BoxNode,
  grid: GridNode,
  simplegrid: SimpleGridNode,
  list: ListNode,
  status: StatusLight,
  progress: ProgressNode,
  loader: ProgressNode,
  spinner: ProgressNode,
  chart: ChartNode,
  table: TableNode,
  datatable: TableNode,
  action: ActionButtonNode,
  actionbutton: ActionButtonNode,
  buttons: ButtonGroupNode,
  copy: CopyNode,
  link: LinkNode,
  highlight: HighlightNode,
  code: CodeNode,
  kbd: KbdNode,
  hovercard: HoverCardNode,
  cardlist: RichCardList,
  listcards: RichCardList,
  video: VideoPlayerNode,
  pagination: PaginationNode,
  form: FormNode,
  settingsform: SettingsFormNode,
  carousel: CarouselNode,
  split: SplitNode,
  spotlight: SpotlightNode,
  tour: TourNode,
  barcode: BarcodeNode,
  modal: ModalNode,
  drawer: DrawerNode,
  tabs: TabsNode,
  accordion: AccordionNode,
  timeline: TimelineNode,
  tree: TreeNode,
  logstream: LogStreamNode,
  sortablelist: SortableListNode,
  stat: StatCardNode,
};

export const PluginNode = ({ node, context }) => {
  if (!node) return null;
  if (node.type === 'divider') {
    return enhanceNodeElement(
      node,
      <Divider my={node.margin || 'sm'} label={node.label} labelPosition={node.position || 'left'} />,
      context
    );
  }
  const Component = COMPONENTS[(node.type || '').toLowerCase()];
  if (!Component) {
    console.warn('Unknown plugin UI node type', node.type);
    return null;
  }
  const element = <Component node={node} context={context} />;
  return enhanceNodeElement(node, element, context);
};

export const PluginCanvas = ({ layout, context }) => {
  if (!layout) return null;
  if (Array.isArray(layout)) {
    return layout.map((node, idx) => <PluginNode key={node.id || idx} node={node} context={context} />);
  }
  return <PluginNode node={layout} context={context} />;
};

export default PluginCanvas;
