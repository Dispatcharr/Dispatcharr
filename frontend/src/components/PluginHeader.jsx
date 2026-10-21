import React from 'react';
import { ActionIcon, Avatar, Box, Button, Group, Text, Tooltip } from '@mantine/core';
import { BookOpen, GitBranch, Scale, ShieldAlert, ShieldCheck, User } from 'lucide-react';
import { DiscordIcon, GitHubIcon } from './icons.jsx';
import { isSafeHttpUrl } from '../utils/url.js';

/** Author name row, reused by both header layouts below. */
export const PluginMetadata = ({
  plugin,
  onClick,
  justify = 'flex-start',
  sourceRepoName,
  license,
  className,
  authorClassName,
  licenseClassName,
  separatorClassName,
  signatureVerified,
  trailing,
}) => {
  if (!plugin.author && !sourceRepoName && !license) return null;
  return (
    <Group
      className={className}
      gap={6}
      align="center"
      wrap="nowrap"
      justify={justify}
    >
      {plugin.author && (
        <Group
          className={authorClassName}
          gap={3}
          align="center"
          wrap="nowrap"
          style={{ minWidth: 0 }}
        >
          <User size={12} color="var(--mantine-color-dimmed)" />
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
      )}
      {plugin.author && license && <Text className={separatorClassName} size="xs" c="dimmed">•</Text>}
      {license && (
        <a
          className={licenseClassName}
          href={`https://spdx.org/licenses/${encodeURIComponent(license)}.html`}
          target="_blank"
          rel="noopener noreferrer"
          style={{ color: 'var(--mantine-color-dimmed)', display: 'flex', alignItems: 'center', gap: 3, textDecoration: 'none' }}
        >
          <Scale size={12} />
          <Text size="xs" c="dimmed">{license}</Text>
        </a>
      )}
      {(plugin.author || license) && sourceRepoName && <Text className={separatorClassName} size="xs" c="dimmed">•</Text>}
      {sourceRepoName && <PluginRepository name={sourceRepoName} />}
      <SignatureIndicator signatureVerified={signatureVerified} />
      {trailing}
    </Group>
  );
};

export const PluginRepository = ({ name }) => {
  if (!name) return null;
  return (
    <Group gap={3} align="center" wrap="nowrap">
      <GitBranch size={12} color="var(--mantine-color-dimmed)" />
      <Text size="xs" c="dimmed">{name}</Text>
    </Group>
  );
};

/** Plain (non-interactive) verified-signature indicator, just an icon with
 * a hover tooltip, not a button, since it's status not an action. */
export const SignatureIndicator = ({ signatureVerified }) => {
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
 * Plugin name, version, and verified-signature indicator. The signature comes
 * after the version so version information remains visually contiguous.
 */
const TitleWithSignature = ({ plugin, onClick, signatureVerified, lineClamp, fw = 600, version }) => (
  <Group gap={4} align="baseline" wrap="nowrap">
    <Text
      fw={fw}
      lineClamp={lineClamp}
      onClick={onClick}
      style={{ minWidth: 0, ...(onClick ? { cursor: 'pointer' } : {}) }}
    >
      {plugin.name}
    </Text>
    {version && <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>v{version}</Text>}
    <SignatureIndicator signatureVerified={signatureVerified} />
  </Group>
);

/** Docs/repo/discord icon-links, all icon+tooltip to match each other rather
 * than mixing pill badges and text links. */
export const PluginLinks = ({
  helpUrl,
  repoUrl,
  discordThread,
  justify = 'flex-start',
  compact = false,
  asButtons = false,
}) => {
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
    <Group
      gap={asButtons ? 'xs' : 6}
      align="center"
      wrap={compact ? 'nowrap' : 'wrap'}
      justify={justify}
      mt={compact ? 0 : 4}
      grow={asButtons}
      style={asButtons ? { width: '100%' } : undefined}
    >
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
        asButtons ? (
          <Button
            size="xs"
            variant="default"
            leftSection={<GitHubIcon size={14} />}
            component="a"
            href={safeRepoUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            Source
          </Button>
        ) : (
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
        )
      )}
      {safeDiscordHref && (
        asButtons ? (
          <Button
            size="xs"
            variant="default"
            leftSection={<DiscordIcon size={14} />}
            component="a"
            href={safeDiscordHref}
            {...(!isDiscordChannel && { target: '_blank', rel: 'noopener noreferrer' })}
          >
            Discord
          </Button>
        ) : (
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
        )
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
  version = plugin.version,
  sourceRepoName,
  license,
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
          <TitleWithSignature plugin={plugin} onClick={onClick} signatureVerified={signatureVerified} version={version} />
        </Box>
        <PluginMetadata plugin={plugin} onClick={onClick} justify="center" sourceRepoName={sourceRepoName} license={license} />
        {!hideLinks && (
          <PluginLinks helpUrl={plugin.help_url} repoUrl={repoUrl} discordThread={discordThread} justify="center" />
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
          version={version}
        />
        <PluginMetadata plugin={plugin} onClick={onClick} sourceRepoName={sourceRepoName} license={license} />
        {!hideLinks && (
          <PluginLinks helpUrl={plugin.help_url} repoUrl={repoUrl} discordThread={discordThread} />
        )}
      </Box>
    </Group>
  );
};

export default PluginHeader;
