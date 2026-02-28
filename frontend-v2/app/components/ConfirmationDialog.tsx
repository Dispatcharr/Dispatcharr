import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "~/components/ui/dialog";
import { Button } from "~/components/ui/button";
import { Checkbox } from "~/components/ui/checkbox";
import { Label } from "~/components/ui/label";
import useWarningsStore from "~/store/warnings";

interface ConfirmationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (deleteFiles?: boolean) => void;
  title?: string;
  message?: string | React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  actionKey?: string;
  onSuppressChange?: (suppressed: boolean) => void;
  showDeleteFileOption?: boolean;
  deleteFileLabel?: string;
  loading?: boolean;
  variant?:
    | "default"
    | "destructive"
    | "outline"
    | "secondary"
    | "ghost"
    | "link";
}

export default function ConfirmationDialog({
  open,
  onOpenChange,
  onConfirm,
  title = "Confirm Action",
  message = "Are you sure you want to proceed?",
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  actionKey,
  onSuppressChange,
  showDeleteFileOption = false,
  deleteFileLabel = "Also delete files from disk",
  loading = false,
  variant = "destructive",
}: ConfirmationDialogProps) {
  const suppressWarning = useWarningsStore((s) => s.suppressWarning);
  const isWarningSuppressed = useWarningsStore((s) => s.isWarningSuppressed);
  const [suppressChecked, setSuppressChecked] = useState(
    actionKey ? isWarningSuppressed(actionKey) : false,
  );
  const [deleteFiles, setDeleteFiles] = useState(false);

  const handleToggleSuppress = (checked: boolean) => {
    setSuppressChecked(checked);
    if (onSuppressChange) {
      onSuppressChange(checked);
    }
  };

  const handleConfirm = () => {
    if (suppressChecked && actionKey) {
      suppressWarning(actionKey);
    }
    if (showDeleteFileOption) {
      onConfirm(deleteFiles);
    } else {
      onConfirm();
    }
    setDeleteFiles(false); // Reset for next time
  };

  const handleClose = () => {
    setDeleteFiles(false); // Reset for next time
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription asChild>
            <div className="pt-2">{message}</div>
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {actionKey && (
            <div className="flex items-center space-x-2">
              <Checkbox
                id="suppress-warning"
                checked={suppressChecked}
                onCheckedChange={handleToggleSuppress}
              />
              <Label
                htmlFor="suppress-warning"
                className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
              >
                Don't ask me again
              </Label>
            </div>
          )}

          {showDeleteFileOption && (
            <div className="flex items-center space-x-2">
              <Checkbox
                id="delete-files"
                checked={deleteFiles}
                onCheckedChange={(checked) =>
                  setDeleteFiles(checked as boolean)
                }
              />
              <Label
                htmlFor="delete-files"
                className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
              >
                {deleteFileLabel}
              </Label>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleClose} disabled={loading}>
            {cancelLabel}
          </Button>
          <Button variant={variant} onClick={handleConfirm} disabled={loading}>
            {loading ? "Loading..." : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
