"""
HLS Output Views

API endpoints for HLS streaming output.
"""

import os
import logging
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from django.http import HttpResponse, FileResponse, Http404
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from django.utils import timezone

from .models import HLSStream, HLSOutputProfile
from .serializers import (
    HLSStreamSerializer,
    HLSStreamListSerializer,
    HLSOutputProfileSerializer
)
from .stream_manager import HLSStreamManager
from .playlist_generator import PlaylistGenerator
from .redis_keys import HLSRedisKeys
from core.utils import RedisClient

logger = logging.getLogger(__name__)


# ============================================================================
# Stream Management Views
# ============================================================================

class HLSStreamListView(generics.ListAPIView):
    """List all active HLS streams"""
    queryset = HLSStream.objects.filter(status__in=['starting', 'running'])
    serializer_class = HLSStreamListSerializer
    permission_classes = [IsAuthenticated]


class HLSStreamDetailView(generics.RetrieveAPIView):
    """Get details of specific HLS stream"""
    queryset = HLSStream.objects.all()
    serializer_class = HLSStreamSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'stream_id'


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def start_stream(request):
    """Start HLS encoding for a channel"""
    try:
        channel_id = request.data.get('channel_id')
        
        if not channel_id:
            return Response(
                {'error': 'channel_id required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get or create stream manager
        manager = HLSStreamManager.get_or_create(channel_id)
        
        # Get input URL from channel
        from apps.channels.models import Channel
        channel = Channel.objects.get(id=channel_id)
        
        # Get stream URL (you may need to adjust this based on your Channel model)
        # For now, assuming there's a method or property to get the stream URL
        input_url = request.data.get('input_url')
        if not input_url:
            # Try to get from channel's first stream
            first_stream = channel.streams.first()
            if first_stream:
                input_url = first_stream.url
            else:
                return Response(
                    {'error': 'No input URL available for this channel'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Start encoding
        manager.start(input_url)
        
        return Response({
            'stream_id': str(manager.stream.stream_id),
            'status': 'starting',
            'message': 'HLS encoding started'
        })
        
    except Exception as e:
        logger.error(f"Failed to start stream: {e}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def stop_stream(request, stream_id):
    """Stop HLS encoding"""
    try:
        stream = HLSStream.objects.get(stream_id=stream_id)
        
        stream_id_str = str(stream.stream_id)
        if stream_id_str in HLSStreamManager._instances:
            manager = HLSStreamManager._instances[stream_id_str]
            manager.stop()
        else:
            # Just update status
            stream.status = 'stopped'
            stream.save()
        
        return Response({
            'stream_id': str(stream_id),
            'status': 'stopped',
            'message': 'HLS encoding stopped'
        })
        
    except HLSStream.DoesNotExist:
        return Response(
            {'error': 'Stream not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f"Failed to stop stream: {e}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def restart_stream(request, stream_id):
    """Restart HLS encoding"""
    try:
        stream = HLSStream.objects.get(stream_id=stream_id)
        
        stream_id_str = str(stream.stream_id)
        if stream_id_str in HLSStreamManager._instances:
            manager = HLSStreamManager._instances[stream_id_str]
            manager.restart()

        return Response({
            'stream_id': str(stream_id),
            'status': 'restarting',
            'message': 'HLS encoding restarted'
        })

    except HLSStream.DoesNotExist:
        return Response(
            {'error': 'Stream not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f"Failed to restart stream: {e}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# ============================================================================
# Playlist Serving Views
# ============================================================================

@never_cache
@require_http_methods(['GET'])
def master_playlist(request, stream_id):
    """Serve master playlist (multivariant)"""
    try:
        # Check Redis cache first
        redis_client = RedisClient.get_instance()
        cache_key = HLSRedisKeys.get_master_playlist_key(stream_id)

        cached_playlist = redis_client.get(cache_key)
        if cached_playlist:
            if isinstance(cached_playlist, bytes):
                cached_playlist = cached_playlist.decode('utf-8')

            return HttpResponse(
                cached_playlist,
                content_type='application/vnd.apple.mpegurl',
                headers={
                    'Cache-Control': 'public, max-age=2',
                    'Access-Control-Allow-Origin': '*',
                }
            )

        # Generate fresh playlist
        stream = HLSStream.objects.get(stream_id=stream_id, status__in=['running', 'starting'])
        generator = PlaylistGenerator(stream, stream.profile)

        playlist_content = generator.generate_master_playlist()

        # Cache in Redis
        redis_client.setex(cache_key, stream.profile.playlist_cache_ttl, playlist_content)

        return HttpResponse(
            playlist_content,
            content_type='application/vnd.apple.mpegurl',
            headers={
                'Cache-Control': f'public, max-age={stream.profile.playlist_cache_ttl}',
                'Access-Control-Allow-Origin': '*',
            }
        )

    except HLSStream.DoesNotExist:
        raise Http404("Stream not found")
    except Exception as e:
        logger.error(f"Error serving master playlist: {e}")
        raise Http404("Error generating playlist")


@never_cache
@require_http_methods(['GET'])
def media_playlist(request, stream_id, quality):
    """Serve media playlist for specific quality"""
    try:
        # Track viewer session
        session_id = request.session.session_key or request.META.get('REMOTE_ADDR', 'unknown')
        redis_client = RedisClient.get_instance()

        viewer_key = HLSRedisKeys.get_viewer_session_key(session_id, stream_id)
        redis_client.setex(viewer_key, 60, "1")  # 60s TTL

        # Check Redis cache
        cache_key = HLSRedisKeys.get_media_playlist_key(stream_id, quality)
        cached_playlist = redis_client.get(cache_key)

        if cached_playlist:
            if isinstance(cached_playlist, bytes):
                cached_playlist = cached_playlist.decode('utf-8')

            return HttpResponse(
                cached_playlist,
                content_type='application/vnd.apple.mpegurl',
                headers={
                    'Cache-Control': 'public, max-age=2',
                    'Access-Control-Allow-Origin': '*',
                }
            )

        # Generate fresh playlist
        stream = HLSStream.objects.get(stream_id=stream_id, status__in=['running', 'starting'])
        generator = PlaylistGenerator(stream, stream.profile)

        # Support time-shifting via query params
        start_seq = request.GET.get('_HLS_msn')  # Media Sequence Number
        end_seq = request.GET.get('_HLS_part')   # Part number (LL-HLS)

        playlist_content = generator.generate_media_playlist(
            quality,
            start_seq=int(start_seq) if start_seq else None,
            end_seq=int(end_seq) if end_seq else None
        )

        # Cache in Redis
        redis_client.setex(cache_key, stream.profile.playlist_cache_ttl, playlist_content)

        return HttpResponse(
            playlist_content,
            content_type='application/vnd.apple.mpegurl',
            headers={
                'Cache-Control': f'public, max-age={stream.profile.playlist_cache_ttl}',
                'Access-Control-Allow-Origin': '*',
            }
        )

    except HLSStream.DoesNotExist:
        raise Http404("Stream not found")
    except Exception as e:
        logger.error(f"Error serving media playlist: {e}")
        raise Http404("Error generating playlist")


@require_http_methods(['GET'])
def serve_segment(request, stream_id, quality, segment):
    """
    Fallback segment serving (Nginx should handle this)
    Only used if Nginx is not configured
    """
    try:
        stream = HLSStream.objects.get(stream_id=stream_id)

        segment_path = os.path.join(
            stream.profile.storage_path,
            str(stream_id),
            quality,
            segment
        )

        if not os.path.exists(segment_path):
            raise Http404("Segment not found")

        # Serve file
        response = FileResponse(
            open(segment_path, 'rb'),
            content_type='video/mp4' if segment.endswith('.m4s') else 'video/mp2t'
        )

        response['Cache-Control'] = 'public, max-age=86400, immutable'
        response['Access-Control-Allow-Origin'] = '*'

        return response

    except HLSStream.DoesNotExist:
        raise Http404("Stream not found")
    except Exception as e:
        logger.error(f"Error serving segment: {e}")
        raise Http404("Segment not found")


# ============================================================================
# Profile Management Views
# ============================================================================

class HLSProfileListView(generics.ListCreateAPIView):
    """List and create HLS output profiles"""
    queryset = HLSOutputProfile.objects.all()
    serializer_class = HLSOutputProfileSerializer
    permission_classes = [IsAuthenticated]


class HLSProfileDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Get, update, or delete HLS output profile"""
    queryset = HLSOutputProfile.objects.all()
    serializer_class = HLSOutputProfileSerializer
    permission_classes = [IsAuthenticated]


# ============================================================================
# Metrics and Stats Views
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def stream_stats(request, stream_id):
    """Get detailed statistics for a stream"""
    try:
        stream = HLSStream.objects.get(stream_id=stream_id)

        # Calculate uptime
        uptime_seconds = 0
        if stream.start_time:
            uptime_seconds = (timezone.now() - stream.start_time).total_seconds()

        # Calculate average bitrate
        average_bitrate = 0
        if uptime_seconds > 0:
            average_bitrate = (stream.total_bytes_generated * 8) / uptime_seconds

        # Get viewer count from Redis
        redis_client = RedisClient.get_instance()
        viewer_count_key = HLSRedisKeys.get_viewer_count_key(str(stream_id))
        viewer_count = redis_client.scard(viewer_count_key) if redis_client.exists(viewer_count_key) else 0

        # Get DVR window info
        from .playlist_generator import PlaylistGenerator
        generator = PlaylistGenerator(stream, stream.profile)

        dvr_info = {}
        if stream.profile.enable_abr and stream.profile.qualities:
            for quality in stream.profile.qualities:
                quality_name = quality['name']
                dvr_info[quality_name] = {
                    'segment_count': generator.get_segment_count(quality_name),
                    'duration_seconds': generator.get_dvr_window_duration(quality_name)
                }

        return Response({
            'stream_id': str(stream_id),
            'status': stream.status,
            'uptime_seconds': uptime_seconds,
            'total_segments': stream.total_segments_generated,
            'current_sequence': stream.current_sequence,
            'total_bytes': stream.total_bytes_generated,
            'average_bitrate_bps': average_bitrate,
            'viewer_count': viewer_count,
            'restart_count': stream.restart_count,
            'dvr_window': dvr_info,
            'last_segment_time': stream.last_segment_time,
            'error_message': stream.error_message
        })

    except HLSStream.DoesNotExist:
        return Response(
            {'error': 'Stream not found'},
            status=status.HTTP_404_NOT_FOUND
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def global_stats(request):
    """Get global HLS output statistics"""

    active_streams = HLSStream.objects.filter(status__in=['starting', 'running'])

    total_bytes = sum(s.total_bytes_generated for s in active_streams)
    total_segments = sum(s.total_segments_generated for s in active_streams)

    # Get total viewer count
    redis_client = RedisClient.get_instance()
    total_viewers = 0
    for stream in active_streams:
        viewer_key = HLSRedisKeys.get_viewer_count_key(str(stream.stream_id))
        if redis_client.exists(viewer_key):
            total_viewers += redis_client.scard(viewer_key)

    return Response({
        'active_streams': active_streams.count(),
        'total_bytes_generated': total_bytes,
        'total_segments_generated': total_segments,
        'total_viewers': total_viewers,
        'streams': [
            {
                'stream_id': str(s.stream_id),
                'channel_name': s.channel.name,
                'status': s.status,
                'uptime_seconds': (timezone.now() - s.start_time).total_seconds() if s.start_time else 0
            }
            for s in active_streams
        ]
    })

