import { Text, } from '@mantine/core';

// Short preview that triggers the details modal when clicked
const RecordingSynopsis = ({ description, onOpen }) => {
  const truncated = description?.length > 140;
  const preview = truncated
    ? `${description.slice(0, 140).trim()}...`
    : description;

  if (!description) return null;

  return (
    <Text
      size="xs"
      c="dimmed"
      lineClamp={2}
      title={description}
      onClick={() => onOpen?.()}
      style={{ cursor: 'pointer' }}
    >
      {preview}
    </Text>
  );
};

export default RecordingSynopsis;