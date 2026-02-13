import React, { useState } from 'react';
import { showNotification } from '../../utils/notificationUtils.js';
import { Field } from '../Field.jsx';
import {
  ActionIcon,
  Anchor,
  Box,
  Avatar,
  Button,
  Card,
  Divider,
  Group,
  Stack,
  Switch,
  Text,
  UnstyledButton,
} from '@mantine/core';
import { ChevronDown, ChevronRight, Trash2 } from 'lucide-react';
import { getConfirmationDetails } from '../../utils/cards/PluginCardUtils.js';

const PluginFieldList = ({ plugin, settings, updateField }) => {
  return plugin.fields.map((f) => (
    <Field
      key={f.id}
      field={f}
      value={settings?.[f.id]}
      onChange={updateField}
    />
  ));
};

const PluginActionList = ({
  plugin,
  enabled,
  runningActionId,
  handlePluginRun,
}) => {
  return plugin.actions.map((action) => (
    <Group key={action.id} justify="space-between">
      <div>
        <Text>{action.label}</Text>
        {action.description && (
          <Text size="sm" c="dimmed">
            {action.description}
          </Text>
        )}
      </div>
      <Button
        loading={runningActionId === action.id}
        disabled={!enabled || runningActionId === action.id}
        onClick={() => handlePluginRun(action)}
        size="xs"
        variant={action.button_variant || 'filled'}
        color={action.button_color}
      >
        {runningActionId === action.id
          ? 'Running…'
          : action.button_label || 'Run'}
      </Button>
    </Group>
  ));
};

const PluginActionStatus = ({ running, lastResult }) => {
  return (
    <>
      {running && (
        <Text size="sm" c="dimmed">
          Running action… please wait
        </Text>
      )}
      {!running && lastResult?.file && (
        <Text size="sm" c="dimmed">
          Output: {lastResult.file}
        </Text>
      )}
      {!running && lastResult?.error && (
        <Text size="sm" c="red">
          Error: {String(lastResult.error)}
        </Text>
      )}
    </>
  );
};

const PluginCard = ({
  plugin,
  onSaveSettings,
  onRunAction,
  onToggleEnabled,
  onRequireTrust,
  onRequestDelete,
  onRequestConfirm,
}) => {
  const [settings, setSettings] = useState(plugin.settings || {});
  const [saving, setSaving] = useState(false);
  const [runningActionId, setRunningActionId] = useState(null);
  const [enabled, setEnabled] = useState(!!plugin.enabled);
  const [lastResult, setLastResult] = useState(null);
  const [expanded, setExpanded] = useState(!!plugin.enabled);

  // Keep local enabled state in sync with props (e.g., after import + enable)
  React.useEffect(() => {
    setEnabled(!!plugin.enabled);
  }, [plugin.enabled]);
  React.useEffect(() => {
    if (!plugin.enabled) {
      setExpanded(false);
    }
  }, [plugin.enabled]);
  // Sync settings if plugin changes identity
  React.useEffect(() => {
    setSettings(plugin.settings || {});
  }, [plugin.key, plugin.settings]);

  const updateField = (id, val) => {
    setSettings((prev) => ({ ...prev, [id]: val }));
  };

  const save = async () => {
    setSaving(true);
    try {
      const result = await onSaveSettings(plugin.key, settings);
      if (result) {
        showNotification({
          title: 'Saved',
          message: `${plugin.name} settings updated`,
          color: 'green',
        });
      } else {
        showNotification({
          title: `${plugin.name} error`,
          message: 'Failed to update settings',
          color: 'red',
        });
      }
    } catch (e) {
      showNotification({
        title: `${plugin.name} error`,
        message: e?.message || 'Failed to update settings',
        color: 'red',
      });
    } finally {
      setSaving(false);
    }
  };

  const missing = plugin.missing;

  const handleEnableChange = () => {
    return async (e) => {
      const next = e.currentTarget.checked;
      if (next && !plugin.ever_enabled && onRequireTrust) {
        const ok = await onRequireTrust(plugin);
        if (!ok) {
          // Revert
          setEnabled(false);
          return;
        }
      }
      const previous = enabled;
      setEnabled(next);
      try {
        const resp = await onToggleEnabled(plugin.key, next);
        if (!resp?.success) {
          setEnabled(previous);
          return;
        }
      } catch (e) {
        setEnabled(previous);
      }
    };
  };

  const handlePluginRun = async (a) => {
    try {
      // Determine if confirmation is required from action metadata or fallback field
      const { requireConfirm, confirmTitle, confirmMessage } =
        getConfirmationDetails(a, plugin, settings);

      if (requireConfirm) {
        const confirmed = await onRequestConfirm(confirmTitle, confirmMessage);

        if (!confirmed) {
          // User canceled, abort the action
          return;
        }
      }

      setRunningActionId(a.id);
      setLastResult(null);

      // Save settings before running to ensure backend uses latest values
      try {
        await onSaveSettings(plugin.key, settings);
      } catch (e) {
        /* ignore, run anyway */
      }
      const resp = await onRunAction(plugin.key, a.id);
      if (resp?.success) {
        setLastResult(resp.result || {});
        const msg = resp.result?.message || 'Plugin action completed';
        showNotification({
          title: plugin.name,
          message: msg,
          color: 'green',
        });
      } else {
        const err = resp?.error || 'Unknown error';
        setLastResult({ error: err });
        showNotification({
          title: `${plugin.name} error`,
          message: String(err),
          color: 'red',
        });
      }
    } finally {
      setRunningActionId(null);
    }
  };

  const toggleExpanded = () => {
    setExpanded((prev) => !prev);
  };

  return (
    <Card
      shadow="sm"
      radius="md"
      withBorder
      style={{ opacity: !missing && enabled ? 1 : 0.6 }}
    >
      <Group justify="space-between" mb="xs" align="flex-start" wrap="nowrap">
        <Group
          gap="sm"
          align="flex-start"
          wrap="nowrap"
          style={{ minWidth: 0, flex: 1 }}
        >
          <ActionIcon
            variant="subtle"
            size="sm"
            onClick={toggleExpanded}
            title={expanded ? 'Collapse settings' : 'Expand settings'}
          >
            {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          </ActionIcon>
          {plugin.logo_url && (
            <Avatar
              src={plugin.logo_url}
              radius="sm"
              size={44}
              alt={`${plugin.name} logo`}
            />
          )}
          <UnstyledButton
            onClick={toggleExpanded}
            style={{ minWidth: 0, flex: 1, textAlign: 'left' }}
          >
            <Box style={{ minWidth: 0, flex: 1 }}>
              <Text fw={600}>{plugin.name}</Text>
              <Text size="sm" c="dimmed">
                {plugin.description}
              </Text>
              {(plugin.author || plugin.help_url) && (
                <Group gap="xs" mt={2}>
                  {plugin.author && (
                    <Text size="xs" c="dimmed">
                      By {plugin.author}
                    </Text>
                  )}
                  {plugin.help_url && (
                    <Anchor
                      href={plugin.help_url}
                      target="_blank"
                      rel="noreferrer"
                      size="xs"
                      onClick={(e) => e.stopPropagation()}
                    >
                      Docs
                    </Anchor>
                  )}
                </Group>
              )}
            </Box>
          </UnstyledButton>
        </Group>
        <Group gap="xs" align="center" wrap="nowrap" style={{ flexShrink: 0 }}>
          <ActionIcon
            variant="subtle"
            color="red"
            title="Delete plugin"
            onClick={() => onRequestDelete && onRequestDelete(plugin)}
          >
            <Trash2 size={16} />
          </ActionIcon>
          <Text size="xs" c="dimmed">
            v{plugin.version || '1.0.0'}
          </Text>
          <Switch
            checked={!missing && enabled}
            onChange={handleEnableChange()}
            size="xs"
            onLabel="On"
            offLabel="Off"
            disabled={missing}
          />
        </Group>
      </Group>

      {(missing || plugin.legacy) && (
        <Text size="sm" c={missing ? 'red' : 'yellow'}>
          {missing
            ? 'Missing plugin files. Re-import or delete this entry.'
            : 'Please update or ask the developer to add plugin.json.'}
        </Text>
      )}

      {expanded &&
        !missing &&
        enabled &&
        plugin.fields &&
        plugin.fields.length > 0 && (
          <Stack gap="xs" mt="sm">
            <PluginFieldList
              plugin={plugin}
              settings={settings}
              updateField={updateField}
            />
            <Group>
              <Button
                loading={saving}
                onClick={save}
                variant="default"
                size="xs"
              >
                Save Settings
              </Button>
            </Group>
          </Stack>
        )}

      {expanded &&
        !missing &&
        enabled &&
        plugin.actions &&
        plugin.actions.length > 0 && (
          <>
            <Divider my="sm" />
            <Stack gap="xs">
              <PluginActionList
                plugin={plugin}
                enabled={enabled}
                runningActionId={runningActionId}
                handlePluginRun={handlePluginRun}
              />
              <PluginActionStatus
                running={!!runningActionId}
                lastResult={lastResult}
              />
            </Stack>
          </>
        )}
    </Card>
  );
};

export default PluginCard;
