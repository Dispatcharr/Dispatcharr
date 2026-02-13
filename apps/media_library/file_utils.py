from __future__ import annotations

from typing import Iterable, Optional

from django.db.models import Q

from apps.media_library.models import MediaFile, MediaFileLink, MediaItem


def media_files_for_item(media_item: MediaItem):
    if not media_item:
        return MediaFile.objects.none()
    return (
        MediaFile.objects.filter(
            Q(media_item=media_item) | Q(item_links__media_item=media_item)
        )
        .distinct()
    )


def primary_media_file_for_item(media_item: MediaItem) -> Optional[MediaFile]:
    if not media_item:
        return None
    link = (
        MediaFileLink.objects.filter(media_item=media_item, is_primary=True)
        .select_related("media_file")
        .first()
    )
    if link:
        return link.media_file
    files = media_files_for_item(media_item)
    return files.filter(is_primary=True).first() or files.first()


def sync_media_file_links(
    media_file: MediaFile,
    media_items: Iterable[MediaItem],
    *,
    primary_item: MediaItem | None = None,
    prune: bool = False,
) -> None:
    if not media_file:
        return
    item_ids = [item.id for item in media_items if item and item.id]
    if not item_ids:
        return

    primary_id = primary_item.id if primary_item else None
    existing_links = list(
        MediaFileLink.objects.filter(media_file=media_file, media_item_id__in=item_ids)
    )
    existing_ids = {link.media_item_id for link in existing_links}
    to_create = []
    for item_id in item_ids:
        if item_id in existing_ids:
            continue
        to_create.append(
            MediaFileLink(
                media_file=media_file,
                media_item_id=item_id,
                is_primary=item_id == primary_id,
            )
        )
    if to_create:
        MediaFileLink.objects.bulk_create(to_create)

    if primary_id:
        MediaFileLink.objects.filter(
            media_file=media_file,
            media_item_id=primary_id,
        ).update(is_primary=True)
        MediaFileLink.objects.filter(media_file=media_file).exclude(
            media_item_id=primary_id
        ).update(is_primary=False)

    if prune:
        MediaFileLink.objects.filter(media_file=media_file).exclude(
            media_item_id__in=item_ids
        ).delete()
