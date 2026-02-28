import { useState, useEffect, useMemo } from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '~/components/ui/dialog';
import { Button } from '~/components/ui/button';
import { Label } from '~/components/ui/label';
import API from '~/lib/api';
import toast from '~/lib/toast';
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldLabel,
} from '~/components/ui/field';
import { RadioGroup, RadioGroupItem } from '~/components/ui/radio-group';
import Input from '~/components/dispatcharr/Input';
import { Badge } from '~/components/ui/badge';
import { X } from 'lucide-react';
import useSettingsStore from '~/store/settings';
import { getChangedSettings, saveChangedSettings } from '~/lib/settings-utils';

interface AssignChannelNumbersFormProps {
  channelIds: number[];
  isOpen: boolean;
  onClose: () => void;
}

// Extract EPG settings directly without parsing all settings
const getEpgSettingsFromStore = (settings) => {
  const epgSettings = settings?.['epg_settings']?.value;
  return {
    epg_match_mode: epgSettings?.epg_match_mode || 'default',
    epg_match_ignore_prefixes: Array.isArray(
      epgSettings?.epg_match_ignore_prefixes
    )
      ? epgSettings.epg_match_ignore_prefixes
      : [],
    epg_match_ignore_suffixes: Array.isArray(
      epgSettings?.epg_match_ignore_suffixes
    )
      ? epgSettings.epg_match_ignore_suffixes
      : [],
    epg_match_ignore_custom: Array.isArray(epgSettings?.epg_match_ignore_custom)
      ? epgSettings.epg_match_ignore_custom
      : [],
  };
};

export default function AssignChannelNumbersForm({
  channelIds,
  isOpen,
  onClose,
}: AssignChannelNumbersFormProps) {
  const settings = useSettingsStore((s) => s.settings);

  const [settingsMode, setSettingsMode] = useState('default');
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Compute form values directly from settings - memoized for performance
  const storedValues = useMemo(
    () => getEpgSettingsFromStore(settings),
    [settings]
  );

  const [ignorePrefixes, setIgnorePrefixes] = useState<string>('');
  const [ignoreSuffixes, setIgnoreSuffixes] = useState<string>('');
  const [ignoreCustom, setIgnoreCustom] = useState<string>('');

  // Reset form when dialog opens
  useEffect(() => {
    if (isOpen) {
      // Reset fields
      setSettingsMode('default');
      setIgnorePrefixes('');
      setIgnoreSuffixes('');
      setIgnoreCustom('');
    }
  }, [isOpen]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);

    try {
      // Save mode and settings (backend will ignore custom settings if mode is 'default')
      const settingsToSave = {
        ...storedValues,
        epg_match_mode: settingsMode,
      };
      const changedSettings = getChangedSettings(settingsToSave, settings);
      if (Object.keys(changedSettings).length > 0) {
        await saveChangedSettings(settings, changedSettings);
      }

      // Then trigger auto-match
      if (channelIds.length > 0) {
        await API.matchEpg(channelIds);
        toast.show({
          title: `EPG matching started for ${channelIds.length} selected channel(s)`,
          color: 'green',
        });
      } else {
        await API.matchEpg();
        toast.show({
          title: 'EPG matching started for all channels without EPG',
          color: 'green',
        });
      }

      onClose();
    } catch (error) {
      console.error('Error during auto-match:', error);
      toast.show({
        title: 'Error',
        message: error.message || 'Failed to start EPG matching',
        color: 'red',
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            EPG Match Settings
          </DialogTitle>
          <DialogDescription>
            Match channels to EPG data for {channelIds.length} selected channel
            {channelIds.length !== 1 ? 's' : ''}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit}>
          <div className="space-y-4 py-2">
            <Label>Matching Mode</Label>
            <RadioGroup
              defaultValue="default"
              value={settingsMode}
              onValueChange={setSettingsMode}
              className="w-fit"
            >
              <Field orientation="horizontal">
                <RadioGroupItem value="default" id="desc-r1" />
                <FieldContent>
                  <FieldLabel htmlFor="desc-r1">
                    Use default settings
                  </FieldLabel>
                  <FieldDescription>
                    Recommended for most users. Handles standard channel name
                    variations automatically.
                  </FieldDescription>
                </FieldContent>
              </Field>

              <Field orientation="horizontal">
                <RadioGroupItem value="advanced" id="desc-r2" />
                <FieldContent>
                  <FieldLabel htmlFor="desc-r2">
                    Configure advanced options
                  </FieldLabel>
                  <FieldDescription>
                    Use if channels aren't matching correctly. Add custom
                    prefixes, suffixes, or strings to ignore.
                  </FieldDescription>
                </FieldContent>
              </Field>
            </RadioGroup>
          </div>

          {settingsMode === 'advanced' && (
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Input
                  label="Ignore Prefxies"
                  description="Removed from START of channel names (e.g., Prime:, Sling:, US:)"
                  placeholder="Type and press enter"
                  value={ignorePrefixes}
                  onChange={(e) => setIgnorePrefixes(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      storedValues.epg_match_ignore_prefixes.push(
                        ignorePrefixes.trim()
                      );
                      setIgnorePrefixes('');
                    }
                  }}
                />
                {storedValues.epg_match_ignore_prefixes.map((prefix, index) => (
                  <Badge key={index}>
                    {prefix}
                    <Button
                      className="size-4 cursor-pointer"
                      onClick={(e) => {
                        e.stopPropagation();
                        storedValues.epg_match_ignore_prefixes =
                          storedValues.epg_match_ignore_prefixes.filter(
                            (_, i) => i !== index
                          );
                      }}
                    >
                      <X />
                    </Button>
                  </Badge>
                ))}
              </div>

              <div className="space-y-2">
                <Input
                  label="Ignore Suffixes"
                  description="Removed from END of channel names (e.g., HD, 4K, +1)"
                  placeholder="Type and press enter"
                  value={ignoreSuffixes}
                  onChange={(e) => setIgnoreSuffixes(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      storedValues.epg_match_ignore_suffixes.push(
                        ignoreSuffixes.trim()
                      );
                      setIgnoreSuffixes('');
                    }
                  }}
                />
                {storedValues.epg_match_ignore_suffixes.map((suffix, index) => (
                  <Badge key={index}>
                    {suffix}
                    <Button
                      className="size-4 cursor-pointer"
                      onClick={(e) => {
                        e.stopPropagation();
                        storedValues.epg_match_ignore_suffixes =
                          storedValues.epg_match_ignore_suffixes.filter(
                            (_, i) => i !== index
                          );
                      }}
                    >
                      <X />
                    </Button>
                  </Badge>
                ))}
              </div>

              <div className="space-y-2">
                <Input
                  label="Ignore Custom Strings"
                  description="Removed from ANYWHERE in channel names (e.g., 24/7, LIVE)"
                  placeholder="Type and press enter"
                  value={ignoreCustom}
                  onChange={(e) => setIgnoreCustom(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      storedValues.epg_match_ignore_custom.push(
                        ignoreCustom.trim()
                      );
                      setIgnoreCustom('');
                    }
                  }}
                />
                {storedValues.epg_match_ignore_custom.map((custom, index) => (
                  <Badge key={index}>
                    {custom}
                    <Button
                      className="size-4 cursor-pointer"
                      onClick={(e) => {
                        e.stopPropagation();
                        storedValues.epg_match_ignore_custom =
                          storedValues.epg_match_ignore_custom.filter(
                            (_, i) => i !== index
                          );
                      }}
                    >
                      <X />
                    </Button>
                  </Badge>
                ))}
              </div>

              <div className="text-xs text-zinc-500">
                Channel display names are never modified. These settings only
                affect the matching algorithm.
              </div>
            </div>
          )}

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
              Start Auto Match
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
