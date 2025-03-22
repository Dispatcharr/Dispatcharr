from django.contrib import admin
from .models import Stream, Channel, ChannelGroup

@admin.register(Stream)
class StreamAdmin(admin.ModelAdmin):
    list_display = (
        'id',  # Primary Key
        'name',
        'channel_group',
        'url',
        'current_viewers',
        'updated_at',
    )

    list_filter = ('channel_group',)  # Filter by 'channel_group' (foreign key)

    search_fields = ('id', 'name', 'url', 'channel_group__name')  # Search by 'ChannelGroup' name

    ordering = ('-updated_at',)

@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = (
        'id',  # Primary Key
        'channel_number',
        'uuid',
        'name',
        'channel_group',
        'tvg_name'
    )
    list_filter = ('channel_group',)
    search_fields = ('id', 'name', 'channel_group__name', 'tvg_name')  # Added 'id'
    ordering = ('channel_number',)

@admin.register(ChannelGroup)
class ChannelGroupAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')  # Added 'id'
    search_fields = ('id', 'name')  # Added 'id'
