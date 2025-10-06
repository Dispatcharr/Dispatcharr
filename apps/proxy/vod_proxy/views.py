"""
VOD (Video on Demand) proxy views for handling movie and series streaming.
Supports M3U profiles for authentication and URL transformation.
"""

import time
import random
import logging
import requests
from django.http import StreamingHttpResponse, JsonResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.views import View
from apps.vod.models import Movie, Series, Episode
from apps.m3u.models import M3UAccount, M3UAccountProfile
from apps.proxy.vod_proxy.connection_manager import VODConnectionManager
from apps.proxy.vod_proxy.multi_worker_connection_manager import MultiWorkerVODConnectionManager, infer_content_type_from_url
from .utils import get_client_info, create_vod_response

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name='dispatch')
class VODStreamView(View):
    """Handle VOD streaming requests with M3U profile support"""

    def get(self, request, content_type, content_id, session_id=None, profile_id=None):
        """
        Stream VOD content (movies or series episodes) with session-based connection reuse

        Args:
            content_type: 'movie', 'series', or 'episode'
            content_id: ID of the content
            session_id: Optional session ID from URL path (for persistent connections)
            profile_id: Optional M3U profile ID for authentication
        """
        logger.info(f"[VOD-REQUEST] Starting VOD stream request: {content_type}/{content_id}, session: {session_id}, profile: {profile_id}")
        logger.info(f"[VOD-REQUEST] Full request path: {request.get_full_path()}")
        logger.info(f"[VOD-REQUEST] Request method: {request.method}")
        logger.info(f"[VOD-REQUEST] Request headers: {dict(request.headers)}")

        try:
            client_ip, client_user_agent = get_client_info(request)

            # Extract timeshift parameters from query string
            # Support multiple timeshift parameter formats
            utc_start = request.GET.get('utc_start') or request.GET.get('start') or request.GET.get('playliststart')
            utc_end = request.GET.get('utc_end') or request.GET.get('end') or request.GET.get('playlistend')
            offset = request.GET.get('offset') or request.GET.get('seek') or request.GET.get('t')

            # VLC specific timeshift parameters
            if not utc_start and not offset:
                # Check for VLC-style timestamp parameters
                if 'timestamp' in request.GET:
                    offset = request.GET.get('timestamp')
                elif 'time' in request.GET:
                    offset = request.GET.get('time')

            # Session ID now comes from URL path parameter
            # Remove legacy query parameter extraction since we're using path-based routing

            # Extract Range header for seeking support
            range_header = request.META.get('HTTP_RANGE')

            logger.info(f"[VOD-TIMESHIFT] Timeshift params - utc_start: {utc_start}, utc_end: {utc_end}, offset: {offset}")
            logger.info(f"[VOD-SESSION] Session ID: {session_id}")

            # Log all query parameters for debugging
            if request.GET:
                logger.debug(f"[VOD-PARAMS] All query params: {dict(request.GET)}")

            if range_header:
                logger.info(f"[VOD-RANGE] Range header: {range_header}")

                # Parse the range to understand what position VLC is seeking to
                try:
                    if 'bytes=' in range_header:
                        range_part = range_header.replace('bytes=', '')
                        if '-' in range_part:
                            start_byte, end_byte = range_part.split('-', 1)
                            if start_byte:
                                start_pos_mb = int(start_byte) / (1024 * 1024)
                                logger.info(f"[VOD-SEEK] Seeking to byte position: {start_byte} (~{start_pos_mb:.1f} MB)")
                                if int(start_byte) > 0:
                                    logger.info(f"[VOD-SEEK] *** ACTUAL SEEK DETECTED *** Position: {start_pos_mb:.1f} MB")
                            else:
                                logger.info(f"[VOD-SEEK] Open-ended range request (from start)")
                            if end_byte:
                                end_pos_mb = int(end_byte) / (1024 * 1024)
                                logger.info(f"[VOD-SEEK] End position: {end_byte} bytes (~{end_pos_mb:.1f} MB)")
                except Exception as e:
                    logger.warning(f"[VOD-SEEK] Could not parse range header: {e}")

                # Simple seek detection - track rapid requests
                current_time = time.time()
                request_key = f"{client_ip}:{content_type}:{content_id}"

                if not hasattr(self.__class__, '_request_times'):
                    self.__class__._request_times = {}

                if request_key in self.__class__._request_times:
                    time_diff = current_time - self.__class__._request_times[request_key]
                    if time_diff < 5.0:
                        logger.info(f"[VOD-SEEK] Rapid request detected ({time_diff:.1f}s) - likely seeking")

                self.__class__._request_times[request_key] = current_time
            else:
                logger.info(f"[VOD-RANGE] No Range header - full content request")

            logger.info(f"[VOD-CLIENT] Client info - IP: {client_ip}, User-Agent: {client_user_agent[:50]}...")

            # If no session ID, create one and redirect to path-based URL
            if not session_id:
                new_session_id = f"vod_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
                logger.info(f"[VOD-SESSION] Creating new session: {new_session_id}")

                # Build redirect URL with session ID in path, preserve query parameters
                path_parts = request.path.rstrip('/').split('/')

                # Construct new path: /vod/movie/UUID/SESSION_ID or /vod/movie/UUID/SESSION_ID/PROFILE_ID/
                if profile_id:
                    new_path = f"{'/'.join(path_parts)}/{new_session_id}/{profile_id}/"
                else:
                    new_path = f"{'/'.join(path_parts)}/{new_session_id}"

                # Preserve any query parameters (except session_id)
                query_params = dict(request.GET)
                query_params.pop('session_id', None)  # Remove if present

                if query_params:
                    from urllib.parse import urlencode
                    query_string = urlencode(query_params, doseq=True)
                    redirect_url = f"{new_path}?{query_string}"
                else:
                    redirect_url = new_path

                logger.info(f"[VOD-SESSION] Redirecting to path-based URL: {redirect_url}")

                return HttpResponse(
                    status=301,
                    headers={'Location': redirect_url}
                )

            # Extract preferred M3U account ID and stream ID from query parameters
            preferred_m3u_account_id = request.GET.get('m3u_account_id')
            preferred_stream_id = request.GET.get('stream_id')

            if preferred_m3u_account_id:
                try:
                    preferred_m3u_account_id = int(preferred_m3u_account_id)
                except (ValueError, TypeError):
                    logger.warning(f"[VOD-PARAM] Invalid m3u_account_id parameter: {preferred_m3u_account_id}")
                    preferred_m3u_account_id = None

            if preferred_stream_id:
                logger.info(f"[VOD-PARAM] Preferred stream ID: {preferred_stream_id}")

            # Get the content object and its relation
            content_obj, relation = self._get_content_and_relation(content_type, content_id, preferred_m3u_account_id, preferred_stream_id)
            if not content_obj or not relation:
                logger.error(f"[VOD-ERROR] Content or relation not found: {content_type} {content_id}")
                raise Http404(f"Content not found: {content_type} {content_id}")

            logger.info(f"[VOD-CONTENT] Found content: {getattr(content_obj, 'name', 'Unknown')}")

            # Get M3U account from relation
            m3u_account = relation.m3u_account
            logger.info(f"[VOD-ACCOUNT] Using M3U account: {m3u_account.name}")

            # Get stream URL from relation
            stream_url = self._get_stream_url_from_relation(relation)
            logger.info(f"[VOD-CONTENT] Content URL: {stream_url or 'No URL found'}")

            if not stream_url:
                logger.error(f"[VOD-ERROR] No stream URL available for {content_type} {content_id}")
                return HttpResponse("No stream URL available", status=503)

            # Get M3U profile (returns profile and current connection count)
            profile_result = self._get_m3u_profile(m3u_account, profile_id, session_id)

            if not profile_result or not profile_result[0]:
                logger.error(f"[VOD-ERROR] No suitable M3U profile found for {content_type} {content_id}")
                return HttpResponse("No available stream", status=503)

            m3u_profile, current_connections = profile_result
            logger.info(f"[VOD-PROFILE] Using M3U profile: {m3u_profile.id} (max_streams: {m3u_profile.max_streams}, current: {current_connections})")

            # Connection tracking is handled by the connection manager
            # Transform URL based on profile
            final_stream_url = self._transform_url(stream_url, m3u_profile)
            logger.info(f"[VOD-URL] Final stream URL: {final_stream_url}")

            # Validate stream URL
            if not final_stream_url or not final_stream_url.startswith(('http://', 'https://')):
                logger.error(f"[VOD-ERROR] Invalid stream URL: {final_stream_url}")
                return HttpResponse("Invalid stream URL", status=500)

            # Get connection manager (Redis-backed for multi-worker support)
            connection_manager = MultiWorkerVODConnectionManager.get_instance()

            # Stream the content with session-based connection reuse
            logger.info("[VOD-STREAM] Calling connection manager to stream content")
            response = connection_manager.stream_content_with_session(
                session_id=session_id,
                content_obj=content_obj,
                stream_url=final_stream_url,
                m3u_profile=m3u_profile,
                client_ip=client_ip,
                client_user_agent=client_user_agent,
                request=request,
                utc_start=utc_start,
                utc_end=utc_end,
                offset=offset,
                range_header=range_header
            )

            logger.info(f"[VOD-SUCCESS] Stream response created successfully, type: {type(response)}")
            return response

        except Exception as e:
            logger.error(f"[VOD-EXCEPTION] Error streaming {content_type} {content_id}: {e}", exc_info=True)
            return HttpResponse(f"Streaming error: {str(e)}", status=500)

    def head(self, request, content_type, content_id, session_id=None, profile_id=None):
        """
        Handle HEAD requests for FUSE filesystem integration

        Returns content length and session URL header for subsequent GET requests
        """
        logger.info(f"[VOD-HEAD] HEAD request: {content_type}/{content_id}, session: {session_id}, profile: {profile_id}")

        try:
            # Get client info for M3U profile selection
            client_ip, client_user_agent = get_client_info(request)
            logger.info(f"[VOD-HEAD] Client info - IP: {client_ip}, User-Agent: {client_user_agent[:50] if client_user_agent else 'None'}...")

            # If no session ID, create one (same logic as GET)
            if not session_id:
                new_session_id = f"vod_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
                logger.info(f"[VOD-HEAD] Creating new session for HEAD: {new_session_id}")

                # Build session URL for response header
                path_parts = request.path.rstrip('/').split('/')
                if profile_id:
                    session_url = f"{'/'.join(path_parts)}/{new_session_id}/{profile_id}/"
                else:
                    session_url = f"{'/'.join(path_parts)}/{new_session_id}"

                session_id = new_session_id
            else:
                # Session already in URL, construct the current session URL
                session_url = request.path
                logger.info(f"[VOD-HEAD] Using existing session: {session_id}")

            # Extract preferred M3U account ID and stream ID from query parameters
            preferred_m3u_account_id = request.GET.get('m3u_account_id')
            preferred_stream_id = request.GET.get('stream_id')

            if preferred_m3u_account_id:
                try:
                    preferred_m3u_account_id = int(preferred_m3u_account_id)
                except (ValueError, TypeError):
                    logger.warning(f"[VOD-HEAD] Invalid m3u_account_id parameter: {preferred_m3u_account_id}")
                    preferred_m3u_account_id = None

            if preferred_stream_id:
                logger.info(f"[VOD-HEAD] Preferred stream ID: {preferred_stream_id}")

            # Get content and relation (same as GET)
            content_obj, relation = self._get_content_and_relation(content_type, content_id, preferred_m3u_account_id, preferred_stream_id)
            if not content_obj or not relation:
                logger.error(f"[VOD-HEAD] Content or relation not found: {content_type} {content_id}")
                return HttpResponse("Content not found", status=404)

            # Get M3U account and stream URL
            m3u_account = relation.m3u_account
            stream_url = self._get_stream_url_from_relation(relation)
            if not stream_url:
                logger.error(f"[VOD-HEAD] No stream URL available for {content_type} {content_id}")
                return HttpResponse("No stream URL available", status=503)

            # Get M3U profile (returns profile and current connection count)
            profile_result = self._get_m3u_profile(m3u_account, profile_id, session_id)
            if not profile_result or not profile_result[0]:
                logger.error(f"[VOD-HEAD] No M3U profile found or all profiles at capacity")
                return HttpResponse("No available stream", status=503)

            m3u_profile, current_connections = profile_result

            # Transform URL if needed
            final_stream_url = self._transform_url(stream_url, m3u_profile)

            # Make a small range GET request to get content length since providers don't support HEAD
            # We'll use a tiny range to minimize data transfer but get the headers we need
            # Use M3U account's user agent as primary, client user agent as fallback
            m3u_user_agent = m3u_account.get_user_agent().user_agent if m3u_account.get_user_agent() else None
            headers = {
                'User-Agent': m3u_user_agent or client_user_agent or 'Dispatcharr/1.0',
                'Accept': '*/*',
                'Range': 'bytes=0-1'  # Request only first 2 bytes
            }

            logger.info(f"[VOD-HEAD] Making small range GET request to provider: {final_stream_url}")
            response = requests.get(final_stream_url, headers=headers, timeout=30, allow_redirects=True, stream=True)

            # Check for range support - should be 206 for partial content
            if response.status_code == 206:
                # Parse Content-Range header to get total file size
                content_range = response.headers.get('Content-Range', '')
                if content_range:
                    # Content-Range: bytes 0-1/1234567890
                    total_size = content_range.split('/')[-1]
                    logger.info(f"[VOD-HEAD] Got file size from Content-Range: {total_size}")
                else:
                    logger.warning(f"[VOD-HEAD] No Content-Range header in 206 response")
                    total_size = response.headers.get('Content-Length', '0')
            elif response.status_code == 200:
                # Server doesn't support range requests, use Content-Length from full response
                total_size = response.headers.get('Content-Length', '0')
                logger.info(f"[VOD-HEAD] Server doesn't support ranges, got Content-Length: {total_size}")
            else:
                logger.error(f"[VOD-HEAD] Provider GET request failed: {response.status_code}")
                return HttpResponse("Provider error", status=response.status_code)

            # Close the small range request - we don't need to keep this connection
            response.close()

            # Store the total content length in Redis for the persistent connection to use
            try:
                import redis
                r = redis.StrictRedis(host='localhost', port=6379, db=0, decode_responses=True)
                content_length_key = f"vod_content_length:{session_id}"
                r.set(content_length_key, total_size, ex=1800)  # Store for 30 minutes
                logger.info(f"[VOD-HEAD] Stored total content length {total_size} for session {session_id}")
            except Exception as e:
                logger.error(f"[VOD-HEAD] Failed to store content length in Redis: {e}")

            # Now create a persistent connection for the session (if one doesn't exist)
            # This ensures the FUSE GET requests will reuse the same connection

            connection_manager = MultiWorkerVODConnectionManager.get_instance()

            logger.info(f"[VOD-HEAD] Pre-creating persistent connection for session: {session_id}")

            # We don't actually stream content here, just ensure connection is ready
            # The actual GET requests from FUSE will use the persistent connection

            # Use the total_size we extracted from the range response
            provider_content_type = response.headers.get('Content-Type')

            if provider_content_type:
                content_type_header = provider_content_type
                logger.info(f"[VOD-HEAD] Using provider Content-Type: {content_type_header}")
            else:
                # Provider didn't send Content-Type, infer from URL
                inferred_content_type = infer_content_type_from_url(final_stream_url)
                if inferred_content_type:
                    content_type_header = inferred_content_type
                    logger.info(f"[VOD-HEAD] Provider missing Content-Type, inferred from URL: {content_type_header}")
                else:
                    content_type_header = 'video/mp4'
                    logger.info(f"[VOD-HEAD] No Content-Type from provider and could not infer from URL, using default: {content_type_header}")

            logger.info(f"[VOD-HEAD] Provider response - Total Size: {total_size}, Type: {content_type_header}")

            # Create response with content length and session URL header
            head_response = HttpResponse()
            head_response['Content-Length'] = total_size
            head_response['Content-Type'] = content_type_header
            head_response['Accept-Ranges'] = 'bytes'

            # Custom header with session URL for FUSE
            head_response['X-Session-URL'] = session_url
            head_response['X-Dispatcharr-Session'] = session_id

            logger.info(f"[VOD-HEAD] Returning HEAD response with session URL: {session_url}")
            return head_response

        except Exception as e:
            logger.error(f"[VOD-HEAD] Error in HEAD request: {e}", exc_info=True)
            return HttpResponse(f"HEAD error: {str(e)}", status=500)

    def _get_content_and_relation(self, content_type, content_id, preferred_m3u_account_id=None, preferred_stream_id=None):
        """Get the content object and its M3U relation"""
        try:
            logger.info(f"[CONTENT-LOOKUP] Looking up {content_type} with UUID {content_id}")
            if preferred_m3u_account_id:
                logger.info(f"[CONTENT-LOOKUP] Preferred M3U account ID: {preferred_m3u_account_id}")
            if preferred_stream_id:
                logger.info(f"[CONTENT-LOOKUP] Preferred stream ID: {preferred_stream_id}")

            if content_type == 'movie':
                content_obj = get_object_or_404(Movie, uuid=content_id)
                logger.info(f"[CONTENT-FOUND] Movie: {content_obj.name} (ID: {content_obj.id})")

                # Filter by preferred stream ID first (most specific)
                relations_query = content_obj.m3u_relations.filter(m3u_account__is_active=True)
                if preferred_stream_id:
                    specific_relation = relations_query.filter(stream_id=preferred_stream_id).first()
                    if specific_relation:
                        logger.info(f"[STREAM-SELECTED] Using specific stream: {specific_relation.stream_id} from provider: {specific_relation.m3u_account.name}")
                        return content_obj, specific_relation
                    else:
                        logger.warning(f"[STREAM-FALLBACK] Preferred stream ID {preferred_stream_id} not found, falling back to account/priority selection")

                # Filter by preferred M3U account if specified
                if preferred_m3u_account_id:
                    specific_relation = relations_query.filter(m3u_account__id=preferred_m3u_account_id).first()
                    if specific_relation:
                        logger.info(f"[PROVIDER-SELECTED] Using preferred provider: {specific_relation.m3u_account.name}")
                        return content_obj, specific_relation
                    else:
                        logger.warning(f"[PROVIDER-FALLBACK] Preferred M3U account {preferred_m3u_account_id} not found, using highest priority")

                # Get the highest priority active relation (fallback or default)
                relation = relations_query.select_related('m3u_account').order_by('-m3u_account__priority', 'id').first()

                if relation:
                    logger.info(f"[PROVIDER-SELECTED] Using provider: {relation.m3u_account.name} (priority: {relation.m3u_account.priority})")

                return content_obj, relation

            elif content_type == 'episode':
                content_obj = get_object_or_404(Episode, uuid=content_id)
                logger.info(f"[CONTENT-FOUND] Episode: {content_obj.name} (ID: {content_obj.id}, Series: {content_obj.series.name})")

                # Filter by preferred stream ID first (most specific)
                relations_query = content_obj.m3u_relations.filter(m3u_account__is_active=True)
                if preferred_stream_id:
                    specific_relation = relations_query.filter(stream_id=preferred_stream_id).first()
                    if specific_relation:
                        logger.info(f"[STREAM-SELECTED] Using specific stream: {specific_relation.stream_id} from provider: {specific_relation.m3u_account.name}")
                        return content_obj, specific_relation
                    else:
                        logger.warning(f"[STREAM-FALLBACK] Preferred stream ID {preferred_stream_id} not found, falling back to account/priority selection")

                # Filter by preferred M3U account if specified
                if preferred_m3u_account_id:
                    specific_relation = relations_query.filter(m3u_account__id=preferred_m3u_account_id).first()
                    if specific_relation:
                        logger.info(f"[PROVIDER-SELECTED] Using preferred provider: {specific_relation.m3u_account.name}")
                        return content_obj, specific_relation
                    else:
                        logger.warning(f"[PROVIDER-FALLBACK] Preferred M3U account {preferred_m3u_account_id} not found, using highest priority")

                # Get the highest priority active relation (fallback or default)
                relation = relations_query.select_related('m3u_account').order_by('-m3u_account__priority', 'id').first()

                if relation:
                    logger.info(f"[PROVIDER-SELECTED] Using provider: {relation.m3u_account.name} (priority: {relation.m3u_account.priority})")

                return content_obj, relation

            elif content_type == 'series':
                # For series, get the first episode
                series = get_object_or_404(Series, uuid=content_id)
                logger.info(f"[CONTENT-FOUND] Series: {series.name} (ID: {series.id})")
                episode = series.episodes.first()
                if not episode:
                    logger.error(f"[CONTENT-ERROR] No episodes found for series {series.name}")
                    return None, None

                logger.info(f"[CONTENT-FOUND] First episode: {episode.name} (ID: {episode.id})")

                # Filter by preferred stream ID first (most specific)
                relations_query = episode.m3u_relations.filter(m3u_account__is_active=True)
                if preferred_stream_id:
                    specific_relation = relations_query.filter(stream_id=preferred_stream_id).first()
                    if specific_relation:
                        logger.info(f"[STREAM-SELECTED] Using specific stream: {specific_relation.stream_id} from provider: {specific_relation.m3u_account.name}")
                        return episode, specific_relation
                    else:
                        logger.warning(f"[STREAM-FALLBACK] Preferred stream ID {preferred_stream_id} not found, falling back to account/priority selection")

                # Filter by preferred M3U account if specified
                if preferred_m3u_account_id:
                    specific_relation = relations_query.filter(m3u_account__id=preferred_m3u_account_id).first()
                    if specific_relation:
                        logger.info(f"[PROVIDER-SELECTED] Using preferred provider: {specific_relation.m3u_account.name}")
                        return episode, specific_relation
                    else:
                        logger.warning(f"[PROVIDER-FALLBACK] Preferred M3U account {preferred_m3u_account_id} not found, using highest priority")

                # Get the highest priority active relation (fallback or default)
                relation = relations_query.select_related('m3u_account').order_by('-m3u_account__priority', 'id').first()

                if relation:
                    logger.info(f"[PROVIDER-SELECTED] Using provider: {relation.m3u_account.name} (priority: {relation.m3u_account.priority})")

                return episode, relation
            else:
                logger.error(f"[CONTENT-ERROR] Invalid content type: {content_type}")
                return None, None

        except Exception as e:
            logger.error(f"Error getting content object: {e}")
            return None, None

    def _get_stream_url_from_relation(self, relation):
        """Get stream URL from the M3U relation"""
        try:
            # Log the relation type and available attributes
            logger.info(f"[VOD-URL] Relation type: {type(relation).__name__}")
            logger.info(f"[VOD-URL] Account type: {relation.m3u_account.account_type}")
            logger.info(f"[VOD-URL] Stream ID: {getattr(relation, 'stream_id', 'N/A')}")

            # First try the get_stream_url method (this should build URLs dynamically)
            if hasattr(relation, 'get_stream_url'):
                url = relation.get_stream_url()
                if url:
                    logger.info(f"[VOD-URL] Built URL from get_stream_url(): {url}")
                    return url
                else:
                    logger.warning(f"[VOD-URL] get_stream_url() returned None")

            logger.error(f"[VOD-URL] Relation has no get_stream_url method or it failed")
            return None
        except Exception as e:
            logger.error(f"[VOD-URL] Error getting stream URL from relation: {e}", exc_info=True)
            return None

    def _get_m3u_profile(self, m3u_account, profile_id, session_id=None):
        """Get appropriate M3U profile for streaming using Redis-based viewer counts

        Args:
            m3u_account: M3UAccount instance
            profile_id: Optional specific profile ID requested
            session_id: Optional session ID to check for existing connections

        Returns:
            tuple: (M3UAccountProfile, current_connections) or None if no profile found
        """
        try:
            from core.utils import RedisClient
            redis_client = RedisClient.get_client()

            if not redis_client:
                logger.warning("Redis not available, falling back to default profile")
                default_profile = M3UAccountProfile.objects.filter(
                    m3u_account=m3u_account,
                    is_active=True,
                    is_default=True
                ).first()
                return (default_profile, 0) if default_profile else None

            # Check if this session already has an active connection
            if session_id:
                persistent_connection_key = f"vod_persistent_connection:{session_id}"
                connection_data = redis_client.hgetall(persistent_connection_key)

                if connection_data:
                    # Decode Redis hash data
                    decoded_data = {}
                    for k, v in connection_data.items():
                        k_str = k.decode('utf-8') if isinstance(k, bytes) else k
                        v_str = v.decode('utf-8') if isinstance(v, bytes) else v
                        decoded_data[k_str] = v_str

                    existing_profile_id = decoded_data.get('m3u_profile_id')
                    if existing_profile_id:
                        try:
                            existing_profile = M3UAccountProfile.objects.get(
                                id=int(existing_profile_id),
                                m3u_account=m3u_account,
                                is_active=True
                            )
                            # Get current connections for logging
                            profile_connections_key = f"profile_connections:{existing_profile.id}"
                            current_connections = int(redis_client.get(profile_connections_key) or 0)

                            logger.info(f"[PROFILE-SELECTION] Session {session_id} reusing existing profile {existing_profile.id}: {current_connections}/{existing_profile.max_streams} connections")
                            return (existing_profile, current_connections)
                        except (M3UAccountProfile.DoesNotExist, ValueError):
                            logger.warning(f"[PROFILE-SELECTION] Session {session_id} has invalid profile ID {existing_profile_id}, selecting new profile")
                        except Exception as e:
                            logger.warning(f"[PROFILE-SELECTION] Error checking existing profile for session {session_id}: {e}")
                    else:
                        logger.debug(f"[PROFILE-SELECTION] Session {session_id} exists but has no profile ID stored")            # If specific profile requested, try to use it
            if profile_id:
                try:
                    profile = M3UAccountProfile.objects.get(
                        id=profile_id,
                        m3u_account=m3u_account,
                        is_active=True
                    )
                    # Check Redis-based current connections
                    profile_connections_key = f"profile_connections:{profile.id}"
                    current_connections = int(redis_client.get(profile_connections_key) or 0)

                    if profile.max_streams == 0 or current_connections < profile.max_streams:
                        logger.info(f"[PROFILE-SELECTION] Using requested profile {profile.id}: {current_connections}/{profile.max_streams} connections")
                        return (profile, current_connections)
                    else:
                        logger.warning(f"[PROFILE-SELECTION] Requested profile {profile.id} is at capacity: {current_connections}/{profile.max_streams}")
                except M3UAccountProfile.DoesNotExist:
                    logger.warning(f"[PROFILE-SELECTION] Requested profile {profile_id} not found")

            # Get active profiles ordered by priority (default first)
            m3u_profiles = M3UAccountProfile.objects.filter(
                m3u_account=m3u_account,
                is_active=True
            )

            default_profile = m3u_profiles.filter(is_default=True).first()
            if not default_profile:
                logger.error(f"[PROFILE-SELECTION] No default profile found for M3U account {m3u_account.id}")
                return None

            # Check profiles in order: default first, then others
            profiles = [default_profile] + list(m3u_profiles.filter(is_default=False))

            for profile in profiles:
                profile_connections_key = f"profile_connections:{profile.id}"
                current_connections = int(redis_client.get(profile_connections_key) or 0)

                # Check if profile has available connection slots
                if profile.max_streams == 0 or current_connections < profile.max_streams:
                    logger.info(f"[PROFILE-SELECTION] Selected profile {profile.id} ({profile.name}): {current_connections}/{profile.max_streams} connections")
                    return (profile, current_connections)
                else:
                    logger.debug(f"[PROFILE-SELECTION] Profile {profile.id} at capacity: {current_connections}/{profile.max_streams}")

            # All profiles are at capacity - return None to trigger error response
            logger.error(f"[PROFILE-SELECTION] All profiles at capacity for M3U account {m3u_account.id}, rejecting request")
            return None

        except Exception as e:
            logger.error(f"Error getting M3U profile: {e}")
            return None

    def _transform_url(self, original_url, m3u_profile):
        """Transform URL based on M3U profile settings"""
        try:
            import re

            if not original_url:
                return None

            search_pattern = m3u_profile.search_pattern
            replace_pattern = m3u_profile.replace_pattern
            safe_replace_pattern = re.sub(r'\$(\d+)', r'\\\1', replace_pattern)

            if search_pattern and replace_pattern:
                transformed_url = re.sub(search_pattern, safe_replace_pattern, original_url)
                return transformed_url

            return original_url

        except Exception as e:
            logger.error(f"Error transforming URL: {e}")
            return original_url

@method_decorator(csrf_exempt, name='dispatch')
class VODPlaylistView(View):
    """Generate M3U playlists for VOD content"""

    def get(self, request, profile_id=None):
        """Generate VOD playlist"""
        try:
            # Get profile if specified
            m3u_profile = None
            if profile_id:
                try:
                    m3u_profile = M3UAccountProfile.objects.get(
                        id=profile_id,
                        is_active=True
                    )
                except M3UAccountProfile.DoesNotExist:
                    return HttpResponse("Profile not found", status=404)

            # Generate playlist content
            playlist_content = self._generate_playlist(m3u_profile)

            response = HttpResponse(playlist_content, content_type='application/vnd.apple.mpegurl')
            response['Content-Disposition'] = 'attachment; filename="vod_playlist.m3u8"'
            return response

        except Exception as e:
            logger.error(f"Error generating VOD playlist: {e}")
            return HttpResponse("Playlist generation error", status=500)

    def _generate_playlist(self, m3u_profile=None):
        """Generate M3U playlist content for VOD"""
        lines = ["#EXTM3U"]

        # Add movies
        movies = Movie.objects.filter(is_active=True)
        if m3u_profile:
            movies = movies.filter(m3u_account=m3u_profile.m3u_account)

        for movie in movies:
            profile_param = f"?profile={m3u_profile.id}" if m3u_profile else ""
            lines.append(f'#EXTINF:-1 tvg-id="{movie.tmdb_id}" group-title="Movies",{movie.title}')
            lines.append(f'/proxy/vod/movie/{movie.uuid}/{profile_param}')

        # Add series
        series_list = Series.objects.filter(is_active=True)
        if m3u_profile:
            series_list = series_list.filter(m3u_account=m3u_profile.m3u_account)

        for series in series_list:
            for episode in series.episodes.all():
                profile_param = f"?profile={m3u_profile.id}" if m3u_profile else ""
                episode_title = f"{series.title} - S{episode.season_number:02d}E{episode.episode_number:02d}"
                lines.append(f'#EXTINF:-1 tvg-id="{series.tmdb_id}" group-title="Series",{episode_title}')
                lines.append(f'/proxy/vod/episode/{episode.uuid}/{profile_param}')

        return '\n'.join(lines)


@method_decorator(csrf_exempt, name='dispatch')
class VODPositionView(View):
    """Handle VOD position updates"""

    def post(self, request, content_id):
        """Update playback position for VOD content"""
        try:
            import json
            data = json.loads(request.body)
            client_id = data.get('client_id')
            position = data.get('position', 0)

            # Find the content object
            content_obj = None
            try:
                content_obj = Movie.objects.get(uuid=content_id)
            except Movie.DoesNotExist:
                try:
                    content_obj = Episode.objects.get(uuid=content_id)
                except Episode.DoesNotExist:
                    return JsonResponse({'error': 'Content not found'}, status=404)

            # Here you could store the position in a model or cache
            # For now, just return success
            logger.info(f"Position update for {content_obj.__class__.__name__} {content_id}: {position}s")

            return JsonResponse({
                'success': True,
                'content_id': str(content_id),
                'position': position
            })

        except Exception as e:
            logger.error(f"Error updating VOD position: {e}")
            return JsonResponse({'error': str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class VODStatsView(View):
    """Get VOD connection statistics"""

    def get(self, request):
        """Get current VOD connection statistics"""
        try:
            connection_manager = MultiWorkerVODConnectionManager.get_instance()
            redis_client = connection_manager.redis_client

            if not redis_client:
                return JsonResponse({'error': 'Redis not available'}, status=500)

            # Get all VOD persistent connections (consolidated data)
            pattern = "vod_persistent_connection:*"
            cursor = 0
            connections = []
            current_time = time.time()

            while True:
                cursor, keys = redis_client.scan(cursor, match=pattern, count=100)

                for key in keys:
                    try:
                        key_str = key.decode('utf-8') if isinstance(key, bytes) else key
                        connection_data = redis_client.hgetall(key)

                        if connection_data:
                            # Extract session ID from key
                            session_id = key_str.replace('vod_persistent_connection:', '')

                            # Decode Redis hash data
                            combined_data = {}
                            for k, v in connection_data.items():
                                k_str = k.decode('utf-8') if isinstance(k, bytes) else k
                                v_str = v.decode('utf-8') if isinstance(v, bytes) else v
                                combined_data[k_str] = v_str

                            # Get content info from the connection data (using correct field names)
                            content_type = combined_data.get('content_obj_type', 'unknown')
                            content_uuid = combined_data.get('content_uuid', 'unknown')
                            client_id = session_id

                            # Get content info with enhanced metadata
                            content_name = "Unknown"
                            content_metadata = {}
                            try:
                                if content_type == 'movie':
                                    content_obj = Movie.objects.select_related('logo').get(uuid=content_uuid)
                                    content_name = content_obj.name

                                    # Get duration from content object
                                    duration_secs = None
                                    if hasattr(content_obj, 'duration_secs') and content_obj.duration_secs:
                                        duration_secs = content_obj.duration_secs

                                    # If we don't have duration_secs, try to calculate it from file size and position data
                                    if not duration_secs:
                                        file_size_bytes = int(combined_data.get('total_content_size', 0))
                                        last_seek_byte = int(combined_data.get('last_seek_byte', 0))
                                        last_seek_percentage = float(combined_data.get('last_seek_percentage', 0.0))

                                        # Calculate position if we have the required data
                                        if file_size_bytes and file_size_bytes > 0 and last_seek_percentage > 0:
                                            # If we know the seek percentage and current time position, we can estimate duration
                                            # But we need to know the current time position in seconds first
                                            # For now, let's use a rough estimate based on file size and typical bitrates
                                            # This is a fallback - ideally duration should be in the database
                                            estimated_duration = 6000  # 100 minutes as default for movies
                                            duration_secs = estimated_duration

                                    content_metadata = {
                                        'year': content_obj.year,
                                        'rating': content_obj.rating,
                                        'genre': content_obj.genre,
                                        'duration_secs': duration_secs,
                                        'description': content_obj.description,
                                        'logo_url': content_obj.logo.url if content_obj.logo else None,
                                        'tmdb_id': content_obj.tmdb_id,
                                        'imdb_id': content_obj.imdb_id
                                    }
                                elif content_type == 'episode':
                                    content_obj = Episode.objects.select_related('series', 'series__logo').get(uuid=content_uuid)
                                    content_name = f"{content_obj.series.name} - {content_obj.name}"

                                    # Get duration from content object
                                    duration_secs = None
                                    if hasattr(content_obj, 'duration_secs') and content_obj.duration_secs:
                                        duration_secs = content_obj.duration_secs

                                    # If we don't have duration_secs, estimate for episodes
                                    if not duration_secs:
                                        estimated_duration = 2400  # 40 minutes as default for episodes
                                        duration_secs = estimated_duration

                                    content_metadata = {
                                        'series_name': content_obj.series.name,
                                        'episode_name': content_obj.name,
                                        'season_number': content_obj.season_number,
                                        'episode_number': content_obj.episode_number,
                                        'air_date': content_obj.air_date.isoformat() if content_obj.air_date else None,
                                        'rating': content_obj.rating,
                                        'duration_secs': duration_secs,
                                        'description': content_obj.description,
                                        'logo_url': content_obj.series.logo.url if content_obj.series.logo else None,
                                        'series_year': content_obj.series.year,
                                        'series_genre': content_obj.series.genre,
                                        'tmdb_id': content_obj.tmdb_id,
                                        'imdb_id': content_obj.imdb_id
                                    }
                            except:
                                pass

                            # Get M3U profile information
                            m3u_profile_info = {}
                            m3u_profile_id = combined_data.get('m3u_profile_id')
                            if m3u_profile_id:
                                try:
                                    from apps.m3u.models import M3UAccountProfile
                                    profile = M3UAccountProfile.objects.select_related('m3u_account').get(id=m3u_profile_id)
                                    m3u_profile_info = {
                                        'profile_name': profile.name,
                                        'account_name': profile.m3u_account.name,
                                        'account_id': profile.m3u_account.id,
                                        'max_streams': profile.m3u_account.max_streams,
                                        'm3u_profile_id': int(m3u_profile_id)
                                    }
                                except Exception as e:
                                    logger.warning(f"Could not fetch M3U profile {m3u_profile_id}: {e}")

                            # Also try to get profile info from stored data if database lookup fails
                            if not m3u_profile_info and combined_data.get('m3u_profile_name'):
                                m3u_profile_info = {
                                    'profile_name': combined_data.get('m3u_profile_name', 'Unknown Profile'),
                                    'm3u_profile_id': combined_data.get('m3u_profile_id'),
                                    'account_name': 'Unknown Account'  # We don't store account name directly
                                }

                            # Calculate estimated current position based on seek percentage or last known position
                            last_known_position = int(combined_data.get('position_seconds', 0))
                            last_position_update = combined_data.get('last_position_update')
                            last_seek_percentage = float(combined_data.get('last_seek_percentage', 0.0))
                            last_seek_timestamp = float(combined_data.get('last_seek_timestamp', 0.0))
                            estimated_position = last_known_position

                            # If we have seek percentage and content duration, calculate position from that
                            if last_seek_percentage > 0 and content_metadata.get('duration_secs'):
                                try:
                                    duration_secs = int(content_metadata['duration_secs'])
                                    # Calculate position from seek percentage
                                    seek_position = int((last_seek_percentage / 100) * duration_secs)

                                    # If we have a recent seek timestamp, add elapsed time since seek
                                    if last_seek_timestamp > 0:
                                        elapsed_since_seek = current_time - last_seek_timestamp
                                        # Add elapsed time but don't exceed content duration
                                        estimated_position = min(
                                            seek_position + int(elapsed_since_seek),
                                            duration_secs
                                        )
                                    else:
                                        estimated_position = seek_position
                                except (ValueError, TypeError):
                                    pass
                            elif last_position_update and content_metadata.get('duration_secs'):
                                # Fallback: use time-based estimation from position_seconds
                                try:
                                    update_timestamp = float(last_position_update)
                                    elapsed_since_update = current_time - update_timestamp
                                    # Add elapsed time to last known position, but don't exceed content duration
                                    estimated_position = min(
                                        last_known_position + int(elapsed_since_update),
                                        int(content_metadata['duration_secs'])
                                    )
                                except (ValueError, TypeError):
                                    # If timestamp parsing fails, fall back to last known position
                                    estimated_position = last_known_position

                            connection_info = {
                                'content_type': content_type,
                                'content_uuid': content_uuid,
                                'content_name': content_name,
                                'content_metadata': content_metadata,
                                'm3u_profile': m3u_profile_info,
                                'client_id': client_id,
                                'client_ip': combined_data.get('client_ip', 'Unknown'),
                                'user_agent': combined_data.get('client_user_agent', 'Unknown'),
                                'connected_at': combined_data.get('created_at'),
                                'last_activity': combined_data.get('last_activity'),
                                'm3u_profile_id': m3u_profile_id,
                                'position_seconds': estimated_position,  # Use estimated position
                                'last_known_position': last_known_position,  # Include raw position for debugging
                                'last_position_update': last_position_update,  # Include timestamp for frontend use
                                'bytes_sent': int(combined_data.get('bytes_sent', 0)),
                                # Seek/range information for position calculation and frontend display
                                'last_seek_byte': int(combined_data.get('last_seek_byte', 0)),
                                'last_seek_percentage': float(combined_data.get('last_seek_percentage', 0.0)),
                                'total_content_size': int(combined_data.get('total_content_size', 0)),
                                'last_seek_timestamp': float(combined_data.get('last_seek_timestamp', 0.0))
                            }

                            # Calculate connection duration
                            duration_calculated = False
                            if connection_info['connected_at']:
                                try:
                                    connected_time = float(connection_info['connected_at'])
                                    duration = current_time - connected_time
                                    connection_info['duration'] = int(duration)
                                    duration_calculated = True
                                except:
                                    pass

                            # Fallback: use last_activity if connected_at is not available
                            if not duration_calculated and connection_info['last_activity']:
                                try:
                                    last_activity_time = float(connection_info['last_activity'])
                                    # Estimate connection duration using client_id timestamp if available
                                    if connection_info['client_id'].startswith('vod_'):
                                        # Extract timestamp from client_id (format: vod_timestamp_random)
                                        parts = connection_info['client_id'].split('_')
                                        if len(parts) >= 2:
                                            client_start_time = float(parts[1]) / 1000.0  # Convert ms to seconds
                                            duration = current_time - client_start_time
                                            connection_info['duration'] = int(duration)
                                            duration_calculated = True
                                except:
                                    pass

                            # Final fallback
                            if not duration_calculated:
                                connection_info['duration'] = 0

                            connections.append(connection_info)

                    except Exception as e:
                        logger.error(f"Error processing connection key {key}: {e}")

                if cursor == 0:
                    break

            # Group connections by content
            content_stats = {}
            for conn in connections:
                content_key = f"{conn['content_type']}:{conn['content_uuid']}"
                if content_key not in content_stats:
                    content_stats[content_key] = {
                        'content_type': conn['content_type'],
                        'content_name': conn['content_name'],
                        'content_uuid': conn['content_uuid'],
                        'content_metadata': conn['content_metadata'],
                        'connection_count': 0,
                        'connections': []
                    }
                content_stats[content_key]['connection_count'] += 1
                content_stats[content_key]['connections'].append(conn)

            return JsonResponse({
                'vod_connections': list(content_stats.values()),
                'total_connections': len(connections),
                'timestamp': current_time
            })

        except Exception as e:
            logger.error(f"Error getting VOD stats: {e}")
            return JsonResponse({'error': str(e)}, status=500)
