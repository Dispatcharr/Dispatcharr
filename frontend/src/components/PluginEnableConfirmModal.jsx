import React from 'react';
import { Divider, List, Stack, Text, Tooltip } from '@mantine/core';
import { ShieldCheck } from 'lucide-react';
import ConfirmationDialog from './ConfirmationDialog.jsx';
import { usePluginStore } from '../store/plugins.jsx';
import {
  PluginSecurityWarning,
  PluginSupportDisclaimer,
  PluginWarningBox,
} from './PluginWarnings.jsx';

// Shown the first time a plugin is enabled (gated by !plugin.ever_enabled at
// each call site). Render this once per page that can enable a plugin
// (Plugins.jsx, PluginDetail.jsx, PluginBrowse.jsx). State lives in
// usePluginStore so every entry point (My Plugins grid, plugin detail page,
// post-import "Enable now", post-install "Enable plugin") shares one dialog
// instance instead of drifting.
export default function PluginEnableConfirmModal() {
  const { opened, plugin, purpose } = usePluginStore((s) => s.enableConfirm);
  const resolveEnableConfirmation = usePluginStore(
    (s) => s.resolveEnableConfirmation
  );
  const capabilities = plugin?.capabilities || [];
  const requiresRestart = capabilities.some((c) => c.requires_restart);
  const capabilityGroups = capabilities.reduce((groups, capability) => {
    const group =
      typeof capability.group === 'object' && capability.group
        ? capability.group
        : { id: capability.group || 'other', label: capability.group || 'Other', order: 99 };
    const groupId = group.id || 'other';
    groups[groupId] = {
      label: group.label || 'Other',
      order: Number.isFinite(group.order) ? group.order : 99,
      capabilities: [...(groups[groupId]?.capabilities || []), capability],
    };
    return groups;
  }, {});
  const sortedCapabilityGroups = Object.entries(capabilityGroups).sort(
    ([, left], [, right]) => left.order - right.order || left.label.localeCompare(right.label)
  );
  return (
    <ConfirmationDialog
      opened={opened}
      onClose={() => resolveEnableConfirmation(false)}
      onConfirm={() => resolveEnableConfirmation(true)}
      title={
        purpose === 'update'
          ? `Approve new capabilities for ${plugin?.name}?`
          : plugin ? `Enable ${plugin.name}?` : 'Enable third-party plugins?'
      }
      confirmLabel={purpose === 'update' ? 'I understand, update' : 'I understand, enable'}
      confirmColor="red"
      zIndex={300}
      message={
        <Stack gap="sm">
          <PluginSecurityWarning>
            {purpose === 'update'
              ? 'This update requests additional capabilities. Declining disables the plugin and clears its previous capability approvals.'
              : 'Plugins run server-side code with full access to your Dispatcharr instance and its data. Only enable plugins from developers you trust. Malicious plugins could read or modify data, call internal APIs, or perform unwanted actions. Review the source or trust the author before enabling.'}
          </PluginSecurityWarning>
          {capabilities.length > 0 && (
            <PluginWarningBox tone="info" icon={<ShieldCheck size={16} />}>
              <Text size="xs" fw={600} mb={4}>
                {purpose === 'update' ? 'This update requests:' : 'This plugin requests:'}
              </Text>
              <Stack gap={6}>
                {sortedCapabilityGroups.map(([groupId, group]) => (
                  <React.Fragment key={groupId}>
                    <div>
                      <Divider label={group.label} labelPosition="left" my={3} />
                      <List size="xs" spacing={3}>
                        {group.capabilities.map((cap) => (
                          <List.Item key={cap.id}>
                            <Tooltip
                              label={cap.description}
                              disabled={!cap.description}
                              multiline
                              w={300}
                              withArrow
                            >
                              <Text span fw={600} size="xs">
                                {cap.label}
                              </Text>
                            </Tooltip>
                          </List.Item>
                        ))}
                      </List>
                    </div>
                  </React.Fragment>
                ))}
              </Stack>
              {requiresRestart && (
                <>
                  <Divider my={8} />
                  <Text size="xs">
                    Enabling background tasks for this plugin requires a full
                    application restart to take effect. Restart the Dispatcharr
                    container after enabling.
                  </Text>
                </>
              )}
            </PluginWarningBox>
          )}
          <PluginSupportDisclaimer />
        </Stack>
      }
    />
  );
}
