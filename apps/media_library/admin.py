from django.contrib import admin

from apps.media_library.models import (
    ArtworkAsset,
    Library,
    LibraryLocation,
    LibraryScan,
    MediaFile,
    MediaItem,
    MediaItemVODLink,
    WatchProgress,
)


admin.site.register(Library)
admin.site.register(LibraryLocation)
admin.site.register(MediaItem)
admin.site.register(MediaFile)
admin.site.register(MediaItemVODLink)
admin.site.register(ArtworkAsset)
admin.site.register(WatchProgress)
admin.site.register(LibraryScan)
