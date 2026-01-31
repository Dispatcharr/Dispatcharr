import React, { createContext, useContext, useState, useCallback } from 'react';
import {
  Stack,
  Group,
  Card,
  Title,
  Text,
  Alert,
  Button,
  Tabs,
  Loader,
  Modal,
  Divider,
  Badge,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle,
  Info,
} from 'lucide-react';
import API from '../../api';
import PluginForm from './PluginForm';
import PluginTable from './PluginTable';
import PluginList from './PluginList';
import PluginDragDropList from './PluginDragDropList';

// Context for sharing plugin state across components
const PluginContext = createContext(null);

export const usePluginContext = () => useContext(PluginContext);

/**
 * PluginRenderer - Renders a plugin page from UI schema
 *
 * This component interprets the declarative UI schema and renders
 * the corresponding Mantine components.
 */
const PluginRenderer = ({ pluginKey, components, modals = [] }) => {
  const [openModals, setOpenModals] = useState({});
  const [actionLoading, setActionLoading] = useState({});
  const [dataRefreshKey, setDataRefreshKey] = useState(0);

  // Open a modal by ID
  const openModal = useCallback((modalId) => {
    setOpenModals((prev) => ({ ...prev, [modalId]: true }));
  }, []);

  // Close a modal by ID
  const closeModal = useCallback((modalId) => {
    setOpenModals((prev) => ({ ...prev, [modalId]: false }));
  }, []);

  // Execute a plugin action
  const runAction = useCallback(async (actionId, params = {}) => {
    setActionLoading((prev) => ({ ...prev, [actionId]: true }));

    try {
      const response = await API.runPluginAction(pluginKey, actionId, params);

      if (response?.success) {
        const result = response.result || {};
        const message = result.message || 'Action completed';

        notifications.show({
          title: 'Success',
          message,
          color: 'green',
        });

        // Refresh data after action
        setDataRefreshKey((k) => k + 1);

        return result;
      } else {
        throw new Error(response?.error || 'Action failed');
      }
    } catch (error) {
      const message = error?.body?.error || error?.message || 'Action failed';
      notifications.show({
        title: 'Error',
        message,
        color: 'red',
      });
      throw error;
    } finally {
      setActionLoading((prev) => ({ ...prev, [actionId]: false }));
    }
  }, [pluginKey]);

  // Context value
  const contextValue = {
    pluginKey,
    openModal,
    closeModal,
    runAction,
    actionLoading,
    dataRefreshKey,
  };

  return (
    <PluginContext.Provider value={contextValue}>
      {/* Render main components */}
      {components.map((component, index) => (
        <ComponentRenderer
          key={component.id || `component-${index}`}
          component={component}
        />
      ))}

      {/* Render modals */}
      {modals.map((modal) => (
        <Modal
          key={modal.id}
          opened={openModals[modal.id] || false}
          onClose={() => closeModal(modal.id)}
          title={modal.title}
          size={modal.size || 'md'}
          centered={modal.centered !== false}
        >
          {modal.components?.map((component, index) => (
            <ComponentRenderer
              key={component.id || `modal-${modal.id}-${index}`}
              component={component}
            />
          ))}
        </Modal>
      ))}
    </PluginContext.Provider>
  );
};

/**
 * ComponentRenderer - Renders a single component from schema
 */
const ComponentRenderer = ({ component }) => {
  const context = usePluginContext();

  if (!component || !component.type) {
    return null;
  }

  // Handle visibility
  if (component.visible === false) {
    return null;
  }

  const { type, ...props } = component;

  switch (type) {
    case 'stack':
      return <StackComponent {...props} />;

    case 'group':
      return <GroupComponent {...props} />;

    case 'card':
      return <CardComponent {...props} />;

    case 'tabs':
      return <TabsComponent {...props} />;

    case 'title':
      return <TitleComponent {...props} />;

    case 'text':
      return <TextComponent {...props} />;

    case 'alert':
      return <AlertComponent {...props} />;

    case 'button':
      return <ButtonComponent {...props} />;

    case 'divider':
      return <Divider {...(props.label ? { label: props.label } : {})} my={props.my || 'md'} />;

    case 'badge':
      return <BadgeComponent {...props} />;

    case 'form':
      return <PluginForm {...props} />;

    case 'table':
      return <PluginTable {...props} />;

    case 'list':
      return <PluginList {...props} />;

    case 'drag_drop_list':
      return <PluginDragDropList {...props} />;

    case 'loading':
      return (
        <Stack align="center" py="xl">
          <Loader size={props.size || 'md'} />
          {props.message && <Text c="dimmed">{props.message}</Text>}
        </Stack>
      );

    case 'empty':
      return (
        <Stack align="center" py="xl">
          <Text c="dimmed">{props.message || 'No data'}</Text>
          {props.action && (
            <Button
              variant="subtle"
              onClick={() => context.runAction(props.action)}
            >
              {props.actionLabel || 'Refresh'}
            </Button>
          )}
        </Stack>
      );

    default:
      console.warn(`Unknown component type: ${type}`);
      return (
        <Alert color="yellow" title="Unknown Component">
          Component type "{type}" is not supported.
        </Alert>
      );
  }
};

// ============================================================================
// Layout Components
// ============================================================================

const StackComponent = ({ components, gap = 'md', align, ...rest }) => (
  <Stack gap={gap} align={align} {...rest}>
    {components?.map((child, index) => (
      <ComponentRenderer
        key={child.id || `stack-child-${index}`}
        component={child}
      />
    ))}
  </Stack>
);

const GroupComponent = ({ components, gap = 'md', justify, wrap = true, ...rest }) => (
  <Group gap={gap} justify={justify} wrap={wrap ? 'wrap' : 'nowrap'} {...rest}>
    {components?.map((child, index) => (
      <ComponentRenderer
        key={child.id || `group-child-${index}`}
        component={child}
      />
    ))}
  </Group>
);

const CardComponent = ({ title, subtitle, components, padding = 'md', shadow = 'sm', withBorder = true, ...rest }) => (
  <Card padding={padding} shadow={shadow} withBorder={withBorder} {...rest}>
    {(title || subtitle) && (
      <Card.Section withBorder inheritPadding py="xs" mb="md">
        {title && <Title order={4}>{title}</Title>}
        {subtitle && <Text size="sm" c="dimmed">{subtitle}</Text>}
      </Card.Section>
    )}
    {components?.map((child, index) => (
      <ComponentRenderer
        key={child.id || `card-child-${index}`}
        component={child}
      />
    ))}
  </Card>
);

const TabsComponent = ({ items, defaultTab, orientation = 'horizontal', variant = 'default', ...rest }) => {
  const defaultValue = defaultTab || items?.[0]?.id;

  return (
    <Tabs defaultValue={defaultValue} orientation={orientation} variant={variant} {...rest}>
      <Tabs.List>
        {items?.map((tab) => (
          <Tabs.Tab key={tab.id} value={tab.id}>
            {tab.icon && <span style={{ marginRight: 8 }}>{tab.icon}</span>}
            {tab.label}
            {tab.badge != null && (
              <Badge size="xs" ml="xs">{tab.badge}</Badge>
            )}
          </Tabs.Tab>
        ))}
      </Tabs.List>

      {items?.map((tab) => (
        <Tabs.Panel key={tab.id} value={tab.id} pt="md">
          {tab.components?.map((child, index) => (
            <ComponentRenderer
              key={child.id || `tab-${tab.id}-child-${index}`}
              component={child}
            />
          ))}
        </Tabs.Panel>
      ))}
    </Tabs>
  );
};

// ============================================================================
// Content Components
// ============================================================================

const TitleComponent = ({ content, order = 2, ...rest }) => (
  <Title order={order} {...rest}>{content}</Title>
);

const TextComponent = ({ content, size, weight, color, align, ...rest }) => (
  <Text size={size} fw={weight} c={color} ta={align} {...rest}>
    {content}
  </Text>
);

const AlertComponent = ({ title, message, color = 'blue', icon, closable, ...rest }) => {
  const iconMap = {
    error: <AlertCircle size={16} />,
    warning: <AlertTriangle size={16} />,
    success: <CheckCircle size={16} />,
    info: <Info size={16} />,
  };

  const alertIcon = icon ? iconMap[icon] || <Info size={16} /> : null;

  return (
    <Alert
      title={title}
      color={color}
      icon={alertIcon}
      withCloseButton={closable}
      {...rest}
    >
      {message}
    </Alert>
  );
};

const BadgeComponent = ({ content, color = 'blue', variant = 'filled', size = 'md', ...rest }) => (
  <Badge color={color} variant={variant} size={size} {...rest}>
    {content}
  </Badge>
);

const ButtonComponent = ({
  label,
  action,
  params,
  color = 'blue',
  variant = 'filled',
  size = 'sm',
  icon,
  loading: loadingProp,
  disabled,
  confirm,
  openModal: modalToOpen,
  ...rest
}) => {
  const context = usePluginContext();
  const isLoading = loadingProp || (action && context.actionLoading[action]);

  const handleClick = async () => {
    if (modalToOpen) {
      context.openModal(modalToOpen);
      return;
    }

    if (action) {
      if (confirm) {
        const confirmMessage = typeof confirm === 'object' ? confirm.message : 'Are you sure?';
        const confirmTitle = typeof confirm === 'object' ? confirm.title : 'Confirm';

        // For now, use browser confirm. Could replace with Mantine modal later.
        if (!window.confirm(`${confirmTitle}\n\n${confirmMessage}`)) {
          return;
        }
      }

      await context.runAction(action, params || {});
    }
  };

  return (
    <Button
      color={color}
      variant={variant}
      size={size}
      loading={isLoading}
      disabled={disabled}
      onClick={handleClick}
      {...rest}
    >
      {label}
    </Button>
  );
};

export default PluginRenderer;
