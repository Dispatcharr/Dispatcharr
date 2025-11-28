# HLS Output Integration Design

## Overview
Properly integrate HLS Output into Dispatcharr's existing architecture by extending the StreamProfile system and using existing proxy infrastructure.

## Architecture

### 1. StreamProfile Extension
- Create locked HLS stream profiles (similar to ffmpeg, streamlink)
- Profiles will use ffmpeg to generate HLS output
- Example profiles:
  - **HLS 1080p** - Single quality HLS output at 1080p
  - **HLS 720p** - Single quality HLS output at 720p
  - **HLS ABR** - Adaptive Bitrate with multiple qualities
  - **HLS LL** - Low-Latency HLS

### 2. HLS Global Settings (CoreSettings)
Store HLS configuration in CoreSettings with key `'hls-output-settings'`:
```json
{
  "segment_duration": 4,
  "playlist_size": 10,
  "dvr_window_seconds": 7200,
  "storage_path": "/var/www/hls",
  "use_memory_storage": false,
  "segment_cache_ttl": 86400,
  "playlist_cache_ttl": 2,
  "enable_ll_hls": false,
  "partial_segment_duration": 0.33
}
```

### 3. HLS URL Generation
Add HLS URL button to Channels page:
- Base URL: `/hls/channel/{channel.uuid}/master.m3u8`
- Configurable parameters:
  - `quality` - Select specific quality (1080p, 720p, 480p, 360p)
  - `dvr` - Enable DVR window (true/false)
  - `ll` - Enable low-latency mode (true/false)

### 4. HLS Proxy Integration
Extend existing proxy system to serve HLS:
- Use apps/proxy/hls_proxy (already exists for HLS input)
- Add HLS output endpoint that:
  1. Gets channel's stream profile
  2. If profile is HLS type, generates HLS output
  3. Serves master playlist and media playlists
  4. Serves segments from storage or memory

### 5. FFmpeg Command Templates
HLS profiles use ffmpeg with HLS-specific parameters:

**HLS 1080p Profile:**
```
ffmpeg -user_agent {userAgent} -i {streamUrl} \
  -c:v libx264 -preset veryfast -b:v 5000k -maxrate 5000k -bufsize 10000k \
  -s 1920x1080 -c:a aac -b:a 192k -ar 48000 \
  -f hls -hls_time 4 -hls_list_size 10 -hls_flags delete_segments \
  -hls_segment_filename /var/www/hls/{channelId}/1080p_%03d.ts \
  /var/www/hls/{channelId}/1080p.m3u8
```

**HLS ABR Profile:**
```
ffmpeg -user_agent {userAgent} -i {streamUrl} \
  -filter_complex "[0:v]split=4[v1][v2][v3][v4]" \
  -map "[v1]" -c:v libx264 -b:v 5000k -s 1920x1080 -map 0:a -c:a aac -b:a 192k \
  -f hls -hls_time 4 -var_stream_map "v:0,a:0" \
  -master_pl_name master.m3u8 \
  /var/www/hls/{channelId}/1080p.m3u8 \
  -map "[v2]" -c:v libx264 -b:v 2800k -s 1280x720 -map 0:a -c:a aac -b:a 128k \
  -f hls -hls_time 4 -var_stream_map "v:1,a:1" \
  /var/www/hls/{channelId}/720p.m3u8 \
  ...
```

### 6. Settings Page Integration
Add "HLS Output" accordion to Settings page (like Proxy Settings):
- Global HLS configuration form
- Save/Reset buttons
- No profile creation (profiles are created in Stream Profiles section)

### 7. Channel Assignment
Channels can be assigned HLS stream profiles:
- In Channel edit modal, select HLS profile from Stream Profile dropdown
- HLS profiles appear alongside ffmpeg, Proxy, Redirect, streamlink

## Implementation Plan

### Phase 3: Implement HLS Stream Profiles
1. Create migration to add HLS-specific fields to StreamProfile (optional)
2. Create data migration to add locked HLS profiles
3. Update StreamProfile.build_command() to support {channelId} placeholder
4. Test profile creation and assignment

### Phase 4: Add HLS Global Settings
1. Create HLS settings form component (like ProxySettings)
2. Add HLS Output accordion to Settings.jsx
3. Create API endpoint for HLS settings (get/update)
4. Test settings save/load

### Phase 5: Add HLS URL Generation
1. Add HLS URL generation function to ChannelsTable.jsx
2. Add HLS button to Channels page header
3. Create HLS URL popover with configuration options
4. Test URL generation and copying

### Phase 6: Implement HLS Serving (Future)
1. Create HLS output views in apps/proxy/hls_proxy
2. Implement master playlist generation
3. Implement media playlist generation
4. Implement segment serving
5. Add caching and cleanup

## Benefits of This Approach

1. **Consistent with Dispatcharr architecture** - Uses existing StreamProfile system
2. **No duplicate code** - Reuses proxy infrastructure
3. **User-friendly** - Users create HLS profiles like any other stream profile
4. **Flexible** - Users can create custom HLS profiles with different settings
5. **Maintainable** - All stream profiles managed in one place
6. **No breaking changes** - Doesn't affect existing functionality

## Migration Path

1. Remove broken HLS Output implementation ✅
2. Design proper integration ✅
3. Implement HLS stream profiles
4. Add HLS global settings
5. Add HLS URL generation
6. Implement HLS serving (can be done later)

