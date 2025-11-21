# apps/m3u/forms.py
from django import forms
from .models import M3UAccount, M3UFilter
import re

class M3UAccountForm(forms.ModelForm):
    enable_vod = forms.BooleanField(
        required=False,
        initial=False,
        label="Enable VOD Content",
        help_text="Parse and import VOD (movies/series) content for XtreamCodes accounts"
    )

    mac_address = forms.CharField(
        required=False,
        label="MAC Address",
        help_text="MAC address for STB-Portal accounts, e.g. 00:1A:79:12:34:56",
    )

    class Meta:
        model = M3UAccount
        fields = [
            'name',
            'server_url',
            'uploaded_file',
            'server_group',
            'max_streams',
            'is_active',
            'enable_vod',
            'mac_address',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Set initial value for enable_vod from custom_properties
        if self.instance and self.instance.custom_properties:
            custom_props = self.instance.custom_properties or {}
            self.fields['enable_vod'].initial = custom_props.get('enable_vod', False)
        if self.instance and hasattr(self.instance, 'mac_address'):
            self.fields['mac_address'].initial = getattr(self.instance, 'mac_address', '')

    def save(self, commit=True):
        instance = super().save(commit=False)

        # Handle enable_vod field
        enable_vod = self.cleaned_data.get('enable_vod', False)

        # Parse existing custom_properties
        custom_props = instance.custom_properties or {}

        # Update VOD preference
        custom_props['enable_vod'] = enable_vod
        instance.custom_properties = custom_props

        # Store mac_address on instance if field exists
        mac_address = self.cleaned_data.get('mac_address', '')
        if hasattr(instance, 'mac_address'):
            instance.mac_address = mac_address

        if commit:
            instance.save()
        return instance

    def clean_uploaded_file(self):
        uploaded_file = self.cleaned_data.get('uploaded_file')
        if uploaded_file:
            if not uploaded_file.name.endswith('.m3u'):
                raise forms.ValidationError("The uploaded file must be an M3U file.")
        return uploaded_file

    def clean(self):
        cleaned_data = super().clean()
        url = cleaned_data.get('server_url')
        file = cleaned_data.get('uploaded_file')
        mac = cleaned_data.get('mac_address')
        account_type = cleaned_data.get('account_type') or getattr(self.instance, 'account_type', None)

        # Ensure either `server_url` or `uploaded_file` is provided (for STD/XC)
        if (account_type != M3UAccount.Types.MAC) and not url and not file:
            raise forms.ValidationError("Either an M3U URL or a file upload is required.")

        # For MAC accounts, require server_url and mac_address
        if account_type == M3UAccount.Types.MAC:
            if not url:
                raise forms.ValidationError("For MAC accounts, a portal URL (server_url) is required.")
            if not mac:
                raise forms.ValidationError("For MAC accounts, a MAC address is required.")

        return cleaned_data


class M3UFilterForm(forms.ModelForm):
    class Meta:
        model = M3UFilter
        fields = ['m3u_account', 'filter_type', 'regex_pattern', 'exclude']

    def clean_regex_pattern(self):
        pattern = self.cleaned_data['regex_pattern']
        try:
            re.compile(pattern)
        except re.error:
            raise forms.ValidationError("Invalid regex pattern")
        return pattern
