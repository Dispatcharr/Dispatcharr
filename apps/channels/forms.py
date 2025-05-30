from django import forms
from .models import Stream, Channel, ChannelGroup

#
# ChannelGroup Form
#
class ChannelGroupForm(forms.ModelForm):
    class Meta:
        model = ChannelGroup
        fields = ['name']


#
# Channel Form
#
class ChannelForm(forms.ModelForm):
    # Explicitly define channel_number as FloatField to ensure decimal values work
    channel_number = forms.FloatField(
        required=False,
        widget=forms.NumberInput(attrs={'step': '0.1'}),  # Allow decimal steps
        help_text="Channel number can include decimals (e.g., 1.1, 2.5)"
    )

    channel_group = forms.ModelChoiceField(
        queryset=ChannelGroup.objects.all(),
        required=False,
        label="Channel Group",
        empty_label="--- No group ---"
    )

    class Meta:
        model = Channel
        fields = [
            'channel_number',
            'name',
            'channel_group',
        ]


#
# Example: Stream Form (optional if you want a ModelForm for Streams)
#
class StreamForm(forms.ModelForm):
    class Meta:
        model = Stream
        fields = [
            'name',
            'url',
            'logo_url',
            'epg_data',
            'local_file',
            'channel_group',
        ]
