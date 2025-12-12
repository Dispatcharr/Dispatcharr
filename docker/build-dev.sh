#!/bin/bash 
set -e

# Default values
VERSION=$(python3 -c "import sys; sys.path.append('..'); import version; print(version.__version__)")
REGISTRY="dispatcharr"        # Registry or private repo to push to
IMAGE="dispatcharr"           # Image that we're building
BRANCH="dev" 
ARCH=""                      # Architectures to build for, e.g. linux/amd64,linux/arm64
PUSH=false

usage() {
  cat <<- EOF
    To test locally:
      ./build-dev.sh 

    To build and push to registry:
      ./build-dev.sh -p

    To build and push to a private registry:
      ./build-dev.sh -p -r myregistry:5000

    To build for -both-  x86_64 and arm_64:
      ./build-dev.sh -p -a linux/amd64,linux/arm64

    Do it all:
      ./build-dev.sh -p -r myregistry:5000 -a linux/amd64,linux/arm64
EOF
exit 0
}

# Parse options
while getopts "pr:a:b:i:h" opt; do
  case $opt in
    r) REGISTRY="$OPTARG" ;;
    a) ARCH="--platform $OPTARG" ;;
    b) BRANCH="$OPTARG" ;;
    i) IMAGE="$OPTARG" ;;
    p) PUSH=true ;;
    h) usage ;;
    \?) echo "Invalid option: -$OPTARG" >&2; exit 1 ;;
  esac
done

BUILD_ARGS="BRANCH=$BRANCH"

echo docker build --build-arg $BUILD_ARGS $ARCH -t $IMAGE
docker build -f Dockerfile --build-arg $BUILD_ARGS $ARCH -t $IMAGE ..
docker tag $IMAGE $IMAGE:$BRANCH
docker tag $IMAGE $IMAGE:$VERSION

if [ -z "$PUSH" ]; then
  echo "Please run 'docker push -t $IMAGE:dev -t $IMAGE:${VERSION}' when ready"
else
  for TAG in latest "$VERSION" "$BRANCH"; do
    docker tag "$IMAGE" "$REGISTRY/$IMAGE:$TAG"
    docker push -q "$REGISTRY/$IMAGE:$TAG"
  done
  echo "Images pushed successfully."
fi





