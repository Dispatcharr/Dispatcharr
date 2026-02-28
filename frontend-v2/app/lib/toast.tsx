/**
 * Toast notification utility
 * Wraps Sonner with a Mantine-like API for managing toasts
 */

import { toast as sonnerToast, type ExternalToast } from "sonner";

export type ToastId = string | number;

export interface ToastOptions extends ExternalToast {
  title?: string;
  message?: string;
  autoClose?: number | false;
  withCloseButton?: boolean;
}

/**
 * Toast utility with Mantine-like API
 */
export const toast = {
  /**
   * Show a toast notification
   */
  show: (options: ToastOptions): ToastId => {
    const { title, message, autoClose, withCloseButton = true, ...rest } = options;

    const content = title ? (
      <div>
        <div className="font-medium">{title}</div>
        {message && <div className="text-sm text-muted-foreground">{message}</div>}
      </div>
    ) : message;

    return sonnerToast(content, {
      ...rest,
      duration: autoClose === false ? Infinity : autoClose,
      closeButton: withCloseButton,
    });
  },

  /**
   * Show success toast
   */
  success: (title: string, options?: Omit<ToastOptions, 'title'>): ToastId => {
    const { message, ...rest } = options || {};
    const content = message ? (
      <div>
        <div className="font-medium">{title}</div>
        <div className="text-sm text-muted-foreground">{message}</div>
      </div>
    ) : title;

    return sonnerToast.success(content, rest);
  },

  /**
   * Show error toast
   */
  error: (title: string, options?: Omit<ToastOptions, 'title'>): ToastId => {
    const { message, ...rest } = options || {};
    const content = message ? (
      <div>
        <div className="font-medium">{title}</div>
        <div className="text-sm text-muted-foreground">{message}</div>
      </div>
    ) : title;

    return sonnerToast.error(content, rest);
  },

  /**
   * Show warning toast
   */
  warning: (title: string, options?: Omit<ToastOptions, 'title'>): ToastId => {
    const { message, ...rest } = options || {};
    const content = message ? (
      <div>
        <div className="font-medium">{title}</div>
        <div className="text-sm text-muted-foreground">{message}</div>
      </div>
    ) : title;

    return sonnerToast.warning(content, rest);
  },

  /**
   * Show info toast
   */
  info: (title: string, options?: Omit<ToastOptions, 'title'>): ToastId => {
    const { message, ...rest } = options || {};
    const content = message ? (
      <div>
        <div className="font-medium">{title}</div>
        <div className="text-sm text-muted-foreground">{message}</div>
      </div>
    ) : title;

    return sonnerToast.info(content, rest);
  },

  /**
   * Show loading toast
   */
  loading: (title: string, options?: Omit<ToastOptions, 'title'>): ToastId => {
    const { message, ...rest } = options || {};
    const content = message ? (
      <div>
        <div className="font-medium">{title}</div>
        <div className="text-sm text-muted-foreground">{message}</div>
      </div>
    ) : title;

    return sonnerToast.loading(content, rest);
  },

  /**
   * Update an existing toast by ID
   */
  update: (id: ToastId, options: ToastOptions): void => {
    const { title, message, autoClose, withCloseButton = true, ...rest } = options;

    const content = title ? (
      <div>
        <div className="font-medium">{title}</div>
        {message && <div className="text-sm text-muted-foreground">{message}</div>}
      </div>
    ) : message;

    sonnerToast(content, {
      id,
      ...rest,
      duration: autoClose === false ? Infinity : autoClose,
      closeButton: withCloseButton,
    });
  },

  /**
   * Dismiss a toast by ID
   */
  dismiss: (id?: ToastId): void => {
    if (id) {
      sonnerToast.dismiss(id);
    } else {
      sonnerToast.dismiss();
    }
  },

  /**
   * Promise toast - shows loading, then success/error based on promise result
   */
  promise: <T,>(
    promise: Promise<T>,
    messages: {
      loading: string;
      success: string | ((data: T) => string);
      error: string | ((error: any) => string);
    }
  ): Promise<T> => {
    return sonnerToast.promise(promise, {
      loading: messages.loading,
      success: messages.success,
      error: messages.error,
    });
  },

  /**
   * Custom toast with render function
   */
  custom: (
    render: (id: ToastId) => React.ReactNode,
    options?: ExternalToast
  ): ToastId => {
    return sonnerToast.custom(render, options);
  },
};

// Export the toast function as default
export default toast;
