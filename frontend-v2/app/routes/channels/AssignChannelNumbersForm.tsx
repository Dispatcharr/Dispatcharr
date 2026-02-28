import { useState, useEffect } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "~/components/ui/dialog";
import { Button } from "~/components/ui/button";
import { Input } from "~/components/ui/input";
import { Label } from "~/components/ui/label";
import { ListOrdered } from "lucide-react";
import API from "~/lib/api";
import toast from "~/lib/toast";

interface AssignChannelNumbersFormProps {
  channelIds: number[];
  isOpen: boolean;
  onClose: () => void;
}

export default function AssignChannelNumbersForm({
  channelIds,
  isOpen,
  onClose,
}: AssignChannelNumbersFormProps) {
  const [startingNumber, setStartingNumber] = useState<number>(1);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Reset form when dialog opens
  useEffect(() => {
    if (isOpen) {
      setStartingNumber(1);
    }
  }, [isOpen]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!channelIds || channelIds.length === 0) {
      toast.error("No channels selected");
      return;
    }

    setIsSubmitting(true);

    try {
      const result = await API.assignChannelNumbers(channelIds, startingNumber);

      toast.success(result?.message || "Channels assigned successfully");

      await API.requeryChannels();

      onClose();
    } catch (err) {
      console.error("Failed to assign channel numbers:", err);
      toast.error("Failed to assign channel numbers");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ListOrdered className="h-5 w-5" />
            Assign Channel Numbers
          </DialogTitle>
          <DialogDescription>
            Assign sequential channel numbers starting from the specified number.
            {channelIds.length > 0 && (
              <span className="block mt-1 text-sm">
                {channelIds.length} channel{channelIds.length !== 1 ? "s" : ""} selected
              </span>
            )}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit}>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="starting-number">Starting Number</Label>
              <Input
                id="starting-number"
                type="number"
                min={1}
                value={startingNumber}
                onChange={(e) => setStartingNumber(Number(e.target.value))}
                placeholder="Enter starting number"
                required
                disabled={isSubmitting}
              />
            </div>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={onClose}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Assigning..." : "Assign"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
