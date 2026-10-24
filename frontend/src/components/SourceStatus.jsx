import { Badge, Box, Text, Tooltip } from '@mantine/core';
import { ScreenshotText } from './SensitiveFields.jsx';
import classes from './tables/M3UsTable.module.css';

const summaryOf = (message) => {
  const firstLine = message.trim().split(/[\r\n]+/)[0];
  const prefix = firstLine.split(/:\s+/)[0];
  const summary = (prefix.length >= 8 ? prefix : firstLine)
    .replace(/\s+/g, ' ')
    .trim();
  return summary.length > 100 ? `${summary.slice(0, 97).trimEnd()}…` : summary;
};

export default function SourceStatus({
  label,
  color,
  messages = [],
  messageColor,
}) {
  const details = messages.filter(
    (message) => typeof message === 'string' && message.trim()
  );
  const status = (
    <Box
      component="span"
      role="group"
      aria-label={`${label} status`}
      tabIndex={details.length ? 0 : undefined}
      className={classes.status}
    >
      <Badge
        component="span"
        variant="light"
        color={color}
        className={classes.statusBadge}
      >
        {label}
      </Badge>
      {details.length > 0 && (
        <Text
          component="span"
          size="xs"
          c={messageColor || 'dimmed'}
          truncate
          className={classes.statusMessage}
        >
          <ScreenshotText>{summaryOf(details[0])}</ScreenshotText>
        </Text>
      )}
    </Box>
  );
  return details.length ? (
    <Tooltip
      label={<ScreenshotText>{details.join('\n')}</ScreenshotText>}
      multiline
      className={classes.detailTooltip}
      events={{ hover: true, focus: true, touch: true }}
      withArrow
    >
      {status}
    </Tooltip>
  ) : (
    status
  );
}
