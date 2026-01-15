#!/bin/bash
#
# Release script for stkai-sdk
#
# Usage:
#   ./scripts/release.sh [major|minor|patch]
#
# Default: patch
#
# Examples:
#   ./scripts/release.sh         # 0.2.4 → 0.2.5
#   ./scripts/release.sh patch   # 0.2.4 → 0.2.5
#   ./scripts/release.sh minor   # 0.2.4 → 0.3.0
#   ./scripts/release.sh major   # 0.2.4 → 1.0.0
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print colored message
info() { echo -e "${BLUE}ℹ${NC} $1"; }
success() { echo -e "${GREEN}✓${NC} $1"; }
warning() { echo -e "${YELLOW}⚠${NC} $1"; }
error() { echo -e "${RED}✗${NC} $1"; exit 1; }

# Show help
show_help() {
    echo "Usage: $0 [OPTIONS] [major|minor|patch]"
    echo ""
    echo "Bump version, commit, tag, and push to trigger release."
    echo ""
    echo "Arguments:"
    echo "  major    Bump major version (0.2.4 → 1.0.0)"
    echo "  minor    Bump minor version (0.2.4 → 0.3.0)"
    echo "  patch    Bump patch version (0.2.4 → 0.2.5) [default]"
    echo ""
    echo "Options:"
    echo "  -h, --help    Show this help message"
    echo "  -n, --dry-run Simulate release without making changes"
    echo ""
    echo "Examples:"
    echo "  $0            # Bump patch version"
    echo "  $0 minor      # Bump minor version"
    echo "  $0 major      # Bump major version"
    echo "  $0 --dry-run  # Simulate patch release"
}

# Parse arguments
DRY_RUN=false
BUMP_TYPE="patch"

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            show_help
            exit 0
            ;;
        -n|--dry-run)
            DRY_RUN=true
            shift
            ;;
        major|minor|patch)
            BUMP_TYPE="$1"
            shift
            ;;
        *)
            error "Invalid argument: '$1'. Use --help for usage."
            ;;
    esac
done

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PYPROJECT_FILE="$PROJECT_ROOT/pyproject.toml"

# Change to project root
cd "$PROJECT_ROOT"

if [[ "$DRY_RUN" == true ]]; then
    echo ""
    echo -e "${YELLOW}🔍 DRY-RUN MODE - No changes will be made${NC}"
    echo ""
fi

info "Starting release process..."

# ============================================
# Validations
# ============================================

# Check if pyproject.toml exists
if [[ ! -f "$PYPROJECT_FILE" ]]; then
    error "pyproject.toml not found at $PYPROJECT_FILE"
fi

# Check if on main branch
CURRENT_BRANCH=$(git branch --show-current)
if [[ "$CURRENT_BRANCH" != "main" ]]; then
    error "Must be on 'main' branch. Current branch: '$CURRENT_BRANCH'"
fi
success "On branch 'main'"

# Check for uncommitted changes
if [[ -n $(git status --porcelain) ]]; then
    error "Working directory has uncommitted changes. Commit or stash them first."
fi
success "Working directory is clean"

# Fetch latest from remote
info "Fetching latest from remote..."
git fetch origin main --quiet

# Check if local is up to date with remote
LOCAL_COMMIT=$(git rev-parse HEAD)
REMOTE_COMMIT=$(git rev-parse origin/main)

if [[ "$LOCAL_COMMIT" != "$REMOTE_COMMIT" ]]; then
    error "Local branch is not up to date with origin/main. Pull or push first."
fi
success "Local branch is up to date with remote"

# ============================================
# Version calculation
# ============================================

# Extract current version from pyproject.toml
CURRENT_VERSION=$(grep -E '^version\s*=' "$PYPROJECT_FILE" | head -1 | sed 's/.*"\(.*\)".*/\1/')

if [[ -z "$CURRENT_VERSION" ]]; then
    error "Could not extract version from pyproject.toml"
fi

info "Current version: $CURRENT_VERSION"

# Parse version components
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"

# Calculate new version
case "$BUMP_TYPE" in
    major)
        NEW_MAJOR=$((MAJOR + 1))
        NEW_MINOR=0
        NEW_PATCH=0
        ;;
    minor)
        NEW_MAJOR=$MAJOR
        NEW_MINOR=$((MINOR + 1))
        NEW_PATCH=0
        ;;
    patch)
        NEW_MAJOR=$MAJOR
        NEW_MINOR=$MINOR
        NEW_PATCH=$((PATCH + 1))
        ;;
esac

NEW_VERSION="${NEW_MAJOR}.${NEW_MINOR}.${NEW_PATCH}"
TAG_NAME="v${NEW_VERSION}"

info "New version: $NEW_VERSION ($BUMP_TYPE bump)"

# Check if tag already exists
if git rev-parse "$TAG_NAME" >/dev/null 2>&1; then
    error "Tag '$TAG_NAME' already exists!"
fi

# ============================================
# Confirmation
# ============================================

echo ""
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
if [[ "$DRY_RUN" == true ]]; then
    echo -e "${YELLOW}  Release Summary (DRY-RUN)${NC}"
else
    echo -e "${YELLOW}  Release Summary${NC}"
fi
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  Bump type:       $BUMP_TYPE"
echo "  Current version: $CURRENT_VERSION"
echo "  New version:     $NEW_VERSION"
echo "  Tag:             $TAG_NAME"
echo ""
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# In dry-run mode, show what would happen and exit
if [[ "$DRY_RUN" == true ]]; then
    echo -e "${BLUE}Would execute the following steps:${NC}"
    echo "  1. Update pyproject.toml: version = \"$CURRENT_VERSION\" → \"$NEW_VERSION\""
    echo "  2. Create commit: \"release new version v${NEW_VERSION};\""
    echo "  3. Create tag: $TAG_NAME"
    echo "  4. Push commit to origin/main"
    echo "  5. Push tag $TAG_NAME to origin"
    echo ""
    success "Dry-run completed. No changes were made."
    exit 0
fi

read -p "Proceed with release? [y/N] " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    warning "Release cancelled."
    exit 0
fi

# ============================================
# Release
# ============================================

echo ""
info "Updating pyproject.toml..."

# Update version in pyproject.toml
sed -i.bak "s/^version = \"${CURRENT_VERSION}\"/version = \"${NEW_VERSION}\"/" "$PYPROJECT_FILE"
rm -f "${PYPROJECT_FILE}.bak"

success "Updated version to $NEW_VERSION"

info "Creating commit..."
git add "$PYPROJECT_FILE"
git commit -m "release new version v${NEW_VERSION};"
success "Created commit"

info "Creating tag '$TAG_NAME'..."
git tag "$TAG_NAME"
success "Created tag"

info "Pushing to remote..."
git push origin main
git push origin "$TAG_NAME"
success "Pushed commit and tag to remote"

# ============================================
# Done
# ============================================

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  Release v${NEW_VERSION} completed successfully!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  GitHub Actions will now:"
echo "    1. Run tests"
echo "    2. Build package"
echo "    3. Publish to PyPI"
echo ""
echo "  Monitor progress at:"
echo "    https://github.com/rafaelpontezup/stkai-sdk/actions"
echo ""
