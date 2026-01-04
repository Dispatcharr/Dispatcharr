import React, { useState } from 'react';
import { showNotification } from '../../utils/notificationUtils.js';
import { Field } from '../Field.jsx';
import {
  ActionIcon,
  Button,
  Card,
  Divider,
  Group,
  Stack,
  Switch,
  Text,
} from '@mantine/core';
import { Trash2 } from 'lucide-react';
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

const PluginActionList = ({ plugin, enabled, running, handlePluginRun }) => {
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
        loading={running}
        disabled={!enabled}
        onClick={() => handlePluginRun(action)}
        size="xs"
      >
        {running ? 'Running…' : 'Run'}
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
  const [running, setRunning] = useState(false);
  const [enabled, setEnabled] = useState(!!plugin.enabled);
  const [lastResult, setLastResult] = useState(null);

  // Keep local enabled state in sync with props (e.g., after import + enable)
  React.useEffect(() => {
    setEnabled(!!plugin.enabled);
  }, [plugin.enabled]);
  // Sync settings if plugin changes identity
  React.useEffect(() => {
    setSettings(plugin.settings || {});
  }, [plugin.key]);

  const updateField = (id, val) => {
    setSettings((prev) => ({ ...prev, [id]: val }));
  };

  const save = async () => {
    setSaving(true);
    try {
      await onSaveSettings(plugin.key, settings);
      showNotification({
        title: 'Saved',
        message: `${plugin.name} settings updated`,
        color: 'green',
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
      setEnabled(next);
      const resp = await onToggleEnabled(plugin.key, next);
      if (next && resp?.ever_enabled) {
        plugin.ever_enabled = true;
      }
    };
  };

  const handlePluginRun = async (a) => {
    setRunning(true);
    setLastResult(null);
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
      setRunning(false);
    }
  };

  return (
    <Card
      shadow="sm"
      radius="md"
      withBorder
      opacity={!missing && enabled ? 1 : 0.6}
    >
      <Group justify="space-between" mb="xs" align="center">
        <div>
          <Text fw={600}>{plugin.name}</Text>
          <Text size="sm" c="dimmed">
            {plugin.description}
          </Text>
        </div>
        <Group gap="xs" align="center">
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

      {missing && (
        <Text size="sm" c="red">
          Missing plugin files. Re-import or delete this entry.
        </Text>
      )}

      {!missing && plugin.fields && plugin.fields.length > 0 && (
        <Stack gap="xs" mt="sm">
          <PluginFieldList
            plugin={plugin}
            settings={settings}
            updateField={updateField}
          />
          <Group>
            <Button loading={saving} onClick={save} variant="default" size="xs">
              Save Settings
            </Button>
          </Group>
        </Stack>
      )}

      {!missing && plugin.actions && plugin.actions.length > 0 && (
        <>
          <Divider my="sm" />
          <Stack gap="xs">
            <PluginActionList
              plugin={plugin}
              enabled={enabled}
              running={running}
              handlePluginRun={handlePluginRun}
            />
            <PluginActionStatus running={running} lastResult={lastResult} />
          </Stack>
        </>
      )}
    </Card>
  );
};

export default PluginCard;