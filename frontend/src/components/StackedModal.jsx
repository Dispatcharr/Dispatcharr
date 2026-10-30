import { useEffect, useId, useRef } from 'react';
import { Modal, useModalStackContext } from '@mantine/core';
import classes from './StackedModal.module.css';

// Source editors mount some child dialogs only while open. Mantine's stack
// needs an explicit removal on unmount as well as on opened=false.
export default function StackedModal({
  stackId,
  keepVisibleInStack = false,
  ...props
}) {
  const generatedId = useId();
  const id = stackId || generatedId;
  const stack = useModalStackContext();
  const background = !!(
    keepVisibleInStack &&
    props.opened &&
    stack?.currentId &&
    stack.currentId !== id
  );
  const currentStack = useRef(stack);
  currentStack.current = stack;

  useEffect(() => () => currentStack.current?.removeModal(id), [id]);

  return (
    <Modal
      {...props}
      stackId={id}
      inert={background || props.inert}
      className={
        [props.className, background && classes.background]
          .filter(Boolean)
          .join(' ') || undefined
      }
      // Keep the shared stack below portalled comboboxes. Explicit high
      // z-index values are still respected outside a Modal.Stack.
      {...(stack ? { zIndex: 200 } : {})}
    />
  );
}
