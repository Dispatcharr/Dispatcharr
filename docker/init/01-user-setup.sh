#!/bin/bash

# Set up user details
export PUID=${PUID:-1000}
export PGID=${PGID:-1000}

# Check if group with PGID exists
if getent group "$PGID" >/dev/null 2>&1; then
    # Group exists, check if it's named correctly (should match POSTGRES_USER)
    existing_group=$(getent group "$PGID" | cut -d: -f1)
    if [ "$existing_group" != "$POSTGRES_USER" ]; then
        # Rename the existing group to match POSTGRES_USER
        groupmod -n "$POSTGRES_USER" "$existing_group"
        echo "Group $existing_group with GID $PGID renamed to $POSTGRES_USER"
    fi
else
    # Group doesn't exist, create it with same name as POSTGRES_USER
    groupadd -g "$PGID" "$POSTGRES_USER"
    echo "Group $POSTGRES_USER with GID $PGID created"
fi

# Create user if it doesn't exist
if ! getent passwd $PUID > /dev/null 2>&1; then
    useradd -u $PUID -g $PGID -m $POSTGRES_USER
else
    existing_user=$(getent passwd $PUID | cut -d: -f1)
    if [ "$existing_user" != "$POSTGRES_USER" ]; then
        usermod -l $POSTGRES_USER -g $PGID "$existing_user"
    fi
fi

# Get the GID of /dev/dri/renderD128 on the host (must be mounted into container)
if [ -e "/dev/dri/renderD128" ]; then
    HOST_RENDER_GID=$(stat -c '%g' /dev/dri/renderD128)

    # Check if this GID belongs to the video group
    VIDEO_GID=$(getent group video 2>/dev/null | cut -d: -f3)

    if [ "$HOST_RENDER_GID" = "$VIDEO_GID" ]; then
        echo "RenderD128 GID ($HOST_RENDER_GID) matches video group GID. Using video group for GPU access."
        # Make sure POSTGRES_USER is in video group
        if ! id -nG "$POSTGRES_USER" | grep -qw "video"; then
            usermod -a -G video "$POSTGRES_USER"
            echo "Added user $POSTGRES_USER to video group for GPU access"
        fi
    else
        # We need to ensure render group exists with correct GID
        if getent group render >/dev/null; then
            CURRENT_RENDER_GID=$(getent group render | cut -d: -f3)
            if [ "$CURRENT_RENDER_GID" != "$HOST_RENDER_GID" ]; then
                # Check if another group already has the target GID
                if getent group "$HOST_RENDER_GID" >/dev/null 2>&1; then
                    EXISTING_GROUP=$(getent group "$HOST_RENDER_GID" | cut -d: -f1)
                    echo "Warning: Cannot change render group GID to $HOST_RENDER_GID as it's already used by group '$EXISTING_GROUP'"
                    # Add user to the existing group with the target GID to ensure device access
                    if ! id -nG "$POSTGRES_USER" | grep -qw "$EXISTING_GROUP"; then
                        usermod -a -G "$EXISTING_GROUP" "$POSTGRES_USER" || echo "Warning: Failed to add user to $EXISTING_GROUP group"
                        echo "Added user $POSTGRES_USER to $EXISTING_GROUP group for GPU access"
                    fi
                else
                    echo "Changing render group GID from $CURRENT_RENDER_GID to $HOST_RENDER_GID"
                    groupmod -g "$HOST_RENDER_GID" render || echo "Warning: Failed to change render group GID. Continuing anyway..."
                fi
            fi
        else
            echo "Creating render group with GID $HOST_RENDER_GID"
            groupadd -g "$HOST_RENDER_GID" render
        fi

        # Make sure POSTGRES_USER is in render group
        if ! id -nG "$POSTGRES_USER" | grep -qw "render"; then
            usermod -a -G render "$POSTGRES_USER"
            echo "Added user $POSTGRES_USER to render group for GPU access"
        fi
    fi
else
    echo "Warning: /dev/dri/renderD128 not found. GPU acceleration may not be available."
fi

# Always add user to video group for hardware acceleration if it exists
# (some systems use video group for general GPU access)
if getent group video >/dev/null 2>&1; then
    if ! id -nG "$POSTGRES_USER" | grep -qw "video"; then
        usermod -a -G video "$POSTGRES_USER"
        echo "Added user $POSTGRES_USER to video group for hardware acceleration access"
    fi
fi

# Run nginx as specified user (replace any existing user directive on line 1)
sed -i "1s/^user .*/user $POSTGRES_USER;/" /etc/nginx/nginx.conf
