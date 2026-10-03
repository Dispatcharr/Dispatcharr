import React, { useState } from 'react';
import { Button } from '@mantine/core';
import API from '../api';

// The whole body arrives before the browser saves anything; say so.
const DownloadLogButton = ({ name, ...props }) => {
  const [busy, setBusy] = useState(false);
  return (
    <Button
      size="xs"
      variant="subtle"
      loading={busy}
      onClick={async () => {
        setBusy(true);
        try {
          await API.downloadLogFile(name);
        } catch {
          // errorNotification already surfaced the failure
        } finally {
          setBusy(false);
        }
      }}
      {...props}
    >
      Download
    </Button>
  );
};

export default DownloadLogButton;
