from rest_framework import serializers
from .models import M3UAccount, M3UFilter, ServerGroup, M3UAccountProfile
from core.models import UserAgent
from apps.channels.models import ChannelGroup, ChannelGroupM3UAccount
from apps.channels.serializers import ChannelGroupM3UAccountSerializer, ChannelGroupSerializer
import logging

logger = logging.getLogger(__name__)

class M3UFilterSerializer(serializers.ModelSerializer):
    """Serializer for M3U Filters"""
    channel_groups = ChannelGroupM3UAccountSerializer(source='m3u_account', many=True)

    class Meta:
        model = M3UFilter
        fields = ['id', 'filter_type', 'regex_pattern', 'exclude', 'channel_groups']

from rest_framework import serializers
from .models import M3UAccountProfile

class M3UAccountProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = M3UAccountProfile
        fields = ['id', 'name', 'max_streams', 'is_active', 'is_default', 'current_viewers', 'search_pattern', 'replace_pattern']
        read_only_fields = ['id']

    def create(self, validated_data):
        m3u_account = self.context.get('m3u_account')

        # Use the m3u_account when creating the profile
        validated_data['m3u_account_id'] = m3u_account.id

        return super().create(validated_data)


class M3UAccountSerializer(serializers.ModelSerializer):
    """Serializer for M3U Account"""
    filters = M3UFilterSerializer(many=True, read_only=True)
    # Include user_agent as a mandatory field using its primary key.
    user_agent = serializers.PrimaryKeyRelatedField(
        queryset=UserAgent.objects.all(),
        required=True
    )
    profiles = M3UAccountProfileSerializer(many=True, read_only=True)
    read_only_fields = ['locked']
    # channel_groups = serializers.SerializerMethodField()
    channel_groups = ChannelGroupM3UAccountSerializer(source='channel_group.all', many=True, required=False)


    class Meta:
        model = M3UAccount
        fields = [
            'id', 'name', 'server_url', 'uploaded_file', 'server_group',
            'max_streams', 'is_active', 'created_at', 'updated_at', 'filters', 'user_agent', 'profiles', 'locked',
            'channel_groups',
        ]

    # def get_channel_groups(self, obj):
    #     # Retrieve related ChannelGroupM3UAccount records for this M3UAccount
    #     relations = ChannelGroupM3UAccount.objects.filter(m3u_account=obj).select_related('channel_group')

    #     # Serialize the channel groups with their enabled status
    #     return [
    #         {
    #             'channel_group_name': relation.channel_group.name,
    #             'channel_group_id': relation.channel_group.id,
    #             'enabled': relation.enabled,
    #         }
    #         for relation in relations
    #     ]

    # def to_representation(self, instance):
    #     """Override the default to_representation method to include channel_groups"""
    #     representation = super().to_representation(instance)

    #     # Manually add the channel_groups to the representation
    #     channel_groups = ChannelGroupM3UAccount.objects.filter(m3u_account=instance).select_related('channel_group')
    #     representation['channel_groups'] = [
    #         {
    #             'id': relation.id,
    #             'channel_group_name': relation.channel_group.name,
    #             'channel_group_id': relation.channel_group.id,
    #             'enabled': relation.enabled,
    #         }
    #         for relation in channel_groups
    #     ]

    #     return representation

    # def update(self, instance, validated_data):
    #     logger.info(validated_data)
    #     channel_groups_data = validated_data.pop('channel_groups', None)
    #     instance = super().update(instance, validated_data)

    #     if channel_groups_data is not None:
    #         logger.info(json.dumps(channel_groups_data))
    #         # Remove existing relationships not included in the request
    #         existing_groups = {cg.channel_group_id: cg for cg in instance.channel_group.all()}

    #         # for group_id in set(existing_groups.keys()) - sent_group_ids:
    #         #     existing_groups[group_id].delete()

    #         # Create or update relationships
    #         for cg_data in channel_groups_data:
    #             logger.info(json.dumps(cg_data))
    #             ChannelGroupM3UAccount.objects.update_or_create(
    #                 channel_group=existing_groups[cg_data['channel_group_id']],
    #                 m3u_account=instance,
    #                 defaults={'enabled': cg_data.get('enabled', True)}
    #             )

    #     return instance

class ServerGroupSerializer(serializers.ModelSerializer):
    """Serializer for Server Group"""

    class Meta:
        model = ServerGroup
        fields = ['id', 'name']
