import { Modal, Group, Button, Checkbox, Box } from '@mantine/core';
import React, { useEffect, useState } from 'react';
import useWarningsStore from '../store/warnings';

/**
 * A reusable confirmation dialog with option to suppress future warnings
 *
 * @param {Object} props - Component props
 * @param {boolean} props.opened - Whether the dialog is visible
 * @param {Function} props.onClose - Function to call when closing without confirming
 * @param {Function} props.onConfirm - Function to call when confirming the action
 * @param {string} props.title - Dialog title
 * @param {string} props.message - Dialog message
 * @param {string} props.confirmLabel - Text for the confirm button
 * @param {string} props.cancelLabel - Text for the cancel button
 * @param {string} props.actionKey - Unique key for this type of action (used for suppression)
 * @param {Function} props.onSuppressChange - Called when "don't show again" option changes
 * @param {string} [props.size='md'] - Size of the modal
 * @param {boolean} [props.loading=false] - Whether the confirm button should show loading state
 * @param {boolean} [props.showDeleteFileOption=false] - Show "also delete files" checkbox
 * @param {string} [props.deleteFileLabel] - Label for delete-files checkbox
 * @param {boolean} [props.showStopStreamOption=false] - Show "also stop stream" checkbox
 * @param {string} [props.stopStreamLabel] - Label for stop-stream checkbox
 */
const ConfirmationDialog = ({
  opened,
  onClose,
  onConfirm,
  title = 'Confirm Action',
  message = 'Are you sure you want to proceed?',
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  actionKey,
  onSuppressChange,
  size = 'md',
  zIndex = 1000,
  showDeleteFileOption = false,
  deleteFileLabel = 'Also delete files from disk',
  showStopStreamOption = false,
  stopStreamLabel = 'Also stop active stream if playing',
  loading = false,
}) => {
  const suppressWarning = useWarningsStore((s) => s.suppressWarning);
  const isWarningSuppressed = useWarningsStore((s) => s.isWarningSuppressed);
  const setActionPreference = useWarningsStore((s) => s.setActionPreference);
  const getActionPreference = useWarningsStore((s) => s.getActionPreference);
  const [suppressChecked, setSuppressChecked] = useState(
    isWarningSuppressed(actionKey)
  );
  const [deleteFiles, setDeleteFiles] = useState(false);
  const [stopStream, setStopStream] = useState(false);

  useEffect(() => {
    if (!opened) {
      return;
    }
    setSuppressChecked(isWarningSuppressed(actionKey));
    setDeleteFiles(false);
    if (showStopStreamOption && actionKey) {
      setStopStream(getActionPreference(actionKey, 'stopStream', false));
    } else {
      setStopStream(false);
    }
  }, [
    opened,
    actionKey,
    showStopStreamOption,
    isWarningSuppressed,
    getActionPreference,
  ]);

  const handleToggleSuppress = (e) => {
    setSuppressChecked(e.currentTarget.checked);
    if (onSuppressChange) {
      onSuppressChange(e.currentTarget.checked);
    }
  };

  const handleConfirm = () => {
    if (showStopStreamOption && actionKey) {
      setActionPreference(actionKey, { stopStream });
    }
    if (suppressChecked) {
      suppressWarning(actionKey);
    }
    if (showStopStreamOption) {
      onConfirm(stopStream);
    } else if (showDeleteFileOption) {
      onConfirm(deleteFiles);
    } else {
      onConfirm();
    }
    setDeleteFiles(false);
  };

  const handleClose = () => {
    setDeleteFiles(false);
    setStopStream(false);
    onClose();
  };

  return (
    <Modal
      opened={opened}
      onClose={handleClose}
      title={title}
      size={size}
      centered
      zIndex={zIndex}
    >
      <Box mb={20}>{message}</Box>

      {showDeleteFileOption && (
        <Checkbox
          checked={deleteFiles}
          onChange={(event) => setDeleteFiles(event.currentTarget.checked)}
          label={deleteFileLabel}
          mb="md"
        />
      )}

      {showStopStreamOption && (
        <Checkbox
          checked={stopStream}
          onChange={(event) => setStopStream(event.currentTarget.checked)}
          label={stopStreamLabel}
          mb="md"
        />
      )}

      {actionKey && (
        <Checkbox
          label="Don't ask me again"
          checked={suppressChecked}
          onChange={handleToggleSuppress}
          mb={20}
        />
      )}

      <Group justify="flex-end">
        <Button variant="outline" onClick={handleClose} disabled={loading}>
          {cancelLabel}
        </Button>
        <Button
          color="red"
          onClick={handleConfirm}
          loading={loading}
          disabled={loading}
          loaderProps={{ type: 'dots' }}
        >
          {confirmLabel}
        </Button>
      </Group>
    </Modal>
  );
};

export default ConfirmationDialog;
