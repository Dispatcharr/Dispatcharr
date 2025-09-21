from django.contrib import admin
from django.utils.html import format_html
from .models import M3UAccount, M3UFilter, ServerGroup, UserAgent, M3UAccountProfile
import json


class M3UFilterInline(admin.TabularInline):
    model = M3UFilter
    extra = 1
    verbose_name = "M3U Filter"
    verbose_name_plural = "M3U Filters"


@admin.register(M3UAccount)
class M3UAccountAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "server_url",
        "server_group",
        "max_streams",
        "priority",
        "is_active",
        "user_agent_display",
        "uploaded_file_link",
        "created_at",
        "updated_at",
    )
    list_filter = ("is_active", "server_group")
    search_fields = ("name", "server_url", "server_group__name")
    inlines = [M3UFilterInline]
    actions = ["activate_accounts", "deactivate_accounts"]

    # Handle both ForeignKey and ManyToManyField cases for UserAgent
    def user_agent_display(self, obj):
        if hasattr(obj, "user_agent"):  # ForeignKey case
            return obj.user_agent.user_agent if obj.user_agent else "None"
        elif hasattr(obj, "user_agents"):  # ManyToManyField case
            return ", ".join([ua.user_agent for ua in obj.user_agents.all()]) or "None"
        return "None"

    user_agent_display.short_description = "User Agent(s)"

    def vod_enabled_display(self, obj):
        """Display whether VOD is enabled for this account"""
        if obj.custom_properties:
            custom_props = obj.custom_properties or {}
            return "Yes" if custom_props.get('enable_vod', False) else "No"
        return "No"
    vod_enabled_display.short_description = "VOD Enabled"
    vod_enabled_display.boolean = True

    def uploaded_file_link(self, obj):
        if obj.uploaded_file:
            return format_html(
                "<a href='{}' target='_blank'>Download M3U</a>", obj.uploaded_file.url
            )
        return "No file uploaded"

    uploaded_file_link.short_description = "Uploaded File"

    @admin.action(description="Activate selected accounts")
    def activate_accounts(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description="Deactivate selected accounts")
    def deactivate_accounts(self, request, queryset):
        queryset.update(is_active=False)

    # Add ManyToManyField for Django Admin (if applicable)
    if hasattr(M3UAccount, "user_agents"):
        filter_horizontal = ("user_agents",)  # Only for ManyToManyField


@admin.register(M3UFilter)
class M3UFilterAdmin(admin.ModelAdmin):
    list_display = ("m3u_account", "filter_type", "regex_pattern", "exclude")
    list_filter = ("filter_type", "exclude")
    search_fields = ("regex_pattern",)
    ordering = ("m3u_account",)


@admin.register(ServerGroup)
class ServerGroupAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(M3UAccountProfile)
class M3UAccountProfileAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "m3u_account",
        "is_default",
        "is_active",
        "max_streams",
        "current_viewers",
        "account_status_display",
        "account_expiration_display",
        "last_refresh_display",
    )
    list_filter = ("is_active", "is_default", "m3u_account__account_type")
    search_fields = ("name", "m3u_account__name")
    readonly_fields = ("account_info_display",)
    
    def account_status_display(self, obj):
        """Display account status from custom properties"""
        status = obj.get_account_status()
        if status:
            # Create colored status display
            color_map = {
                'Active': 'green',
                'Expired': 'red',
                'Disabled': 'red',
                'Banned': 'red',
            }
            color = color_map.get(status, 'black')
            return format_html(
                '<span style="color: {};">{}</span>',
                color,
                status
            )
        return "Unknown"
    account_status_display.short_description = "Account Status"
    
    def account_expiration_display(self, obj):
        """Display account expiration from custom properties"""
        expiration = obj.get_account_expiration()
        if expiration:
            from datetime import datetime
            if expiration < datetime.now():
                return format_html(
                    '<span style="color: red;">{}</span>',
                    expiration.strftime('%Y-%m-%d %H:%M')
                )
            else:
                return format_html(
                    '<span style="color: green;">{}</span>',
                    expiration.strftime('%Y-%m-%d %H:%M')
                )
        return "Unknown"
    account_expiration_display.short_description = "Expires"
    
    def last_refresh_display(self, obj):
        """Display last refresh time from custom properties"""
        last_refresh = obj.get_last_refresh()
        if last_refresh:
            return last_refresh.strftime('%Y-%m-%d %H:%M:%S')
        return "Never"
    last_refresh_display.short_description = "Last Refresh"
    
    def account_info_display(self, obj):
        """Display formatted account information from custom properties"""
        if not obj.custom_properties:
            return "No account information available"
        
        html_parts = []
        
        # User Info
        user_info = obj.custom_properties.get('user_info', {})
        if user_info:
            html_parts.append("<h3>User Information:</h3>")
            html_parts.append("<ul>")
            for key, value in user_info.items():
                if key == 'exp_date' and value:
                    try:
                        from datetime import datetime
                        exp_date = datetime.fromtimestamp(float(value))
                        value = exp_date.strftime('%Y-%m-%d %H:%M:%S')
                    except (ValueError, TypeError):
                        pass
                html_parts.append(f"<li><strong>{key}:</strong> {value}</li>")
            html_parts.append("</ul>")
        
        # Server Info
        server_info = obj.custom_properties.get('server_info', {})
        if server_info:
            html_parts.append("<h3>Server Information:</h3>")
            html_parts.append("<ul>")
            for key, value in server_info.items():
                html_parts.append(f"<li><strong>{key}:</strong> {value}</li>")
            html_parts.append("</ul>")
        
        # Last Refresh
        last_refresh = obj.custom_properties.get('last_refresh')
        if last_refresh:
            html_parts.append(f"<p><strong>Last Refresh:</strong> {last_refresh}</p>")
        
        return format_html(''.join(html_parts)) if html_parts else "No account information available"
    
    account_info_display.short_description = "Account Information"
