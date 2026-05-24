import React from 'react';
import {
  Box,
  Button,
  Divider,
  Group,
  Modal,
  SimpleGrid,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import { BookOpen, Github, Heart, Users } from 'lucide-react';
import { DiscordIcon } from './icons.jsx';
import logo from '../images/logo.png';
import useSettingsStore from '../store/settings';

const AboutModal = ({ isOpen, onClose }) => {
  const appVersion = useSettingsStore((s) => s.version);
  const versionString = `v${appVersion?.version || '0.0.0'}${appVersion?.timestamp ? `-${appVersion.timestamp}` : ''}`;

  return (
    <Modal
      opened={isOpen}
      onClose={onClose}
      title="About Dispatcharr"
      centered
      size="md"
    >
      <Stack gap="lg">
        <Group justify="center" gap="md">
          <img src={logo} alt="Dispatcharr" width={56} />
          <Stack gap={2}>
            <Text fw={700} size="xl">
              Dispatcharr
            </Text>
            <Text size="sm" c="dimmed">
              {versionString}
            </Text>
          </Stack>
        </Group>

        <Divider />

        <SimpleGrid cols={2} spacing="sm">
          <Tooltip label="Visit the Dispatcharr documentation" position="top">
            <Button
              component="a"
              href="https://dispatcharr.github.io/Dispatcharr-Docs/"
              target="_blank"
              rel="noopener noreferrer"
              variant="default"
              leftSection={<BookOpen size={15} />}
              fullWidth
            >
              Documentation
            </Button>
          </Tooltip>
          <Tooltip label="Join our Discord community" position="top">
            <Button
              component="a"
              href="https://discord.gg/Sp45V5BcxU"
              target="_blank"
              rel="noopener noreferrer"
              variant="default"
              leftSection={<DiscordIcon size={15} />}
              fullWidth
            >
              Discord
            </Button>
          </Tooltip>
          <Tooltip label="View source on GitHub" position="top">
            <Button
              component="a"
              href="https://github.com/Dispatcharr/Dispatcharr"
              target="_blank"
              rel="noopener noreferrer"
              variant="default"
              leftSection={<Github size={15} />}
              fullWidth
            >
              GitHub
            </Button>
          </Tooltip>
          <Tooltip
            label="Support Dispatcharr on Open Collective"
            position="top"
          >
            <Button
              component="a"
              href="https://opencollective.com/dispatcharr/contribute"
              target="_blank"
              rel="noopener noreferrer"
              variant="default"
              color="pink"
              leftSection={<Heart size={15} />}
              fullWidth
            >
              Donate
            </Button>
          </Tooltip>
        </SimpleGrid>

        <Divider />

        <Stack gap="xs">
          <Group gap="xs">
            <Users size={16} />
            <Text size="sm" fw={500}>
              Contributors
            </Text>
          </Group>
          <Text size="sm" c="dimmed">
            Dispatcharr is built by the community, for the community. Thank you
            to every contributor, tester, and supporter who has helped make this
            project what it is.
          </Text>
        </Stack>

        <Tooltip label="Remembering Jesse Mann" position="top" withArrow>
          <Box
            style={{
              background: 'var(--mantine-color-dark-6)',
              borderRadius: 'var(--mantine-radius-sm)',
              borderLeft: '3px solid var(--mantine-color-pink-5)',
              padding: '10px 14px',
              cursor: 'default',
            }}
          >
            <Text size="sm" c="dimmed">
              In memory of{' '}
              <Text span fw={600} c="gray.3">
                Jesse Mann
              </Text>
              .
            </Text>
          </Box>
        </Tooltip>
      </Stack>
    </Modal>
  );
};

export default AboutModal;
