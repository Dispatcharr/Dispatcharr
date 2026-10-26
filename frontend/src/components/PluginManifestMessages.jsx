import React, { useEffect, useState } from 'react';
import { ActionIcon, Alert, Button, Group, Stack, Text, Tooltip } from '@mantine/core';
import { AlertTriangle, CheckCircle2, CircleAlert, Info, ExternalLink, GitBranch, X } from 'lucide-react';
import API from '../api.js';

const severityPresentation = {
  info: { color: 'blue', icon: <Info size={18} /> },
  success: { color: 'green', icon: <CheckCircle2 size={18} /> },
  warning: { color: 'orange', icon: <AlertTriangle size={18} /> },
  critical: { color: 'red', icon: <CircleAlert size={18} /> },
};

const linkLabel = (link) => {
  try {
    return `Open ${new URL(link).hostname}`;
  } catch {
    return 'Open link';
  }
};

export default function PluginManifestMessages() {
  const [messages, setMessages] = useState([]);

  useEffect(() => {
    let active = true;
    API.getPluginManifestMessages().then((result) => {
      if (active) setMessages(result);
    });
    return () => { active = false; };
  }, []);

  const dismiss = async (messageId) => {
    try {
      await API.dismissPluginManifestMessage(messageId);
      setMessages((current) => current.filter((message) => message.id !== messageId));
    } catch {
      // The API layer presents the request failure; retain the message to retry.
    }
  };

  if (!messages.length) return null;

  return (
    <Stack gap="xs" mb="md">
      {messages.map((message) => {
        const presentation = severityPresentation[message.severity] || severityPresentation.info;
        const sourceRepo = message.source_repo || 'Dispatcharr/Plugins';
        return (
          <Alert key={message.id} color={presentation.color} variant="light">
            <Group justify="space-between" align="flex-start" wrap="nowrap">
              <Group gap={6} align="flex-start" wrap="nowrap" style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    color: `var(--mantine-color-${presentation.color}-6)`,
                    display: 'flex',
                    flex: '0 0 20px',
                    height: 20,
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  {presentation.icon}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  {message.title && (
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        flexWrap: 'wrap',
                        gap: 6,
                        minHeight: 20,
                        marginBottom: 4,
                      }}
                    >
                      <Text size="sm" fw={600} c={presentation.color} style={{ lineHeight: '20px' }}>
                        {message.title}
                      </Text>
                      <Tooltip label={`Message from ${sourceRepo}`} withArrow>
                        <span
                          style={{
                            alignItems: 'center',
                            color: `var(--mantine-color-${presentation.color}-6)`,
                            display: 'inline-flex',
                            fontSize: 'var(--mantine-font-size-xs)',
                            gap: 4,
                            lineHeight: '20px',
                            opacity: 0.7,
                            whiteSpace: 'nowrap',
                          }}
                        >
                          <GitBranch size={14} />
                          <span>{sourceRepo}</span>
                        </span>
                      </Tooltip>
                    </div>
                  )}
                  <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>{message.body}</Text>
                </div>
              </Group>
              <Group gap="xs" wrap="nowrap">
                {message.link && (
                  <Button
                    component="a"
                    href={message.link}
                    target="_blank"
                    rel="noopener noreferrer"
                    size="xs"
                    variant="light"
                    color={presentation.color}
                    rightSection={<ExternalLink size={13} />}
                  >
                    {linkLabel(message.link)}
                  </Button>
                )}
                <ActionIcon
                  aria-label="Dismiss message"
                  variant="subtle"
                  color={presentation.color}
                  onClick={() => dismiss(message.id)}
                >
                  <X size={16} />
                </ActionIcon>
              </Group>
            </Group>
          </Alert>
        );
      })}
    </Stack>
  );
}
