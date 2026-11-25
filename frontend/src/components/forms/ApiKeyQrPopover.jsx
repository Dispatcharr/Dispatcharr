import React, { useState } from 'react';
import {
  ActionIcon,
  Popover,
  PopoverDropdown,
  PopoverTarget,
  Stack,
  Text,
} from '@mantine/core';
import { QrCode } from 'lucide-react';
import { QRCodeSVG } from 'qrcode.react';
import useSettingsStore from '../../store/settings';
import { getPublicBaseUrl } from '../../utils/networkUtils';
import { buildUserApiKeyQrValue } from '../../utils/forms/ApiKeyQrUtils';
import dispatcharrLogo from '../../images/logo.png';

const QR_SIZE = 200;

// Module-level so the renderer receives a stable reference. The mark covers
// roughly 5% of the code, well inside what error correction level H recovers.
const QR_LOGO = {
  src: dispatcharrLogo,
  height: 44,
  width: 44,
  excavate: true,
};

// Only mounted while the popover is open, so the payload is built and the
// code is generated on demand.
const ApiKeyQr = ({ apiKey, user }) => {
  const envMode = useSettingsStore((s) => s.environment?.env_mode);

  return (
    <QRCodeSVG
      role="img"
      aria-label="QR code containing the API key"
      value={buildUserApiKeyQrValue({
        apiKey,
        baseUrl: getPublicBaseUrl(envMode),
        username: user?.username,
        firstName: user?.first_name,
        lastName: user?.last_name,
        email: user?.email,
      })}
      size={QR_SIZE}
      bgColor="#ffffff"
      fgColor="#000000"
      level="H"
      marginSize={4}
      imageSettings={QR_LOGO}
    />
  );
};

const ApiKeyQrPopover = ({ apiKey, user = null }) => {
  const [opened, setOpened] = useState(false);

  return (
    <Popover
      opened={opened}
      onChange={setOpened}
      position="bottom-end"
      withArrow
      shadow="md"
    >
      <PopoverTarget>
        <ActionIcon
          variant="transparent"
          size="sm"
          color="white"
          aria-label="Show API key QR code"
          onClick={() => setOpened((current) => !current)}
        >
          <QrCode />
        </ActionIcon>
      </PopoverTarget>
      <PopoverDropdown>
        <Stack gap="xs" align="center">
          <Text size="sm" fw={500}>
            Scan API Key
          </Text>
          {opened && <ApiKeyQr apiKey={apiKey} user={user} />}
        </Stack>
      </PopoverDropdown>
    </Popover>
  );
};

export default ApiKeyQrPopover;
