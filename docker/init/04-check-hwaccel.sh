#!/bin/bash

echo "🔍 Checking for GPU acceleration devices..."

# Helper function for device access checks
check_dev() {
    local dev=$1
    if [ -e "$dev" ]; then
        if [ -r "$dev" ] && [ -w "$dev" ]; then
            echo "✅ Device $dev is accessible."
        else
            echo "⚠️ Device $dev exists but is not accessible. Check permissions or container runtime options."
        fi
    else
        echo "ℹ️ Device $dev does not exist."
    fi
}

# Initialize device detection flags
ANY_GPU_DEVICES_FOUND=false
DRI_DEVICES_FOUND=false
NVIDIA_FOUND=false
NVIDIA_GPU_IN_LSPCI=false
INTEL_GPU_IN_LSPCI=false
AMD_GPU_IN_LSPCI=false

# Check for all GPU types in hardware via lspci
if command -v lspci >/dev/null 2>&1; then
    # Check for NVIDIA GPUs
    if lspci | grep -i "NVIDIA" | grep -i "VGA\|3D\|Display" >/dev/null; then
        NVIDIA_GPU_IN_LSPCI=true
        NVIDIA_MODEL=$(lspci | grep -i "NVIDIA" | grep -i "VGA\|3D\|Display" | head -1 | sed -E 's/.*: (.*) \[.*/\1/' | sed 's/Corporation //')
    fi

    # Check for Intel GPUs - making sure it's not already detected as NVIDIA
    if lspci | grep -i "Intel" | grep -v "NVIDIA" | grep -i "VGA\|3D\|Display" >/dev/null; then
        INTEL_GPU_IN_LSPCI=true
        INTEL_MODEL=$(lspci | grep -i "Intel" | grep -v "NVIDIA" | grep -i "VGA\|3D\|Display" | head -1 | sed -E 's/.*: (.*) \[.*/\1/' | sed 's/Corporation //')
    fi

    # Check for AMD GPUs - making sure it's not already detected as NVIDIA or Intel
    if lspci | grep -i "AMD\|ATI\|Advanced Micro Devices" | grep -v "NVIDIA\|Intel" | grep -i "VGA\|3D\|Display" >/dev/null; then
        AMD_GPU_IN_LSPCI=true
        AMD_MODEL=$(lspci | grep -i "AMD\|ATI\|Advanced Micro Devices" | grep -v "NVIDIA\|Intel" | grep -i "VGA\|3D\|Display" | head -1 | sed -E 's/.*: (.*) \[.*/\1/' | sed 's/Corporation //' | sed 's/Technologies //')
    fi

    # Display detected GPU hardware
    if [ "$NVIDIA_GPU_IN_LSPCI" = true ]; then
        echo "🔍 Hardware detection: NVIDIA GPU ($NVIDIA_MODEL)"
    fi
    if [ "$INTEL_GPU_IN_LSPCI" = true ]; then
        echo "🔍 Hardware detection: Intel GPU ($INTEL_MODEL)"
    fi
    if [ "$AMD_GPU_IN_LSPCI" = true ]; then
        echo "🔍 Hardware detection: AMD GPU ($AMD_MODEL)"
    fi
fi

# Silently check for any GPU devices first
for dev in /dev/dri/renderD* /dev/dri/card* /dev/nvidia*; do
    if [ -e "$dev" ]; then
        ANY_GPU_DEVICES_FOUND=true
        break
    fi
done

# Only if devices might exist, show detailed checks
if [ "$ANY_GPU_DEVICES_FOUND" = true ]; then
    # Check Intel/AMD VAAPI devices
    echo "🔍 Checking for VAAPI device nodes (Intel/AMD)..."
    for dev in /dev/dri/renderD* /dev/dri/card*; do
        if [ -e "$dev" ]; then
            DRI_DEVICES_FOUND=true
            check_dev "$dev"
        fi
    done

    # Check NVIDIA device nodes
    echo "🔍 Checking for NVIDIA device nodes..."
    for dev in /dev/nvidia*; do
        if [ -e "$dev" ]; then
            NVIDIA_FOUND=true
            check_dev "$dev"
        fi
    done

    # Show GPU device availability messages
    if [ "$NVIDIA_FOUND" = false ] && [ "$NVIDIA_GPU_IN_LSPCI" = true ]; then
        echo "⚠️ No NVIDIA device nodes available despite hardware detection."
        echo "   You may be able to use VAAPI for hardware acceleration, but NVENC/CUDA won't be available."
        echo "   For optimal performance, configure proper NVIDIA container runtime."
    elif [ "$NVIDIA_FOUND" = false ]; then
        echo "ℹ️ No NVIDIA device nodes found under /dev."
    fi

    # Check for Intel/AMD GPUs that might not be fully accessible
    if [ "$DRI_DEVICES_FOUND" = false ] && [ "$INTEL_GPU_IN_LSPCI" = true ]; then
        echo "⚠️ Intel GPU detected in hardware but no DRI devices found."
        echo "   Hardware acceleration will not be available."
        echo "   Make sure /dev/dri/ devices are properly mapped to the container."
    elif [ "$DRI_DEVICES_FOUND" = false ] && [ "$AMD_GPU_IN_LSPCI" = true ]; then
        echo "⚠️ AMD GPU detected in hardware but no DRI devices found."
        echo "   Hardware acceleration will not be available."
        echo "   Make sure /dev/dri/ devices are properly mapped to the container."
    fi
else
    # No GPU devices found, skip the detailed checks
    echo "❌ No GPU acceleration devices detected in this container."
    echo "ℹ️ Checking for potential configuration issues..."

    # Check if the host might have GPUs that aren't passed to the container
    if command -v lspci >/dev/null 2>&1; then
        if lspci | grep -i "VGA\|3D\|Display" | grep -i "NVIDIA\|Intel\|AMD" >/dev/null; then
            echo "⚠️ Host system appears to have GPU hardware, but no devices are accessible to the container."
            echo "   - For NVIDIA GPUs: Ensure NVIDIA Container Runtime is configured properly"
            echo "   - For Intel/AMD GPUs: Verify that /dev/dri/ devices are passed to the container"
            echo "   - Check your Docker run command or docker-compose.yml for proper device mapping"
        else
            echo "ℹ️ No GPU hardware detected on the host system. CPU-only transcoding will be used."
        fi
    else
        echo "ℹ️ Unable to check host GPU hardware (lspci not available). CPU-only transcoding will be used."
    fi

    echo "📋 =================================================="
    echo "✅ GPU detection script complete. No GPUs available for hardware acceleration."
    # Don't exit the container - just return from this script
    return 0 2>/dev/null || true
fi

# Check group membership for GPU access - context-aware based on hardware
echo "🔍 Checking user group memberships and device access..."
VIDEO_GID=$(getent group video | cut -d: -f3)
RENDER_GID=$(getent group render | cut -d: -f3)
NVIDIA_CONTAINER_TOOLKIT_FOUND=false
NVIDIA_ENV_MISMATCH=false

# Improved device access check function
check_user_device_access() {
    local device=$1
    local user=$2
    if [ -e "$device" ];then
        if su -c "test -r '$device' && test -w '$device'" - "$user" 2>/dev/null; then
            echo "✅ User $user has full access to $device"
            return 0
        else
            echo "⚠️ User $user cannot access $device (permission denied)"
            return 1
        fi
    else
        # Device doesn't exist, no need to report here
        return 2
    fi
}

# Direct device access verification for DRI (Intel/AMD)
echo "🔍 Verifying if $POSTGRES_USER has direct access to GPU devices..."
HAS_DRI_ACCESS=false
DRI_ACCESS_COUNT=0
DRI_DEVICE_COUNT=0

for dev in /dev/dri/renderD* /dev/dri/card*; do
    if [ -e "$dev" ]; then
        DRI_DEVICE_COUNT=$((DRI_DEVICE_COUNT + 1))
        if check_user_device_access "$dev" "$POSTGRES_USER"; then
            DRI_ACCESS_COUNT=$((DRI_ACCESS_COUNT + 1))
            HAS_DRI_ACCESS=true
        fi
    fi
done

# Direct device access verification for NVIDIA
HAS_NVIDIA_ACCESS=false
NVIDIA_ACCESS_COUNT=0
NVIDIA_DEVICE_COUNT=0

for dev in /dev/nvidia*; do
    if [ -e "$dev" ]; then
        NVIDIA_DEVICE_COUNT=$((NVIDIA_DEVICE_COUNT + 1))
        if check_user_device_access "$dev" "$POSTGRES_USER"; then
            NVIDIA_ACCESS_COUNT=$((NVIDIA_ACCESS_COUNT + 1))
            HAS_NVIDIA_ACCESS=true
        fi
    fi
done

# Summary of device access
if [ $DRI_DEVICE_COUNT -gt 0 ]; then
    if [ $DRI_ACCESS_COUNT -eq $DRI_DEVICE_COUNT ]; then
        echo "✅ User $POSTGRES_USER has access to all DRI devices ($DRI_ACCESS_COUNT/$DRI_DEVICE_COUNT)"
        echo "   VAAPI hardware acceleration should work properly."
    else
        echo "⚠️ User $POSTGRES_USER has limited access to DRI devices ($DRI_ACCESS_COUNT/$DRI_DEVICE_COUNT)"
        echo "   VAAPI hardware acceleration may not work properly."
        echo "   Consider adding $POSTGRES_USER to the 'video' and/or 'render' groups."
    fi
fi

if [ $NVIDIA_DEVICE_COUNT -gt 0 ]; then
    if [ $NVIDIA_ACCESS_COUNT -eq $NVIDIA_DEVICE_COUNT ]; then
        echo "✅ User $POSTGRES_USER has access to all NVIDIA devices ($NVIDIA_ACCESS_COUNT/$NVIDIA_DEVICE_COUNT)"
        echo "   NVIDIA hardware acceleration should work properly."
    else
        echo "⚠️ User $POSTGRES_USER has limited access to NVIDIA devices ($NVIDIA_ACCESS_COUNT/$NVIDIA_DEVICE_COUNT)"
        echo "   NVIDIA hardware acceleration may not work properly."
        if [ "$NVIDIA_CONTAINER_TOOLKIT_FOUND" = false ]; then
            echo "   Consider adding $POSTGRES_USER to the 'video' group or use NVIDIA Container Toolkit."
        fi
    fi
fi

# Check for traditional group memberships (as additional information)
USER_IN_VIDEO_GROUP=false
USER_IN_RENDER_GROUP=false

if [ -n "$VIDEO_GID" ]; then
    if id -nG "$POSTGRES_USER" 2>/dev/null | grep -qw "video"; then
        USER_IN_VIDEO_GROUP=true
        echo "ℹ️ User $POSTGRES_USER is in the 'video' group (GID $VIDEO_GID)."
    fi
fi

if [ -n "$RENDER_GID" ]; then
    if id -nG "$POSTGRES_USER" 2>/dev/null | grep -qw "render"; then
        USER_IN_RENDER_GROUP=true
        echo "ℹ️ User $POSTGRES_USER is in the 'render' group (GID $RENDER_GID)."
    fi
fi

# Check if NVIDIA Container Toolkit is present through environment or CLI tool
# IMPORTANT: Only mark as found if both env vars AND actual NVIDIA devices exist
if [ "$NVIDIA_FOUND" = true ] && command -v nvidia-container-cli >/dev/null 2>&1; then
    NVIDIA_CONTAINER_TOOLKIT_FOUND=true
# Check for environment variables set by NVIDIA Container Runtime, but only if NVIDIA hardware exists
elif [ "$NVIDIA_FOUND" = true ] && [ -n "$NVIDIA_VISIBLE_DEVICES" ] && [ -n "$NVIDIA_DRIVER_CAPABILITIES" ]; then
    NVIDIA_CONTAINER_TOOLKIT_FOUND=true
    echo "✅ NVIDIA Container Toolkit detected (via environment variables)."
    echo "   The container is properly configured with Docker Compose's 'driver: nvidia' syntax."
elif [ -n "$NVIDIA_VISIBLE_DEVICES" ] && [ -n "$NVIDIA_DRIVER_CAPABILITIES" ] && [ "$NVIDIA_FOUND" = false ]; then
    NVIDIA_ENV_MISMATCH=true
fi

# Removed duplicate video group checks here - consolidated into the earlier checks that include GID

# Check NVIDIA Container Toolkit support
echo "🔍 Checking NVIDIA container runtime support..."

# More reliable detection of NVIDIA Container Runtime
NVIDIA_RUNTIME_ACTIVE=false

# Method 1: Check for nvidia-container-cli tool
if command -v nvidia-container-cli >/dev/null 2>&1; then
    NVIDIA_RUNTIME_ACTIVE=true
    echo "✅ NVIDIA Container Runtime detected (nvidia-container-cli found)."

    if nvidia-container-cli info >/dev/null 2>&1; then
        echo "✅ NVIDIA container runtime is functional."
    else
        echo "⚠️ nvidia-container-cli found, but 'info' command failed. Runtime may be misconfigured."
    fi
fi

# Method 2: Check for NVIDIA Container Runtime specific files
if [ -e "/dev/.nv" ] || [ -e "/.nv" ] || [ -e "/.nvidia-container-runtime" ]; then
    NVIDIA_RUNTIME_ACTIVE=true
    echo "✅ NVIDIA Container Runtime files detected."
fi

# Method 3: Check cgroup information for NVIDIA
if grep -q "nvidia" /proc/self/cgroup 2>/dev/null; then
    NVIDIA_RUNTIME_ACTIVE=true
    echo "✅ NVIDIA Container Runtime cgroups detected."
fi

# Final verdict based on hardware AND runtime with improved messaging
if [ "$NVIDIA_FOUND" = true ] && ([ "$NVIDIA_RUNTIME_ACTIVE" = true ] || [ "$NVIDIA_CONTAINER_TOOLKIT_FOUND" = true ]); then
    echo "✅ NVIDIA Container Runtime is properly configured with hardware access."
elif [ "$NVIDIA_FOUND" = true ] && [ "$NVIDIA_RUNTIME_ACTIVE" = false ] && [ "$NVIDIA_CONTAINER_TOOLKIT_FOUND" = false ]; then
    echo "ℹ️ NVIDIA devices accessible via direct passthrough instead of Container Runtime."
    echo "   This works but consider using the 'deploy: resources: reservations: devices:' method in docker-compose."
elif [ "$NVIDIA_FOUND" = false ] && [ "$NVIDIA_RUNTIME_ACTIVE" = true ]; then
    echo "⚠️ NVIDIA Container Runtime appears to be configured, but no NVIDIA devices found."
    echo "   Check that your host has NVIDIA drivers installed and GPUs are properly passed to the container."
elif [ "$DRI_DEVICES_FOUND" = true ] && [ "$NVIDIA_GPU_IN_LSPCI" = true ]; then
    echo "ℹ️ Limited GPU access: Only DRI devices available for NVIDIA hardware."
    echo "   VAAPI acceleration may work but NVENC/CUDA won't be available."
    echo "   For full NVIDIA capabilities, configure the NVIDIA Container Runtime."
elif [ "$DRI_DEVICES_FOUND" = true ]; then
    echo "ℹ️ Using Intel/AMD GPU hardware for acceleration via VAAPI."
else
    echo "⚠️ No GPU acceleration devices detected. CPU-only transcoding will be used."
fi

# Run nvidia-smi if available
if command -v nvidia-smi >/dev/null 2>&1; then
    echo "🔍 Running nvidia-smi to verify GPU visibility..."
    if nvidia-smi >/dev/null 2>&1; then
        echo "✅ nvidia-smi successful - GPU is accessible to container!"
        echo "   This confirms hardware acceleration should be available to FFmpeg."
    else
        echo "⚠️ nvidia-smi command failed. GPU may not be properly mapped into container."
    fi
else
    echo "ℹ️ nvidia-smi not installed or not in PATH."
fi

# Show relevant environment variables with contextual suggestions
echo "🔍 Checking GPU-related environment variables..."

# Set flags based on device detection
DRI_DEVICES_FOUND=false
for dev in /dev/dri/renderD* /dev/dri/card*; do
    if [ -e "$dev" ];then
        DRI_DEVICES_FOUND=true
        break
    fi
done

# Give contextual suggestions based on detected hardware
if [ "$DRI_DEVICES_FOUND" = true ]; then
    # Detect Intel/AMD GPU model - skip this if we already detected GPUs earlier
    if [ "$NVIDIA_GPU_IN_LSPCI" = false ] && [ "$INTEL_GPU_IN_LSPCI" = false ] && [ "$AMD_GPU_IN_LSPCI" = false ] && command -v lspci >/dev/null 2>&1; then
        GPU_INFO=$(lspci -nn | grep -i "VGA\|Display" | head -1)
        if [ -n "$GPU_INFO" ]; then
            echo "🔍 Detected GPU: $GPU_INFO"
            # Extract model for cleaner display in summary
            GPU_MODEL=$(echo "$GPU_INFO" | sed -E 's/.*: (.*) \[.*/\1/' | sed 's/Corporation //' | sed 's/Technologies //')
        fi
    else
        # Use already detected GPU model info
        if [ "$NVIDIA_GPU_IN_LSPCI" = true ]; then
            GPU_MODEL=$NVIDIA_MODEL
        elif [ "$INTEL_GPU_IN_LSPCI" = true ]; then
            GPU_MODEL=$INTEL_MODEL
        elif [ "$AMD_GPU_IN_LSPCI" = true ]; then
            GPU_MODEL=$AMD_MODEL
        fi
    fi

    if [ -n "$GPU_MODEL" ]; then
        echo "🔍 GPU model: $GPU_MODEL"
    fi
    # Check for LIBVA_DRIVER_NAME environment variable
    if [ -n "$LIBVA_DRIVER_NAME" ]; then
        echo "ℹ️ LIBVA_DRIVER_NAME is set to '$LIBVA_DRIVER_NAME'"
        echo "   Note: If you experience issues with hardware acceleration, try removing this"
        echo "   environment variable to let the system auto-detect the appropriate driver."
    else
        # Check if we can detect the GPU type
        if command -v lspci >/dev/null 2>&1; then
            echo "ℹ️ VAAPI driver auto-detection is usually reliable. Settings below only needed if you experience issues."

            # Create variables to store recommended driver and supported methods
            INTEL_RECOMMENDED_DRIVER=""
            INTEL_SUPPORTS_QSV=false

            # Use the Intel model information we already captured
            if [ "$INTEL_GPU_IN_LSPCI" = true ] && [ -n "$INTEL_MODEL" ]; then
                # Check for newer Intel generations that use iHD
                if echo "$INTEL_MODEL" | grep -q -E "Arc|Xe|Alchemist|Tiger|Alder|Raptor|Meteor|Gen1[2-9]"; then
                    echo "💡 Detected Intel GPU that supports iHD (e.g. Gen12+/Arc/Xe)"
                    echo "   Recommended: LIBVA_DRIVER_NAME=iHD"
                    echo "   Note: Only set this environment variable if hardware acceleration doesn't work by default"
                    INTEL_RECOMMENDED_DRIVER="iHD"
                    INTEL_SUPPORTS_QSV=true
                elif echo "$INTEL_MODEL" | grep -q -E "Coffee|Whiskey|Comet|Gen11"; then
                    echo "💡 Detected Intel GPU that supports both i965 and iHD (e.g. Gen9.5/Gen11)"
                    echo "   Preferred: LIBVA_DRIVER_NAME=iHD"
                    echo "   Recommended: Try i965 only if iHD has compatibility issues"
                    echo "   Note: Only set this environment variable if hardware acceleration doesn't work by default"
                    INTEL_RECOMMENDED_DRIVER="iHD"
                    INTEL_SUPPORTS_QSV=true
                elif echo "$INTEL_MODEL" | grep -q -E "Haswell|Broadwell|Skylake|Kaby"; then
                    echo "💡 Detected Intel GPU that supports i965 (e.g. Gen9 and below)"
                    echo "   Recommended: Set LIBVA_DRIVER_NAME=i965"
                    echo "   Note: Only set this environment variable if hardware acceleration doesn't work by default"
                    INTEL_RECOMMENDED_DRIVER="i965"
                    # Older Intel GPUs support QSV through i965 driver but with more limitations
                    INTEL_SUPPORTS_QSV=false
                else
                    # Generic Intel case - we're not fully confident in our recommendation
                    echo "💡 Unable to definitively identify Intel GPU generation"
                    echo "   Try auto-detection first (no environment variable)"
                    echo "   If issues occur: Try LIBVA_DRIVER_NAME=iHD first (newer GPUs)"
                    echo "   If that fails: Try LIBVA_DRIVER_NAME=i965 (older GPUs)"
                    INTEL_RECOMMENDED_DRIVER="unknown" # Mark as unknown rather than assuming
                    INTEL_SUPPORTS_QSV="maybe" # Mark as maybe instead of assuming true
                fi
            elif [ "$AMD_GPU_IN_LSPCI" = true ]; then
                echo "💡 If auto-detection fails: Set LIBVA_DRIVER_NAME=radeonsi for AMD GPUs"
                echo "   Note: Only set this environment variable if hardware acceleration doesn't work by default"
            else
                echo "ℹ️ Common VAAPI driver options if auto-detection fails:"
                echo "   - For modern Intel GPUs (Gen12+/Arc/Xe): LIBVA_DRIVER_NAME=iHD"
                echo "   - For older Intel GPUs: LIBVA_DRIVER_NAME=i965"
                echo "   - For AMD GPUs: LIBVA_DRIVER_NAME=radeonsi"
                echo "   Note: Only set these environment variables if hardware acceleration doesn't work by default"
            fi
        else
            echo "ℹ️ Intel/AMD GPU detected. Auto-detection should work in most cases."
            echo "   If VAAPI doesn't work, you may need to set LIBVA_DRIVER_NAME manually."
        fi
    fi
fi

# Check FFmpeg hardware acceleration support
echo "🔍 Checking FFmpeg hardware acceleration capabilities..."
if command -v ffmpeg >/dev/null 2>&1; then
    HWACCEL=$(ffmpeg -hide_banner -hwaccels 2>/dev/null | grep -v "Hardware acceleration methods:" || echo "None found")

    # Initialize variables to store compatible and missing methods
    COMPATIBLE_METHODS=""
    MISSING_METHODS=""

    # Format the list of hardware acceleration methods in a more readable way
    echo "🔍 Available FFmpeg hardware acceleration methods:"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # Process the list into a more readable format with relevance indicators
    if [ -n "$HWACCEL" ] && [ "$HWACCEL" != "None found" ]; then
        # First, show methods compatible with detected hardware
        echo "  📌 Compatible with your hardware:"
        COMPATIBLE_FOUND=false

        for method in $HWACCEL; do
            # Skip if it's just the header line or empty
            if [ "$method" = "Hardware" ] || [ -z "$method" ]; then
                continue
            fi

            # Check if this method is relevant to detected hardware
            IS_COMPATIBLE=false
            DESCRIPTION=""

            if [ "$NVIDIA_FOUND" = true ] && [[ "$method" =~ ^(cuda|cuvid|nvenc|nvdec)$ ]]; then
                IS_COMPATIBLE=true
                DESCRIPTION="NVIDIA GPU acceleration"
            elif [ "$INTEL_GPU_IN_LSPCI" = true ] && [ "$method" = "qsv" ] && [ "$INTEL_SUPPORTS_QSV" = true ]; then
                IS_COMPATIBLE=true
                DESCRIPTION="Intel QuickSync acceleration"
            elif [ "$method" = "vaapi" ] && (([ "$INTEL_GPU_IN_LSPCI" = true ] || [ "$AMD_GPU_IN_LSPCI" = true ]) && [ "$DRI_DEVICES_FOUND" = true ]); then
                IS_COMPATIBLE=true
                if [ "$INTEL_GPU_IN_LSPCI" = true ]; then
                    DESCRIPTION="Intel VAAPI acceleration"
                else
                    DESCRIPTION="AMD VAAPI acceleration"
                fi
            fi

            # Display compatible methods and store for summary
            if [ "$IS_COMPATIBLE" = true ]; then
                COMPATIBLE_FOUND=true
                COMPATIBLE_METHODS="$COMPATIBLE_METHODS $method"
                echo "    ✅ $method - $DESCRIPTION"
            fi
        done

        if [ "$COMPATIBLE_FOUND" = false ]; then
            echo "    ❌ No compatible acceleration methods found for your hardware"
        fi

        # Then show all other available methods
        echo "  📌 Other available methods (not compatible with detected hardware):"
        OTHER_FOUND=false

        for method in $HWACCEL; do
            # Skip if it's just the header line or empty
            if [ "$method" = "Hardware" ] || [ -z "$method" ]; then
                continue
            fi

            # Check if this method is relevant to detected hardware
            IS_COMPATIBLE=false

            if [ "$NVIDIA_FOUND" = true ] && [[ "$method" =~ ^(cuda|cuvid|nvenc|nvdec)$ ]]; then
                IS_COMPATIBLE=true
            elif [ "$INTEL_GPU_IN_LSPCI" = true ] && [ "$method" = "qsv" ] && [ "$INTEL_SUPPORTS_QSV" = true ]; then
                IS_COMPATIBLE=true
            elif [ "$method" = "vaapi" ] && (([ "$INTEL_GPU_IN_LSPCI" = true ] || [ "$AMD_GPU_IN_LSPCI" = true ]) && [ "$DRI_DEVICES_FOUND" = true ]); then
                IS_COMPATIBLE=true
            fi

            # Display other methods that aren't compatible
            if [ "$IS_COMPATIBLE" = false ]; then
                OTHER_FOUND=true
                echo "    ℹ️ $method"
            fi
        done

        if [ "$OTHER_FOUND" = false ]; then
            echo "    None"
        fi

        # Show expected methods that are missing
        echo "  📌 Missing methods that should be available for your hardware:"
        MISSING_FOUND=false

        # Check for NVIDIA methods if NVIDIA GPU is detected
        if [ "$NVIDIA_FOUND" = true ]; then
            EXPECTED_NVIDIA="cuda" # cuvid nvenc nvdec" keeping these in case future support is added
            for method in $EXPECTED_NVIDIA; do
                if ! echo "$HWACCEL" | grep -q "$method"; then
                    MISSING_FOUND=true
                    MISSING_METHODS="$MISSING_METHODS $method"
                    echo "    ⚠️ $method - NVIDIA acceleration (missing but should be available)"
                fi
            done
        fi

        # Check for Intel methods if Intel GPU is detected
        if [ "$INTEL_GPU_IN_LSPCI" = true ] && [ "$DRI_DEVICES_FOUND" = true ]; then
            if [ "$INTEL_SUPPORTS_QSV" = true ] && ! echo "$HWACCEL" | grep -q "qsv"; then
                MISSING_FOUND=true
                MISSING_METHODS="$MISSING_METHODS qsv"
                echo "    ⚠️ qsv - Intel QuickSync acceleration (missing but should be available)"
            fi

            if ! echo "$HWACCEL" | grep -q "vaapi"; then
                MISSING_FOUND=true
                MISSING_METHODS="$MISSING_METHODS vaapi"
                echo "    ⚠️ vaapi - Intel VAAPI acceleration (missing but should be available)"
            fi
        fi

        # Check for AMD methods if AMD GPU is detected
        if [ "$AMD_GPU_IN_LSPCI" = true ] && [ "$DRI_DEVICES_FOUND" = true ]; then
            if ! echo "$HWACCEL" | grep -q "vaapi"; then
                MISSING_FOUND=true
                MISSING_METHODS="$MISSING_METHODS vaapi"
                echo "    ⚠️ vaapi - AMD VAAPI acceleration (missing but should be available)"
            fi
        fi

        if [ "$MISSING_FOUND" = false ]; then
            echo "    None - All expected methods are available"
        fi
    else
        echo "  ❌ No hardware acceleration methods found"
    fi
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # Show hardware-appropriate method summary using the already gathered information
    if [ -n "$COMPATIBLE_METHODS" ]; then
        echo "✅ Hardware-appropriate acceleration methods available:$COMPATIBLE_METHODS"
    fi

    # Show missing expected methods
    if [ -n "$MISSING_METHODS" ]; then
        echo "⚠️ Expected acceleration methods not found:$MISSING_METHODS"
        echo "   This might indicate missing libraries or improper driver configuration."
    fi

    # Display specific cases of interest (simplify using previously captured information)
    if [ "$NVIDIA_FOUND" = true ] && ! echo "$COMPATIBLE_METHODS" | grep -q "cuda\|nvenc\|cuvid"; then
        echo "⚠️ NVIDIA GPU detected but no NVIDIA acceleration methods available."
        echo "   Ensure ffmpeg is built with NVIDIA support and required libraries are installed."
    fi

    if (([ "$INTEL_GPU_IN_LSPCI" = true ] || [ "$AMD_GPU_IN_LSPCI" = true ]) &&
        [ "$DRI_DEVICES_FOUND" = true ] && ! echo "$COMPATIBLE_METHODS" | grep -q "vaapi"); then
        echo "⚠️ Intel/AMD GPU detected but VAAPI acceleration not available."
        echo "   Ensure ffmpeg is built with VAAPI support and proper drivers are installed."
    fi
else
    echo "⚠️ FFmpeg not found in PATH."
fi

# Provide a final summary of the hardware acceleration setup
echo "📋 ===================== SUMMARY ====================="

# Identify which GPU type is active and working
if [ "$NVIDIA_FOUND" = true ] && (nvidia-smi >/dev/null 2>&1 || [ -n "$NVIDIA_VISIBLE_DEVICES" ]); then
    if [ -n "$NVIDIA_MODEL" ]; then
        echo "🔰 NVIDIA GPU: $NVIDIA_MODEL"
    else
        echo "🔰 NVIDIA GPU: ACTIVE (model detection unavailable)"
        echo "ℹ️ Note: GPU model information couldn't be retrieved, but devices are present."
        echo "   This may be due to missing nvidia-smi tool or container limitations."
    fi

    if [ "$NVIDIA_CONTAINER_TOOLKIT_FOUND" = true ]; then
        echo "✅ NVIDIA Container Toolkit: CONFIGURED CORRECTLY"
    elif [ -n "$NVIDIA_VISIBLE_DEVICES" ] && [ -n "$NVIDIA_DRIVER_CAPABILITIES" ]; then
        echo "✅ NVIDIA Docker configuration: USING MODERN DEPLOYMENT"
    else
        echo "⚠️ NVIDIA setup method: DIRECT DEVICE MAPPING (functional but not optimal)"
    fi

    # Add device accessibility status
    if [ $NVIDIA_DEVICE_COUNT -gt 0 ]; then
        if [ $NVIDIA_ACCESS_COUNT -eq $NVIDIA_DEVICE_COUNT ]; then
            echo "✅ Device access: ALL NVIDIA DEVICES ACCESSIBLE ($NVIDIA_ACCESS_COUNT/$NVIDIA_DEVICE_COUNT)"
        else
            echo "⚠️ Device access: LIMITED NVIDIA DEVICE ACCESS ($NVIDIA_ACCESS_COUNT/$NVIDIA_DEVICE_COUNT)"
            echo "   Some hardware acceleration features may not work properly."
        fi
    fi

    # Display FFmpeg NVIDIA acceleration methods in more detail
    if echo "$COMPATIBLE_METHODS" | grep -q "cuda\|nvenc\|cuvid"; then
        echo "✅ FFmpeg NVIDIA acceleration: AVAILABLE"

        # Show detailed breakdown of available NVIDIA methods
        NVIDIA_METHODS=$(echo "$COMPATIBLE_METHODS" | grep -o '\(cuda\|cuvid\|nvenc\|nvdec\)')
        echo "   Available NVIDIA methods: $NVIDIA_METHODS"
        echo "   Recommended for: Video transcoding with NVIDIA GPUs"
    else
        echo "⚠️ FFmpeg NVIDIA acceleration: NOT DETECTED"
        if [ -n "$MISSING_METHODS" ]; then
            echo "   Missing methods that should be available: $MISSING_METHODS"
        fi
    fi
elif [ "$NVIDIA_GPU_IN_LSPCI" = true ] && [ "$DRI_DEVICES_FOUND" = true ]; then
    # NVIDIA through DRI only (suboptimal but possible)
    if [ -n "$NVIDIA_MODEL" ]; then
        echo "🔰 NVIDIA GPU: $NVIDIA_MODEL (SUBOPTIMALLY CONFIGURED)"
    else
        echo "🔰 NVIDIA GPU: DETECTED BUT SUBOPTIMALLY CONFIGURED"
    fi
    echo "⚠️ Your NVIDIA GPU is only accessible through DRI devices"
    echo "   - VAAPI acceleration may work for some tasks"
    echo "   - NVENC/CUDA acceleration is NOT available"

    # Add device accessibility status
    if [ $DRI_DEVICE_COUNT -gt 0 ]; then
        if [ $DRI_ACCESS_COUNT -eq $DRI_DEVICE_COUNT ]; then
            echo "✅ Device access: ALL DRI DEVICES ACCESSIBLE ($DRI_ACCESS_COUNT/$DRI_DEVICE_COUNT)"
            echo "   VAAPI acceleration should work properly."
        else
            echo "⚠️ Device access: LIMITED DRI DEVICE ACCESS ($DRI_ACCESS_COUNT/$DRI_DEVICE_COUNT)"
            echo "   VAAPI acceleration may not work properly."
        fi
    fi

    echo "💡 RECOMMENDATION: Use the proper NVIDIA container configuration:"
    echo "    deploy:"
    echo "      resources:"
    echo "        reservations:"
    echo "          devices:"
    echo "            - driver: nvidia"
    echo "              count: all"
    echo "              capabilities: [gpu]"

    if echo "$COMPATIBLE_METHODS" | grep -q "vaapi"; then
        echo "✅ FFmpeg VAAPI acceleration: AVAILABLE (limited without NVENC)"
        echo "   VAAPI can be used for transcoding, but NVENC/CUDA would be more efficient"
    else
        echo "⚠️ FFmpeg VAAPI acceleration: NOT DETECTED"
    fi
elif [ "$DRI_DEVICES_FOUND" = true ]; then
    # Intel/AMD detection with model if available
    if [ -n "$GPU_MODEL" ]; then
        echo "🔰 GPU: $GPU_MODEL"
    elif [ -n "$LIBVA_DRIVER_NAME" ]; then
        echo "🔰 ${LIBVA_DRIVER_NAME^^} GPU: ACTIVE"
    else
        echo "🔰 INTEL/AMD GPU: ACTIVE (model detection unavailable)"
        echo "ℹ️ Note: Basic GPU drivers appear to be loaded (device nodes exist), but"
        echo "   couldn't identify specific model. This doesn't necessarily indicate a problem."
    fi

    # Add device accessibility status
    if [ $DRI_DEVICE_COUNT -gt 0 ]; then
        if [ $DRI_ACCESS_COUNT -eq $DRI_DEVICE_COUNT ]; then
            echo "✅ Device access: ALL DRI DEVICES ACCESSIBLE ($DRI_ACCESS_COUNT/$DRI_DEVICE_COUNT)"
            echo "   VAAPI hardware acceleration should work properly."
        else
            echo "⚠️ Device access: LIMITED DRI DEVICE ACCESS ($DRI_ACCESS_COUNT/$DRI_DEVICE_COUNT)"
            echo "   VAAPI hardware acceleration may not work properly."
        fi
    fi

    # Display FFmpeg VAAPI acceleration method with more details
    if echo "$COMPATIBLE_METHODS" | grep -q "vaapi"; then
        echo "✅ FFmpeg VAAPI acceleration: AVAILABLE"

        # Add recommended usage information
        echo "   Recommended for: General video transcoding with Intel/AMD GPUs"

        # Add recommended driver information for Intel GPUs
        if [ "$INTEL_GPU_IN_LSPCI" = true ] && [ -n "$INTEL_RECOMMENDED_DRIVER" ]; then
            if [ "$INTEL_RECOMMENDED_DRIVER" = "unknown" ]; then
                echo "ℹ️ Uncertain about recommended VAAPI driver for this Intel GPU"
                echo "   Auto-detection should work, but if issues occur try iHD or i965"
            else
                echo "ℹ️ Recommended VAAPI driver for this Intel GPU: $INTEL_RECOMMENDED_DRIVER"
            fi

            if [ "$INTEL_SUPPORTS_QSV" = true ] && echo "$COMPATIBLE_METHODS" | grep -q "qsv"; then
                echo "✅ QSV acceleration: AVAILABLE"
                echo "   Recommended for: Intel-specific optimized transcoding"
                echo "   Works best with: $INTEL_RECOMMENDED_DRIVER driver"
            elif [ "$INTEL_SUPPORTS_QSV" = true ]; then
                echo "ℹ️ QSV acceleration: NOT DETECTED (may be available with proper configuration)"
                echo "   Your Intel GPU supports QSV but it's not available in FFmpeg"
                echo "   Check if FFmpeg is built with QSV support"
            elif [ "$INTEL_SUPPORTS_QSV" = "maybe" ]; then
                echo "ℹ️ QSV acceleration: MAY BE AVAILABLE (depends on exact GPU model)"
            fi
        elif [ "$AMD_GPU_IN_LSPCI" = true ]; then
            echo "ℹ️ Recommended VAAPI driver for AMD GPUs: radeonsi"
        fi
    else
        echo "⚠️ FFmpeg VAAPI acceleration: NOT DETECTED"
        if [ -n "$MISSING_METHODS" ]; then
            echo "   Missing methods that should be available: $MISSING_METHODS"
        fi
    fi
else
    echo "❌ NO GPU ACCELERATION DETECTED"
    echo "⚠️ Hardware acceleration is unavailable or misconfigured"
fi

echo "📋 =================================================="
echo "✅ GPU detection script complete."
