import React from 'react';
import { ActionIcon, Avatar, Box, Group, Text, Tooltip } from '@mantine/core';
import { BookOpen, ShieldAlert, ShieldCheck } from 'lucide-react';
import { DiscordIcon, GitHubIcon } from './icons.jsx';
import { isSafeHttpUrl } from '../utils/url.js';

/** Author name row, reused by both header layouts below. */
const AuthorRow = ({ plugin, onClick, justify = 'flex-start' }) => {
  if (!plugin.author) return null;
  return (
    <Group gap={6} align="center" wrap="nowrap" justify={justify}>
      <Text
        size="xs"
        c="dimmed"
        truncate
        onClick={onClick}
        style={{ minWidth: 0, maxWidth: '100%', ...(onClick ? { cursor: 'pointer' } : {}) }}
      >
        {plugin.author}
      </Text>
    </Group>
  );
};

/** Plain (non-interactive) verified-signature indicator, just an icon with
 * a hover tooltip, not a button, since it's status not an action. Sits next
 * to the plugin name rather than in the icon-link row below. */
const SignatureIndicator = ({ signatureVerified }) => {
  if (signatureVerified == null) return null;
  return signatureVerified ? (
    <Tooltip label="Verified Signature">
      <ShieldCheck size={14} color="var(--mantine-color-dimmed)" style={{ flexShrink: 0 }} />
    </Tooltip>
  ) : (
    <Tooltip label="Invalid Signature">
      <ShieldAlert size={14} color="var(--mantine-color-red-6)" style={{ flexShrink: 0 }} />
    </Tooltip>
  );
};

/**
 * Plugin name + verified-signature indicator, positioned like a `::after` on
 * the title rather than a sibling flex item: the indicator takes no layout
 * width, so a `justify="center"` ancestor centers on the title text alone
 * instead of centering the (title + badge) pair as one wider unit.
 */
const TitleWithSignature = ({ plugin, onClick, signatureVerified, lineClamp, fw = 600 }) => (
  <Box style={{ position: 'relative', display: 'inline-block', maxWidth: '100%' }}>
    <Text
      fw={fw}
      lineClamp={lineClamp}
      onClick={onClick}
      style={onClick ? { cursor: 'pointer' } : undefined}
    >
      {plugin.name}
    </Text>
    <Box style={{ position: 'absolute', left: '100%', top: '50%', transform: 'translateY(-50%)', marginLeft: 6 }}>
      <SignatureIndicator signatureVerified={signatureVerified} />
    </Box>
  </Box>
);

/** Docs/repo/discord icon-links, all icon+tooltip to match each other rather
 * than mixing pill badges and text links. */
const LinksRow = ({ helpUrl, repoUrl, discordThread, justify = 'flex-start' }) => {
  const safeHelpUrl = isSafeHttpUrl(helpUrl) ? helpUrl : null;
  const safeRepoUrl = isSafeHttpUrl(repoUrl) ? repoUrl : null;
  // Only rewrite to the discord:// deep-link scheme when the source matched
  // the strict https://discord.com/channels/ pattern; any other value still
  // has to pass the plain http(s) allowlist before it's rendered at all.
  const isDiscordChannel = /^https:\/\/discord\.com\/channels\//.test(discordThread || '');
  const safeDiscordHref = isDiscordChannel
    ? discordThread.replace('https://', 'discord://')
    : isSafeHttpUrl(discordThread)
      ? discordThread
      : null;

  if (!safeHelpUrl && !safeRepoUrl && !safeDiscordHref) return null;
  return (
    <Group gap={6} align="center" wrap="wrap" justify={justify} mt={4}>
      {safeHelpUrl && (
        <Tooltip label="Documentation">
          <ActionIcon
            variant="subtle"
            color="gray"
            size="sm"
            component="a"
            href={safeHelpUrl}
            target="_blank"
            rel="noreferrer"
            aria-label="Documentation"
          >
            <BookOpen size={16} />
          </ActionIcon>
        </Tooltip>
      )}
      {safeRepoUrl && (
        <Tooltip label="Source Repository">
          <ActionIcon
            variant="subtle"
            color="gray"
            size="sm"
            component="a"
            href={safeRepoUrl}
            target="_blank"
            rel="noopener noreferrer"
            aria-label="Source Repository"
          >
            <GitHubIcon size={16} />
          </ActionIcon>
        </Tooltip>
      )}
      {safeDiscordHref && (
        <Tooltip label="Discord Discussion">
          <ActionIcon
            variant="subtle"
            color="gray"
            size="sm"
            component="a"
            href={safeDiscordHref}
            {...(!isDiscordChannel && { target: '_blank', rel: 'noopener noreferrer' })}
            aria-label="Discord Discussion"
          >
            <DiscordIcon size={16} />
          </ActionIcon>
        </Tooltip>
      )}
    </Group>
  );
};

/**
 * Plugin avatar/name/author/docs-link block, shared by PluginCard and
 * PluginDetail. The repo/discord links and verified-signature badge are
 * optional; they only come from the deeper per-version manifest fetch
 * (PluginDetail has it, the plain card view doesn't), so they render as a
 * second row under the docs link only when passed.
 *
 * `centered` switches from the default horizontal layout (avatar left, text
 * stacked to its right) to a vertical, center-aligned one, used on the
 * plugin detail page, where the whole header block sits centered above the
 * Plugin Control pane instead of at the edge of a card.
 *
 * `hideLinks` skips the docs/repo/discord icon row entirely; the My Plugins
 * grid card doesn't need a Docs shortcut competing with its own Open button.
 */
const PluginHeader = ({
  plugin,
  avatarSize = 48,
  onClick,
  repoUrl,
  discordThread,
  signatureVerified,
  centered = false,
  hideLinks = false,
}) => {
  const avatar = (
    <Avatar
      src={plugin.logo_url}
      radius="sm"
      size={avatarSize}
      alt={`${plugin.name} logo`}
      onClick={onClick}
      style={onClick ? { cursor: 'pointer' } : undefined}
      imageProps={{ draggable: false }}
    >
      {plugin.name?.[0]?.toUpperCase()}
    </Avatar>
  );

  if (centered) {
    return (
      <Box style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center' }}>
        {avatar}
        <Box mt="xs">
          <TitleWithSignature plugin={plugin} onClick={onClick} signatureVerified={signatureVerified} />
        </Box>
        <AuthorRow plugin={plugin} onClick={onClick} justify="center" />
        {!hideLinks && (
          <LinksRow helpUrl={plugin.help_url} repoUrl={repoUrl} discordThread={discordThread} justify="center" />
        )}
      </Box>
    );
  }

  return (
    <Group gap="sm" align="flex-start" wrap="nowrap" style={{ minWidth: 0, flex: 1 }}>
      {avatar}
      <Box style={{ minWidth: 0, flex: 1 }}>
        <TitleWithSignature
          plugin={plugin}
          onClick={onClick}
          signatureVerified={signatureVerified}
          lineClamp={1}
        />
        <AuthorRow plugin={plugin} onClick={onClick} />
        {!hideLinks && (
          <LinksRow helpUrl={plugin.help_url} repoUrl={repoUrl} discordThread={discordThread} />
        )}
      </Box>
    </Group>
  );
};

export default PluginHeader;
