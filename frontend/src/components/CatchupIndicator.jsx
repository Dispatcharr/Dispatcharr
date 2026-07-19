import { Badge, Box, Tooltip } from '@mantine/core';
import { History } from 'lucide-react';

const CATCHUP_ICON_COLOR = '#9ca3af';

export function formatCatchupTooltip(catchupDays) {
  if (catchupDays > 0) {
    const dayWord = catchupDays === 1 ? 'day' : 'days';
    return `Catch-up enabled (${catchupDays} ${dayWord} archive)`;
  }
  return 'Catch-up enabled';
}

export default function CatchupIndicator({
  isCatchup,
  catchupDays = 0,
  variant = 'icon',
  size = 14,
}) {
  if (!isCatchup) {
    return null;
  }

  const label = formatCatchupTooltip(catchupDays);

  if (variant === 'badge') {
    return (
      <Tooltip label={label}>
        <Badge
          size="xs"
          variant="light"
          color="violet"
          leftSection={<History size={12} aria-hidden="true" />}
        >
          Catch-up
        </Badge>
      </Tooltip>
    );
  }

  return (
    <Tooltip label={label}>
      <Box
        component="span"
        role="img"
        aria-label={label}
        style={{ display: 'inline-flex' }}
      >
        <History size={size} color={CATCHUP_ICON_COLOR} aria-hidden="true" />
      </Box>
    </Tooltip>
  );
}
