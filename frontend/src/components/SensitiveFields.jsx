import {
  Children,
  cloneElement,
  forwardRef,
  isValidElement,
  useState,
} from 'react';
import { PasswordInput, Text, TextInput, Tooltip } from '@mantine/core';
import useScreenshotMode from '../store/useScreenshotMode.js';
import { HIDDEN_VALUE, redactUrls } from '../utils/screenshotMode.js';

const redactChildren = (children) =>
  Children.map(children, (child) => {
    if (typeof child === 'string') return redactUrls(child);
    if (isValidElement(child) && child.props.children !== undefined) {
      return cloneElement(child, {}, redactChildren(child.props.children));
    }
    return child;
  });

// Presentation only: source values, form state and clipboard actions stay intact.
export const ScreenshotText = ({ children }) => {
  const enabled = useScreenshotMode((state) => state.enabled);
  return enabled ? redactChildren(children) : children;
};

export const SensitiveValue = ({
  children,
  sensitive = true,
  withTooltip = false,
  tooltipProps,
  ...props
}) => {
  const enabled = useScreenshotMode((state) => state.enabled);
  const value = enabled && sensitive && children ? HIDDEN_VALUE : children;
  const text = <Text {...props}>{value}</Text>;
  return withTooltip ? (
    <Tooltip {...tooltipProps} label={value} disabled={!value}>
      {text}
    </Tooltip>
  ) : (
    text
  );
};

export const SensitiveTextInput = forwardRef(function SensitiveTextInput(
  { sensitive, ...props },
  ref
) {
  const enabled = useScreenshotMode((state) => state.enabled);
  const fieldName = [props.name, props.id, props.label]
    .filter((value) => typeof value === 'string')
    .join(' ');
  const value = props.value ?? props.defaultValue;
  const isSensitive =
    sensitive ??
    (props.type === 'password' ||
      /url|user.?name|password|passwd/i.test(fieldName) ||
      (typeof value === 'string' && /\b[a-z][a-z0-9+.-]*:\/\//i.test(value)));
  const hidden = enabled && isSensitive;
  return (
    <TextInput
      {...props}
      ref={ref}
      type={hidden ? 'password' : props.type}
      autoComplete={hidden ? 'off' : props.autoComplete}
    />
  );
});

export const SensitivePasswordInput = forwardRef(
  function SensitivePasswordInput(props, ref) {
    const enabled = useScreenshotMode((state) => state.enabled);
    const [visible, setVisible] = useState(false);
    const revealed = enabled ? false : (props.visible ?? visible);
    return (
      <PasswordInput
        {...props}
        ref={ref}
        visible={revealed}
        onVisibilityChange={(value) => {
          setVisible(value);
          props.onVisibilityChange?.(value);
        }}
        visibilityToggleButtonProps={{
          'aria-label': revealed ? 'Hide password' : 'Show password',
          tabIndex: 0,
          ...props.visibilityToggleButtonProps,
          disabled:
            enabled ||
            props.disabled ||
            props.visibilityToggleButtonProps?.disabled,
        }}
      />
    );
  }
);
