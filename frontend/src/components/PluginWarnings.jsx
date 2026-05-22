import React from 'react';
import { Box, Text } from '@mantine/core';
import { AlertTriangle, Info, OctagonAlert } from 'lucide-react';
import dispatcharrLogo from '../images/logo.png';

export const PluginSecurityWarning = ({ children }) => (
  <Box
    style={{
      background: 'rgba(239, 68, 68, 0.1)',
      border: '1px solid rgba(239, 68, 68, 0.35)',
      borderRadius: 'var(--mantine-radius-sm)',
      padding: '10px 14px',
      display: 'flex',
      gap: 10,
      alignItems: 'flex-start',
    }}
  >
    <Box style={{ color: '#ef4444', flexShrink: 0, paddingTop: 1 }}>
      <OctagonAlert size={16} />
    </Box>
    <Text size="xs" style={{ color: '#f87171' }}>
      {children}
    </Text>
  </Box>
);

export const PluginSupportDisclaimer = () => (
  <Box
    style={{
      background: 'rgba(20, 145, 126, 0.1)',
      border: '1px solid rgba(20, 145, 126, 0.35)',
      borderRadius: 'var(--mantine-radius-sm)',
      padding: '10px 14px',
      display: 'flex',
      gap: 10,
      alignItems: 'flex-start',
    }}
  >
    <Box style={{ flexShrink: 0, paddingTop: 1 }}>
      <img
        src={dispatcharrLogo}
        alt="Dispatcharr"
        width={16}
        height={16}
        draggable={false}
        style={{ display: 'block', objectFit: 'contain' }}
      />
    </Box>
    <Text size="xs" style={{ color: '#4db8a8' }}>
      Dispatcharr community support cannot assist with third-party plugin
      issues. For help, use the plugin&apos;s Discord thread or submit an issue
      on the plugin&apos;s repository.
    </Text>
  </Box>
);

export const PluginDowngradeWarning = ({ children }) => (
  <Box
    style={{
      background: 'rgba(249, 115, 22, 0.1)',
      border: '1px solid rgba(249, 115, 22, 0.35)',
      borderRadius: 'var(--mantine-radius-sm)',
      padding: '10px 14px',
      display: 'flex',
      gap: 10,
      alignItems: 'flex-start',
    }}
  >
    <Box style={{ color: '#f97316', flexShrink: 0, paddingTop: 1 }}>
      <AlertTriangle size={16} />
    </Box>
    <Text size="xs" style={{ color: '#fb923c' }}>
      {children}
    </Text>
  </Box>
);

export const PluginInfoNote = ({ children }) => (
  <Box
    style={{
      background: 'rgba(148, 163, 184, 0.08)',
      border: '1px solid rgba(148, 163, 184, 0.25)',
      borderRadius: 'var(--mantine-radius-sm)',
      padding: '10px 14px',
      display: 'flex',
      gap: 10,
      alignItems: 'flex-start',
    }}
  >
    <Box style={{ color: '#94a3b8', flexShrink: 0, paddingTop: 1 }}>
      <Info size={16} />
    </Box>
    <Text size="xs" style={{ color: '#cbd5e1' }}>
      {children}
    </Text>
  </Box>
);

export const PluginRestartWarning = () => (
  <Box
    style={{
      background: 'rgba(234, 179, 8, 0.1)',
      border: '1px solid rgba(234, 179, 8, 0.35)',
      borderRadius: 'var(--mantine-radius-sm)',
      padding: '10px 14px',
      display: 'flex',
      gap: 10,
      alignItems: 'flex-start',
    }}
  >
    <Box style={{ color: '#eab308', flexShrink: 0, paddingTop: 1 }}>
      <AlertTriangle size={16} />
    </Box>
    <Text size="xs" style={{ color: '#ca8a04' }}>
      Importing a plugin may briefly restart the backend (you might see a
      temporary disconnect). Please wait a few seconds and the app will
      reconnect automatically.
    </Text>
  </Box>
);
