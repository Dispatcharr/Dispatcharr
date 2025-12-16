# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Automated configuration backup/restore system with scheduled backups, retention policies, and async task processing - Thanks [@stlalpha](https://github.com/stlalpha) (Closes #153)

### Changed

- Removed unreachable code path in m3u output - Thanks [@DawtCom](https://github.com/DawtCom)

### Fixed

- VOD episode processing now correctly handles duplicate episodes (same episode in multiple languages/qualities) by reusing Episode records across multiple M3UEpisodeRelation entries instead of attempting to create duplicates (Fixes #556)
- nginx now gracefully handles hosts without IPv6 support by automatically disabling IPv6 binding at startup (Fixes #744)
- XtreamCodes EPG API now returns correct date/time format for start/end fields and proper string types for timestamps and channel_id
- XtreamCodes EPG API now handles None values for title and description fields to prevent AttributeError

## [0.14.0] - 2025-12-09

### Added

- Sort buttons for 'Group' and 'M3U' columns in Streams table for improved stream organization and filtering - Thanks [@bobey6](https://github.com/bobey6)
- EPG source priority field for controlling which EPG source is preferred when multiple sources have matching entries for a channel (higher numbers = higher priority) (Closes #603)

### Changed

- EPG program parsing optimized for sources with many channels but only a fraction mapped. Now parses XML file once per source instead of once per channel, dramatically reducing I/O and CPU overhead. For sources with 10,000 channels and 100 mapped, this results in ~99x fewer file opens and ~100x fewer full file scans. Orphaned programs for unmapped channels are also cleaned up during refresh to prevent database bloat. Database updates are now atomic to prevent clients from seeing empty/partial EPG data during refresh.
- EPG table now displays detailed status messages including refresh progress, success messages, and last message for idle sources (matching M3U table behavior) (Closes #214)
- IPv6 access now allowed by default with all IPv6 CIDRs accepted - Thanks [@adrianmace](https://github.com/adrianmace)
- nginx.conf updated to bind to both IPv4 and IPv6 ports - Thanks [@jordandalley](https://github.com/jordandalley)
- EPG matching now respects source priority and only uses active (enabled) EPG sources (Closes #672)
- EPG form API Key field now only visible when Schedules Direct source type is selected

### Fixed

- EPG table "Updated" column now updates in real-time via WebSocket using the actual backend timestamp instead of requiring a page refresh
- Bulk channel editor confirmation dialog now displays the correct stream profile name that will be applied to the selected channels.
- uWSGI not found and 502 bad gateway on first startup

## [0.13.1] - 2025-12-06

### Fixed

- JWT token generated so is unique for each deployment

## [0.13.0] - 2025-12-02

### Added

- `CHANGELOG.md` file following Keep a Changelog format to document all notable changes and project history
- System event logging and viewer: Comprehensive logging system that tracks internal application events (M3U refreshes, EPG updates, stream switches, errors) with a dedicated UI viewer for filtering and reviewing historical events. Improves monitoring, troubleshooting, and understanding system behavior
- M3U/EPG endpoint caching: Implements intelligent caching for frequently requested M3U playlists and EPG data to reduce database load and improve response times for clients.
- Search icon to name headers for the channels and streams tables (#686)
- Comprehensive logging for user authentication events and network access restrictions
- Validation for EPG objects and payloads in updateEPG functions to prevent errors from invalid data
- Referrerpolicy to YouTube iframes in series and VOD modals for better compatibility

### Changed

- XC player API now returns server_info for unknown actions to align with provider behavior
- XC player API refactored to streamline action handling and ensure consistent responses
- Date parsing logic in generate_custom_dummy_programs improved to handle empty or invalid inputs
- DVR cards now reflect date and time formats chosen by user - Thanks [@Biologisten](https://github.com/Biologisten)
- "Uncategorized" categories and relations now automatically created for VOD accounts to improve content management (#627)
- Improved minimum horizontal size in the stats page for better usability on smaller displays
- M3U and EPG generation now handles missing channel profiles with appropriate error logging

### Fixed

- Episode URLs in series modal now use UUID instead of ID, fixing broken links (#684, #694)
- Stream preview now respects selected M3U profile instead of always using default profile (#690)
- Channel groups filter in M3UGroupFilter component now filters out non-existent groups (prevents blank webui when editing M3U after a group was removed)
- Stream order now preserved in PATCH/PUT responses from ChannelSerializer, ensuring consistent ordering across all API operations - Thanks [@FiveBoroughs](https://github.com/FiveBoroughs) (#643)
- XC client compatibility: float channel numbers now converted to integers
- M3U account and profile modals now scrollable on mobile devices for improved usability

## [0.12.0] - 2025-11-19

### Added

- RTSP stream support with automatic protocol detection when a proxy profile requires it. The proxy now forces FFmpeg for RTSP sources and properly handles RTSP URLs - Thanks [@ragchuck](https://github.com/ragchuck) (#184)
- UDP stream support, including correct handling when a proxy profile specifies a UDP source. The proxy now skips HTTP-specific headers (like `user_agent`) for non-HTTP protocols and performs manual redirect handling to improve reliability (#617)
- Separate VOD logos system with a new `VODLogo` model, database migration, dedicated API/viewset, and server-paginated UI. This separates movie/series logos from channel logos, making cleanup safer and enabling independent bulk operations

### Changed

- Background profile refresh now uses a rate-limiting/backoff strategy to avoid provider bans
- Bulk channel editing now validates all requested changes up front and applies updates in a single database transaction
- ProxyServer shutdown & ghost-client handling improved to avoid initializing channels for transient clients and prevent duplicate reinitialization during rapid reconnects
- URL / Stream validation expanded to support credentials on non-FQDN hosts, skips HTTP-only checks for RTSP/RTP/UDP streams, and improved host/port normalization
- TV guide scrolling & timeline synchronization improved with mouse-wheel scrolling, synchronized timeline position with guide navigation, and improved mobile momentum scrolling (#252)
- EPG Source dropdown now sorts alphabetically - Thanks [@0x53c65c0a8bd30fff](https://github.com/0x53c65c0a8bd30fff)
- M3U POST handling restored and improved for clients (e.g., Smarters) that request playlists using HTTP POST - Thanks [@maluueu](https://github.com/maluueu)
- Login form revamped with branding, cleaner layout, loading state, "Remember Me" option, and focused sign-in flow
- Series & VOD now have copy-link buttons in modals for easier URL sharing
- `get_host_and_port` now prioritizes verified port sources and handles reverse-proxy edge cases more accurately (#618)

### Fixed

- EXTINF parsing overhauled to correctly extract attributes such as `tvg-id`, `tvg-name`, and `group-title`, even when values include quotes or commas (#637)
- Websocket payload size reduced during EPG processing to avoid UI freezes, blank screens, or memory spikes in the browser (#327)
- Logo management UI fixes including confirmation dialogs, header checkbox reset, delete button reliability, and full client refetch after cleanup

## [0.11.2] - 2025-11-04

### Added

- Custom Dummy EPG improvements:
  - Support for using an existing Custom Dummy EPG as a template for creating new EPGs
  - Custom fallback templates for unmatched patterns
  - `{endtime}` as an available output placeholder and renamed `{time}` → `{starttime}` (#590)
  - Support for date placeholders that respect both source and output timezones (#597)
  - Ability to bulk assign Custom Dummy EPGs to multiple channels
  - "Include New Tag" option to mark programs as new in Dummy EPG output
  - Support for month strings in date parsing
  - Ability to set custom posters and channel logos via regex patterns for Custom Dummy EPGs
  - Improved DST handling by calculating offsets based on the actual program date, not today's date

### Changed

- Stream model maximum URL length increased from 2000 to 4096 characters (#585)
- Groups now sorted during `xc_get_live_categories` based on the order they first appear (by lowest channel number)
- Client TTL settings updated and periodic refresh implemented during active streaming to maintain accurate connection tracking
- `ProgramData.sub_title` field changed from `CharField` to `TextField` to allow subtitles longer than 255 characters (#579)
- Startup improved by verifying `/data` directory ownership and automatically fixing permissions if needed. Pre-creates `/data/models` during initialization (#614)
- Port detection enhanced to check `request.META.get("SERVER_PORT")` before falling back to defaults, ensuring correct port when generating M3U, EPG, and logo URLs - Thanks [@lasharor](https://github.com/lasharor)

### Fixed

- Custom Dummy EPG frontend DST calculation now uses program date instead of current date
- Channel titles no longer truncated early after an apostrophe - Thanks [@0x53c65c0a8bd30fff](https://github.com/0x53c65c0a8bd30fff)

## [0.11.1] - 2025-10-22

### Fixed

- uWSGI not receiving environmental variables
- LXC unable to access daemons launched by uWSGI ([#575](https://github.com/Dispatcharr/Dispatcharr/issues/575), [#576](https://github.com/Dispatcharr/Dispatcharr/issues/576), [#577](https://github.com/Dispatcharr/Dispatcharr/issues/577))

## [0.11.0] - 2025-10-22

### Added

- Custom Dummy EPG system:
  - Regex pattern matching and name source selection
  - Support for custom upcoming and ended programs
  - Timezone-aware with source and local timezone selection
  - Option to include categories and date/live tags in Dummy EPG output
  - (#293)
- Auto-Enable & Category Improvements:
  - Auto-enable settings for new groups and categories in M3U and VOD components (#208)
- IPv6 CIDR validation in Settings - Thanks [@jordandalley](https://github.com/jordandalley) (#236)
- Custom logo support for channel groups in Auto Sync Channels (#555)
- Tooltips added to the Stream Table

### Changed

- Celery and uWSGI now have configurable `nice` levels (defaults: `uWSGI=0`, `Celery=5`) to prioritize streaming when needed. (#571)
- Directory creation and ownership management refactored in init scripts to avoid unnecessary recursive `chown` operations and improve boot speed
- HTTP streamer switched to threaded model with piped output for improved robustness
- Chunk timeout configuration improved and StreamManager timeout handling enhanced
- Proxy timeout values reduced to avoid unnecessary waiting
- Resource cleanup improved to prevent "Too many open files" errors
- Proxy settings caching implemented and database connections properly closed after use
- EPG program fetching optimized with chunked retrieval and explicit ordering to reduce memory usage during output
- EPG output now sorted by channel number for consistent presentation
- Stream Table buttons reordered for better usability
- Database connection handling improved throughout the codebase to reduce overall connection count

### Fixed

- Crash when resizing columns in the Channel Table (#516)
- Errors when saving stream settings (#535)
- Preview and edit bugs for custom streams where profile and group selections did not display correctly
- `channel_id` and `channel.uuid` now converted to strings before processing to fix manual switching when the uWSGI worker was not the stream owner (#269)
- Stream locking and connection search issues when switching channels; increased search timeout to reduce premature failures (#503)
- Stream Table buttons no longer shift into multiple rows when selecting many streams
- Custom stream previews
- Custom Stream settings not loading properly (#186)
- Orphaned categories now automatically removed for VOD and Series during M3U refresh (#540)

## [0.10.4] - 2025-10-08

### Added

- "Assign TVG-ID from EPG" functionality with frontend actions for single-channel and batch operations
- Confirmation dialogs in `ChannelBatchForm` for setting names, logos, TVG-IDs, and clearing EPG assignments
- "Clear EPG" button to `ChannelBatchForm` for easy reset of assignments
- Batch editing of channel logos - Thanks [@EmeraldPi](https://github.com/EmeraldPi)
- Ability to set logo name from URL - Thanks [@EmeraldPi](https://github.com/EmeraldPi)
- Proper timestamp tracking for channel creation and updates; `XC Get Live Streams` now uses this information
- Time Zone Settings added to the application ([#482](https://github.com/Dispatcharr/Dispatcharr/issues/482), [#347](https://github.com/Dispatcharr/Dispatcharr/issues/347))
- Comskip settings support including comskip.ini upload and custom directory selection (#418)
- Manual recording scheduling for channels without EPG data (#162)

### Changed

- Default M3U account type is now set to XC for new accounts
- Performance optimization: Only fetch playlists and channel profiles after a successful M3U refresh (rather than every status update)
- Playlist retrieval now includes current connection counts and improved session handling during VOD session start
- Improved stream selection logic when all profiles have reached max connections (retries faster)

### Fixed

- Large EPGs now fully parse all channels
- Duplicate channel outputs for streamer profiles set to "All"
- Streamer profiles with "All" assigned now receive all eligible channels
- PostgreSQL btree index errors from logo URL validation during channel creation (#519)
- M3U processing lock not releasing when no streams found during XC refresh, which also skipped VOD scanning (#449)
- Float conversion errors by normalizing decimal format during VOD scanning (#526)
- Direct URL ordering in M3U output to use correct stream sequence (#528)
- Adding multiple M3U accounts without refreshing modified only the first entry (#397)
- UI state bug where new playlist creation was not notified to frontend ("Fetching Groups" stuck)
- Minor FFmpeg task and stream termination bugs in DVR module
- Input escaping issue where single quotes were interpreted as code delimiters (#406)

## [0.10.3] - 2025-10-04

### Added

- Logo management UI improvements where Channel editor now uses the Logo Manager modal, allowing users to add logos by URL directly from the edit form - Thanks [@EmeraldPi](https://github.com/EmeraldPi)

### Changed

- FFmpeg base container rebuilt with improved native build support - Thanks [@EmeraldPi](https://github.com/EmeraldPi)
- GitHub Actions workflow updated to use native runners instead of QEMU emulation for more reliable multi-architecture builds

### Fixed

- EPG parsing stability when large EPG files would not fully parse all channels. Parser now uses `iterparse` with `recover=True` for both channel and program-level parsing, ensuring complete and resilient XML processing even when Cloudflare injects additional root elements

## [0.10.2] - 2025-10-03

### Added

- `m3u_id` parameter to `generate_hash_key` and updated related calls
- Support for `x-tvg-url` and `url-tvg` generation with preserved query parameters (#345)
- Exact Gracenote ID matching for EPG channel mapping (#291)
- Recovery handling for XMLTV parser errors
- `nice -n 5` added to Celery commands for better process priority management

### Changed

- Default M3U hash key changed to URL only for new installs
- M3U profile retrieval now includes current connection counts and improved session handling during VOD session start
- Improved stream selection logic when all profiles have reached max connections (retries faster)
- XMLTV parsing refactored to use `iterparse` for `<tv>` element
- Release workflow refactored to run on native architecture
- Docker build system improvements:
  - Split install/build steps
  - Switch from Yarn → NPM
  - Updated to Node.js 24 (frontend build)
  - Improved ARM build reliability
  - Pushes to DockerHub with combined manifest
  - Removed redundant tags and improved build organization

### Fixed

- Cloudflare-hosted EPG feeds breaking parsing (#497)
- Bulk channel creation now preserves the order channels were selected in (no longer reversed)
- M3U hash settings not saving properly
- VOD selecting the wrong M3U profile at session start (#461)
- Redundant `h` removed from 12-hour time format in settings page

## [0.10.1] - 2025-09-24

### Added

- Virtualized rendering for TV Guide for smoother performance when displaying large guides - Thanks [@stlalpha](https://github.com/stlalpha) (#438)
- Enhanced channel/program mapping to reuse EPG data across multiple channels that share the same TVG-ID

### Changed

- `URL` field length in EPGSource model increased from 200 → 1000 characters to support long URLs with tokens
- Improved URL transformation logic with more advanced regex during profile refreshes
- During EPG scanning, the first display name for a channel is now used instead of the last
- `whiteSpace` style changed from `nowrap` → `pre` in StreamsTable for better text formatting

### Fixed

- EPG channel parsing failure when channel `URL` exceeded 500 characters by adding validation during scanning (#452)
- Frontend incorrectly saving case-sensitive setting as a JSON string for stream filters

## [0.10.0] - 2025-09-18

### Added

- Channel Creation Improvements:
  - Ability to specify channel number during channel creation ([#377](https://github.com/Dispatcharr/Dispatcharr/issues/377), [#169](https://github.com/Dispatcharr/Dispatcharr/issues/169))
  - Asynchronous bulk channel creation from stream IDs with WebSocket progress updates
  - WebSocket notifications when channels are created
- EPG Auto-Matching (Rewritten & Enhanced):
  - Completely refactored for improved accuracy and efficiency
  - Can now be applied to selected channels or triggered directly from the channel edit form
  - Uses stricter matching logic with support from sentence transformers
  - Added progress notifications during the matching process
  - Implemented memory cleanup for ML models after matching operations
  - Removed deprecated matching scripts
- Logo & EPG Management:
  - Ability in channel edit form and bulk channel editor to set logos and names from assigned EPG (#157)
  - Improved logo update flow: frontend refreshes on changes, store updates after bulk changes, progress shown via notifications
- Table Enhancements:
  - All tables now support adjustable column resizing (#295)
  - Channels and Streams tables persist column widths and center divider position to local storage
  - Improved sizing and layout for user-agents, stream profiles, logos, M3U, and EPG tables

### Changed

- Simplified VOD and series access: removed user-level restrictions on M3U accounts
- Skip disabled M3U accounts when choosing streams during playback (#402)
- Enhanced `UserViewSet` queryset to prefetch related channel profiles for better performance
- Auto-focus added to EPG filter input
- Category API retrieval now sorts by name
- Increased default column size for EPG fields and removed max size on group/EPG columns
- Standardized EPG column header to display `(EPG ID - TVG-ID)`

### Fixed

- Bug during VOD cleanup where all VODs not from the current M3U scan could be deleted
- Logos not being set correctly in some cases
- Bug where not setting a channel number caused an error when creating a channel (#422)
- Bug where clicking "Add Channel" with a channel selected opened the edit form instead
- Bug where a newly created channel could reuse streams from another channel due to form not clearing properly
- VOD page not displaying correct order while changing pages
- `ReferenceError: setIsInitialized is not defined` when logging into web UI
- `cannot access local variable 'total_chunks' where it is not associated with a value` during VOD refresh

## [0.9.1] - 2025-09-13

### Fixed

- Broken migrations affecting the plugins system
- DVR and plugin paths to ensure proper functionality (#381)

## [0.9.0] - 2025-09-12

### Added

- **Video on Demand (VOD) System:**
  - Complete VOD infrastructure with support for movies and TV series
  - Advanced VOD metadata including IMDB/TMDB integration, trailers, cast information
  - Smart VOD categorization with filtering by type (movies vs series)
  - Multi-provider VOD support with priority-based selection
  - VOD streaming proxy with connection tracking and statistics
  - Season/episode organization for TV series with expandable episode details
  - VOD statistics and monitoring integrated with existing stats dashboard
  - Optimized VOD parsing and category filtering
  - Dedicated VOD page with movies and series tabs
  - Rich VOD modals with backdrop images, trailers, and metadata
  - Episode management with season-based organization
  - Play button integration with external player support
  - VOD statistics cards similar to channel cards
- **Plugin System:**
  - Extensible Plugin Framework - Developers can build custom functionality without modifying Dispatcharr core
  - Plugin Discovery & Management - Automatic detection of installed plugins, with enable/disable controls in the UI
  - Backend API Support - New APIs for listing, loading, and managing plugins programmatically
  - Plugin Registry - Structured models for plugin metadata (name, version, author, description)
  - UI Enhancements - Dedicated Plugins page in the admin panel for centralized plugin management
  - Documentation & Scaffolding - Initial documentation and scaffolding to accelerate plugin development
- **DVR System:**
  - Refreshed DVR page for managing scheduled and completed recordings
  - Global pre/post padding controls surfaced in Settings
  - Playback support for completed recordings directly in the UI
  - DVR table view includes title, channel, time, and padding adjustments for clear scheduling
  - Improved population of DVR listings, fixing intermittent blank screen issues
  - Comskip integration for automated commercial detection and skipping in recordings
  - User-configurable comskip toggle in Settings
- **Enhanced Channel Management:**
  - EPG column added to channels table for better organization
  - EPG filtering by channel assignment and source name
  - Channel batch renaming for efficient bulk channel name updates
  - Auto channel sync improvements with custom stream profile override
  - Channel logo management overhaul with background loading
- Date and time format customization in settings - Thanks [@Biologisten](https://github.com/Biologisten)
- Auto-refresh intervals for statistics with better UI controls
- M3U profile notes field for better organization
- XC account information retrieval and display with account refresh functionality and notifications

### Changed

- JSONB field conversion for custom properties (replacing text fields) for better performance
- Database encoding converted from ASCII to UTF8 for better character support
- Batch processing for M3U updates and channel operations
- Query optimization with prefetch_related to eliminate N+1 queries
- Reduced API calls by fetching all data at once instead of per-category
- Buffering speed setting now affects UI indicators
- Swagger endpoint accessible with or without trailing slash
- EPG source names displayed before channel names in edit forms
- Logo loading improvements with background processing
- Channel card enhancements with better status indicators
- Group column width optimization
- Better content-type detection for streams
- Improved headers with content-range and total length
- Enhanced user-agent handling for M3U accounts
- HEAD request support with connection keep-alive
- Progress tracking improvements for clients with new sessions
- Server URL length increased to 1000 characters for token support
- Prettier formatting applied to all frontend code
- String quote standardization and code formatting improvements

### Fixed

- Logo loading issues in channel edit forms resolved
- M3U download error handling and user feedback improved
- Unique constraint violations fixed during stream rehashing
- Channel stats fetching moved from Celery beat task to configurable API calls
- Speed badge colors now use configurable buffering speed setting
- Channel cards properly close when streams stop
- Active streams labeling updated from "Active Channels"
- WebSocket updates for client connect/disconnect events
- Null value handling before database saves
- Empty string scrubbing for cleaner data
- Group relationship cleanup for removed M3U groups
- Logo cleanup for unused files with proper batch processing
- Recordings start 5 mins after show starts (#102)

### Closed

- [#350](https://github.com/Dispatcharr/Dispatcharr/issues/350): Allow DVR recordings to be played via the UI
- [#349](https://github.com/Dispatcharr/Dispatcharr/issues/349): DVR screen doesn't populate consistently
- [#340](https://github.com/Dispatcharr/Dispatcharr/issues/340): Global find and replace
- [#311](https://github.com/Dispatcharr/Dispatcharr/issues/311): Stat's "Current Speed" does not reflect "Buffering Speed" setting
- [#304](https://github.com/Dispatcharr/Dispatcharr/issues/304): Name ignored when uploading logo
- [#300](https://github.com/Dispatcharr/Dispatcharr/issues/300): Updating Logo throws error
- [#286](https://github.com/Dispatcharr/Dispatcharr/issues/286): 2 Value/Column EPG in Channel Edit
- [#280](https://github.com/Dispatcharr/Dispatcharr/issues/280): Add general text field in M3U/XS profiles
- [#190](https://github.com/Dispatcharr/Dispatcharr/issues/190): Show which stream is being used and allow it to be altered in channel properties
- [#155](https://github.com/Dispatcharr/Dispatcharr/issues/155): Additional column with EPG assignment information / Allow filtering by EPG assignment
- [#138](https://github.com/Dispatcharr/Dispatcharr/issues/138): Bulk Channel Edit Functions

## [0.8.0] - 2025-08-19

### Added

- Channel & Stream Enhancements:
  - Preview streams under a channel, with stream logo and name displayed in the channel card
  - Advanced stats for channel streams
  - Stream qualities displayed in the channel table
  - Stream stats now saved to the database
  - URL badges can now be clicked to copy stream links to the clipboard
- M3U Filtering for Streams:
  - Streams for an M3U account can now be filtered using flexible parameters
  - Apply filters based on stream name, group title, or stream URL (via regex)
  - Filters support both inclusion and exclusion logic for precise control
  - Multiple filters can be layered with a priority order for complex rules
- Ability to reverse the sort order for auto channel sync
- Custom validator for URL fields now allows non-FQDN hostnames (#63)
- Membership creation added in `UpdateChannelMembershipAPIView` if not found (#275)

### Changed

- Bumped Postgres to version 17
- Updated dependencies in `requirements.txt` for compatibility and improvements
- Improved chunked extraction to prevent memory issues - Thanks [@pantherale0](https://github.com/pantherale0)

### Fixed

- XML escaping for channel ID in `generate_dummy_epg` function
- Bug where creating a channel from a stream not displayed in the table used an invalid stream name
- Debian install script - Thanks [@deku-m](https://github.com/deku-m)

## [0.7.1] - 2025-07-29

### Added

- Natural sorting for channel names during auto channel sync
- Ability to sort auto sync order by provider order (default), channel name, TVG ID, or last updated time
- Auto-created channels can now be assigned to specific channel profiles (#255)
- Channel profiles are now fetched automatically after a successful M3U refresh
- Uses only whole numbers when assigning the next available channel number

### Changed

- Logo upload behavior changed to wait for the Create button before saving
- Uses the channel name as the display name in EPG output for improved readability
- Ensures channels are only added to a selected profile if one is explicitly chosen

### Fixed

- Logo Manager prevents redundant messages from the file scanner by properly tracking uploaded logos in Redis
- Fixed an issue preventing logo uploads via URL
- Adds internal support for assigning multiple profiles via API

## [0.7.0] - 2025-07-19

### Added

- **Logo Manager:**
  - Complete logo management system with filtering, search, and usage tracking
  - Upload logos directly through the UI
  - Automatically scan `/data/logos` for existing files (#69)
  - View which channels use each logo
  - Bulk delete unused logos with cleanup
  - Enhanced display with hover effects and improved sizing
  - Improved logo fetching with timeouts and user-agent headers to prevent hanging
- **Group Manager:**
  - Comprehensive group management interface (#128)
  - Search and filter groups with ease
  - Bulk operations for cleanup
  - Filter channels by group membership
  - Automatically clean up unused groups
- **Auto Channel Sync:**
  - Automatic channel synchronization from M3U sources (#147)
  - Configure auto-sync settings per M3U account group
  - Set starting channel numbers by group
  - Override group names during sync
  - Apply regex match and replace for channel names
  - Filter channels by regex match on stream name
  - Track auto-created vs manually added channels
  - Smart updates preserve UUIDs and existing links
- Stream rehashing with WebSocket notifications
- Better error handling for blocked rehash attempts
- Lock acquisition to prevent conflicts
- Real-time progress tracking

### Changed

- Persist table page sizes in local storage (streams & channels)
- Smoother pagination and improved UX
- Fixed z-index issues during table refreshes
- Improved XC client with connection pooling
- Better error handling for API and JSON decode failures
- Smarter handling of empty content and blocking responses
- Improved EPG XML generation with richer metadata
- Better support for keywords, languages, ratings, and credits
- Better form layouts and responsive buttons
- Enhanced confirmation dialogs and feedback

### Fixed

- Channel table now correctly restores page size from local storage
- Resolved WebSocket message formatting issues
- Fixed logo uploads and edits
- Corrected ESLint issues across the codebase
- Fixed HTML validation errors in menus
- Optimized logo fetching with proper timeouts and headers ([#101](https://github.com/Dispatcharr/Dispatcharr/issues/101), [#217](https://github.com/Dispatcharr/Dispatcharr/issues/217))

## [0.6.2] - 2025-07-10

### Fixed

- **Streaming & Connection Stability:**
  - Provider timeout issues - Slow but responsive providers no longer cause channel lockups
  - Added chunk and process timeouts - Prevents hanging during stream processing and transcoding
  - Improved connection handling - Enhanced process management and socket closure detection for safer streaming
  - Enhanced health monitoring - Health monitor now properly notifies main thread without attempting reconnections
- **User Interface & Experience:**
  - Touch screen compatibility - Web player can now be properly closed on touch devices
  - Improved user management - Added support for first/last names, login tracking, and standardized table formatting
- Improved logging - Enhanced log messages with channel IDs for better debugging
- Code cleanup - Removed unused imports, variables, and dead links

## [0.6.1] - 2025-06-27

### Added

- Dynamic parameter options for M3U and EPG URLs (#207)
- Support for 'num' property in channel number extraction (fixes channel creation from XC streams not having channel numbers)

### Changed

- EPG generation now uses streaming responses to prevent client timeouts during large EPG file generation (#179)
- Improved reliability when downloading EPG data from external sources
- Better program positioning - Programs that start before the current view now have proper text positioning (#223)
- Better mobile support - Improved sizing and layout for mobile devices across multiple tables
- Responsive stats cards - Better calculation for card layout and improved filling on different screen sizes (#218)
- Enhanced table rendering - M3U and EPG tables now render better on small screens
- Optimized spacing - Removed unnecessary padding and blank space throughout the interface
- Better settings layout - Improved minimum widths and mobile support for settings pages
- Always show 2 decimal places for FFmpeg speed values

### Fixed

- TV Guide now properly filters channels based on selected channel group
- Resolved loading issues - Fixed channels and groups not loading correctly in the TV Guide
- Stream profile fixes - Resolved issue with setting stream profile to 'use default'
- Single channel editing - When only one channel is selected, the correct channel editor now opens
- Bulk edit improvements - Added "no change" options for bulk editing operations
- Bulk channel editor now properly saves changes (#222)
- Link form improvements - Better sizing and rendering of link forms with proper layering
- Confirmation dialogs added with warning suppression for user deletion, channel profile deletion, and M3U profile deletion

## [0.6.0] - 2025-06-19

### Added

- **User Management & Access Control:**
  - Complete user management system with user levels and channel access controls
  - Network access control with CIDR validation and IP-based restrictions
  - Logout functionality and improved loading states for authenticated users
- **Xtream Codes Output:**
  - Xtream Codes support enables easy output to IPTV clients (#195)
- **Stream Management & Monitoring:**
  - FFmpeg statistics integration - Real-time display of video/audio codec info, resolution, speed, and stream type
  - Automatic stream switching when buffering is detected
  - Enhanced stream profile management with better connection tracking
  - Improved stream state detection, including buffering as an active state
- **Channel Management:**
  - Bulk channel editing for channel group, stream profile, and user access level
- **Enhanced M3U & EPG Features:**
  - Dynamic `tvg-id` source selection for M3U and EPG (`tvg_id`, `gracenote`, or `channel_number`)
  - Direct URL support in M3U output via `direct=true` parameter
  - Flexible EPG output with a configurable day limit via `days=#` parameter
  - Support for LIVE tags and `dd_progrid` numbering in EPG processing
- Proxy settings configuration with UI integration and improved validation
- Stream retention controls - Set stale stream days to `0` to disable retention completely (#123)
- Tuner flexibility - Minimum of 1 tuner now allowed for HDHomeRun output
- Fallback IP geolocation provider (#127) - Thanks [@maluueu](https://github.com/maluueu)
- POST method now allowed for M3U output, enabling support for Smarters IPTV - Thanks [@maluueu](https://github.com/maluueu)

### Changed

- Improved channel cards with better status indicators and tooltips
- Clearer error messaging for unsupported codecs in the web player
- Network access warnings to prevent accidental lockouts
- Case-insensitive M3U parsing for improved compatibility
- Better EPG processing with improved channel matching
- Replaced Mantine React Table with custom implementations
- Improved tooltips and parameter wrapping for cleaner interfaces
- Better badge colors and status indicators
- Stronger form validation and user feedback
- Streamlined settings management using JSON configs
- Default value population for clean installs
- Environment-specific configuration support for multiple deployment scenarios

### Fixed

- FFmpeg process cleanup - Ensures FFmpeg fully exits before marking connection closed
- Resolved stream profile update issues in statistics display
- Fixed M3U profile ID behavior when switching streams
- Corrected stream switching logic - Redis is only updated on successful switches
- Fixed connection counting - Excludes the current profile from available connection counts
- Fixed custom stream channel creation when no group is assigned (#122)
- Resolved EPG auto-matching deadlock when many channels match simultaneously - Thanks [@xham3](https://github.com/xham3)

## [0.5.2] - 2025-06-03

### Added

- Direct Logo Support: Added ability to bypass logo caching by adding `?cachedlogos=false` to the end of M3U and EPG URLs (#109)

### Changed

- Dynamic Resource Management: Auto-scales Celery workers based on demand, reducing overall memory and CPU usage while still allowing high-demand tasks to complete quickly (#111)
- Enhanced Logging:
  - Improved logging for M3U processing
  - Better error output from XML parser for easier troubleshooting

### Fixed

- XMLTV Parsing: Added `remove_blank_text=True` to lxml parser to prevent crashes with poorly formatted XMLTV files (#115)
- Stats Display: Refactored channel info retrieval for safer decoding and improved error logging, fixing intermittent issues with statistics not displaying properly

## [0.5.1] - 2025-05-28

### Added

- Support for ZIP-compressed EPG files
- Automatic extraction of compressed files after downloading
- Intelligent file type detection for EPG sources:
  - Reads the first bits of files to determine file type
  - If a compressed file is detected, it peeks inside to find XML files
- Random descriptions for dummy channels in the TV guide
- Support for decimal channel numbers (converted from integer to float) - Thanks [@MooseyOnTheLoosey](https://github.com/MooseyOnTheLoosey)
- Show channels without EPG data in TV Guide
- Profile name added to HDHR-friendly name and device ID (allows adding multiple HDHR profiles to Plex)

### Changed

- About 30% faster EPG processing
- Significantly improved memory usage for large EPG files
- Improved timezone handling
- Cleaned up cached files when deleting EPG sources
- Performance improvements when processing extremely large M3U files
- Improved batch processing with better cleanup
- Enhanced WebSocket update handling for large operations
- Redis configured for better performance (no longer saves to disk)
- Improved memory management for Celery tasks
- Separated beat schedules with a file scanning interval set to 20 seconds
- Improved authentication error handling with user redirection to the login page
- Improved channel card formatting for different screen resolutions (can now actually read the channel stats card on mobile)
- Decreased line height for status messages in the EPG and M3U tables for better appearance on smaller screens
- Updated the EPG form to match the M3U form for consistency

### Fixed

- Profile selection issues that previously caused WebUI crashes
- Issue with `tvc-guide-id` (Gracenote ID) in bulk channel creation
- Bug when uploading an M3U with the default user-agent set
- Bug where multiple channel initializations could occur, causing zombie streams and performance issues (choppy streams)
- Better error handling for buffer overflow issues
- Fixed various memory leaks
- Bug in the TV Guide that would crash the web UI when selecting a profile to filter by
- Multiple minor bug fixes and code cleanup

## [0.5.0] - 2025-05-15

### Added

- **XtreamCodes Support:**
  - Initial XtreamCodes client support
  - Option to add EPG source with XC account
  - Improved XC login and authentication
  - Improved error handling for XC connections
- **Hardware Acceleration:**
  - Detection of hardware acceleration capabilities with recommendations (available in logs after startup)
  - Improved support for NVIDIA, Intel (QSV), and VAAPI acceleration methods
  - Added necessary drivers and libraries for hardware acceleration
  - Automatically assigns required permissions for hardware acceleration
  - Thanks to [@BXWeb](https://github.com/BXWeb), @chris.r3x, [@rykr](https://github.com/rykr), @j3111, [@jesmannstl](https://github.com/jesmannstl), @jimmycarbone, [@gordlaben](https://github.com/gordlaben), [@roofussummers](https://github.com/roofussummers), [@slamanna212](https://github.com/slamanna212)
- **M3U and EPG Management:**
  - Enhanced M3U profile creation with live regex results
  - Added stale stream detection with configurable thresholds
  - Improved status messaging for M3U and EPG operations:
    - Shows download speed with estimated time remaining
    - Shows parsing time remaining
  - Added "Pending Setup" status for M3U's requiring group selection
  - Improved handling of M3U group filtering
- **UI Improvements:**
  - Added configurable table sizes
  - Enhanced video player with loading and error states
  - Improved WebSocket connection handling with authentication
  - Added confirmation dialogs for critical operations
  - Auto-assign numbers now configurable by selection
  - Added bulk editing of channel profile membership (select multiple channels, then click the profile toggle on any selected channel to apply the change to all)
- **Infrastructure & Performance:**
  - Standardized and improved the logging system
  - New environment variable to set logging level: `DISPATCHARR_LOG_LEVEL` (default: `INFO`, available: `TRACE`, `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`)
  - Introduced a new base image build process: updates are now significantly smaller (typically under 15MB unless the base image changes)
  - Improved environment variable handling in container
- Support for Gracenote ID (`tvc-guide-stationid`) - Thanks [@rykr](https://github.com/rykr)
- Improved file upload handling with size limits removed

### Fixed

- Issues with profiles not loading correctly
- Problems with stream previews in tables
- Channel creation and editing workflows
- Logo display issues
- WebSocket connection problems
- Multiple React-related errors and warnings
- Pagination and filtering issues in tables

## [0.4.1] - 2025-05-01

### Changed

- Optimized uWSGI configuration settings for better server performance
- Improved asynchronous processing by converting additional timers to gevent
- Enhanced EPG (Electronic Program Guide) downloading with proper user agent headers

### Fixed

- Issue with "add streams to channel" functionality to correctly follow disabled state logic

## [0.4.0] - 2025-05-01

### Added

- URL copy buttons for stream and channel URLs
- Manual stream switching ability
- EPG auto-match notifications - Users now receive feedback about how many matches were found
- Informative tooltips throughout the interface, including stream profiles and user-agent details
- Display of connected time for each client
- Current M3U profile information to stats
- Better logging for which channel clients are getting chunks from

### Changed

- Table System Rewrite: Completely refactored channel and stream tables for dramatically improved performance with large datasets
- Improved Concurrency: Replaced time.sleep with gevent.sleep for better performance when handling multiple streams
- Improved table interactions:
  - Restored alternating row colors and hover effects
  - Added shift-click support for multiple row selection
  - Preserved drag-and-drop functionality
- Adjusted logo display to prevent layout shifts with different sized logos
- Improved sticky headers in tables
- Fixed spacing and padding in EPG and M3U tables for better readability on smaller displays
- Stream URL handling improved for search/replace patterns
- Enhanced stream lock management for better reliability
- Added stream name to channel status for better visibility
- Properly track current stream ID during stream switches
- Improved EPG cache handling and cleanup of old cache files
- Corrected content type for M3U file (using m3u instead of m3u8)
- Fixed logo URL handling in M3U generation
- Enhanced tuner count calculation to include only active M3U accounts
- Increased thread stack size in uwsgi configuration
- Changed proxy to use uwsgi socket
- Added build timestamp to version information
- Reduced excessive logging during M3U/EPG file importing
- Improved store variable handling to increase application efficiency
- Frontend now being built by Yarn instead of NPM

### Fixed

- Issues with channel statistics randomly not working
- Stream ordering in channel selection
- M3U profile name added to stream names for better identification
- Channel form not updating some properties after saving
- Issue with setting logos to default
- Channel creation from streams
- Channel group saving
- Improved error handling throughout the application
- Bugs in deleting stream profiles
- Resolved mimetype detection issues
- Fixed form display issues
- Added proper requerying after form submissions and item deletions
- Bug overwriting tvg-id when loading TV Guide
- Bug that prevented large m3u's and epg's from uploading
- Typo in Stream Profile header column for Description - Thanks [@LoudSoftware](https://github.com/LoudSoftware)
- Typo in m3u input processing (tv-chno instead of tvg-chno) - Thanks @www2a

## [0.3.3] - 2025-04-18

### Fixed

- Issue with dummy EPG calculating hours above 24, ensuring time values remain within valid 24-hour format
- Auto import functionality to properly process old files that hadn't been imported yet, rather than ignoring them

## [0.3.2] - 2025-04-16

### Fixed

- Issue with stream ordering for channels - resolved problem where stream objects were incorrectly processed when assigning order in channel configurations

## [0.3.1] - 2025-04-16

### Added

- Key to navigation links in sidebar to resolve DOM errors when loading web UI
- Channels that are set to 'dummy' epg to the TV Guide

### Fixed

- Issue preventing dummy EPG from being set
- Channel numbers not saving properly
- EPGs not refreshing when linking EPG to channel
- Improved error messages in notifications

## [0.3.0] - 2025-04-15

### Added

- URL validation for redirect profile:
  - Validates stream URLs before redirecting clients
  - Prevents clients from being redirected to unavailable streams
  - Now tries alternate streams when primary stream validation fails
- Dynamic tuner configuration for HDHomeRun devices:
  - TunerCount is now dynamically created based on profile max connections
  - Sets minimum of 2 tuners, up to 10 for unlimited profiles

### Changed

- More robust stream switching:
  - Clients now wait properly if a stream is in the switching state
  - Improved reliability during stream transitions
- Performance enhancements:
  - Increased workers and threads for uwsgi for better concurrency

### Fixed

- Issue with multiple dead streams in a row - System now properly handles cases where several sequential streams are unavailable
- Broken links to compose files in documentation

## [0.2.1] - 2025-04-13

### Fixed

- Stream preview (not channel)
- Streaming wouldn't work when using default user-agent for an M3U
- WebSockets and M3U profile form issues

## [0.2.0] - 2025-04-12

Initial beta public release.
