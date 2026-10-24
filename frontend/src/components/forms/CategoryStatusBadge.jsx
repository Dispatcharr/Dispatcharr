import { Badge, Tooltip, UnstyledButton } from '@mantine/core';
import editorClasses from './AccountEditor.module.css';

const CategoryStatusBadge = ({ category, onToggle }) => {
  const badge = (
    <Badge
      component="span"
      className={editorClasses.categoryStatusBadge}
      size="sm"
      radius="sm"
      color={category.ignored ? 'orange' : category.enabled ? 'green' : 'gray'}
      variant={category.enabled ? 'filled' : 'light'}
    >
      {category.ignored ? 'Ignored' : category.enabled ? 'Enabled' : 'Disabled'}
    </Badge>
  );

  if (category.ignored) return badge;

  const action = category.enabled ? 'Disable category' : 'Enable category';
  return (
    <Tooltip
      label={action}
      withArrow
      events={{ hover: true, focus: true, touch: true }}
    >
      <UnstyledButton
        type="button"
        className={editorClasses.categoryStatusButton}
        aria-label={`${action} ${category.name}`}
        onClick={onToggle}
      >
        {badge}
      </UnstyledButton>
    </Tooltip>
  );
};

export default CategoryStatusBadge;
