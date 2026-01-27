#!/bin/bash

# Setup SSH user and keys based on environment variables
# Expected environment variables:
# - SSH_USER: Username for SSH access
# - SSH_PUBLIC_KEY: SSH public key to add to authorized_keys

set -e

if [ -n "$SSH_USER" ] && [ -n "$SSH_PUBLIC_KEY" ]; then
    echo "Setting up SSH access for user: $SSH_USER"
    
    # Create SSH user if it doesn't exist
    if ! getent passwd "$SSH_USER" > /dev/null 2>&1; then
        useradd -m -s /bin/bash "$SSH_USER"
        echo "Created user: $SSH_USER"
    fi
    
    # Create .ssh directory and set permissions
    SSH_HOME="/home/$SSH_USER"
    mkdir -p "$SSH_HOME/.ssh"
    
    # Add public key to authorized_keys
    echo "$SSH_PUBLIC_KEY" > "$SSH_HOME/.ssh/authorized_keys"
    
    # Set correct permissions
    chown -R "$SSH_USER:$SSH_USER" "$SSH_HOME/.ssh"
    chmod 700 "$SSH_HOME/.ssh"
    chmod 600 "$SSH_HOME/.ssh/authorized_keys"
    
    # Add user to dispatch group if it exists
    if getent group dispatch > /dev/null 2>&1; then
        usermod -a -G dispatch "$SSH_USER"
        echo "Added $SSH_USER to dispatch group"
    fi
    
    # Add user to sudo group for admin access
    usermod -a -G sudo "$SSH_USER"
    echo "Added $SSH_USER to sudo group"
    
    # Set a random password to unlock the account (password auth is disabled in SSH config)
    # This prevents "passwordless account" errors while keeping the account secure
    RANDOM_PASSWORD=$(openssl rand -base64 32)
    echo "$SSH_USER:$RANDOM_PASSWORD" | chpasswd
    echo "Account unlocked with secure random password (password auth disabled via SSH config)"

    echo "SSH access configured successfully for $SSH_USER"
else
    echo "SSH_USER and/or SSH_PUBLIC_KEY not provided - SSH access not configured"
fi

# Start SSH daemon
echo "Starting SSH daemon..."
service ssh start

echo "SSH setup completed"

ln -sf /proc/1/fd/1 /var/log/app.log
ln -sf /proc/1/fd/2 /var/log/app.err