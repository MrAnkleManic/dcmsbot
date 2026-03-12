#!/bin/bash
#
# Sync new/updated KB JSON files from BotCleaner output directory.
#
# Usage:
#   ./scripts/sync_from_botcleaner.sh /path/to/botcleaner/output
#   ./scripts/sync_from_botcleaner.sh /path/to/botcleaner/output --apply
#
# Steps:
#   1. Copy new/changed JSON files from BotCleaner output
#   2. Run text cleanup on new files
#   3. Run quality audit on new files
#   4. (Optionally) regenerate embeddings incrementally
#
# Without --apply, this is a dry run showing what would change.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
KB_DIR="$PROJECT_DIR/processed_knowledge_base"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"

# Colours
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

usage() {
    echo "Usage: $0 <botcleaner-output-dir> [--apply] [--embed]"
    echo ""
    echo "  <botcleaner-output-dir>  Path to BotCleaner's output directory"
    echo "  --apply                  Actually copy files (without this, dry run only)"
    echo "  --embed                  Also regenerate embeddings incrementally"
    exit 1
}

if [ $# -lt 1 ]; then
    usage
fi

SOURCE_DIR="$1"
APPLY=false
EMBED=false

shift
while [ $# -gt 0 ]; do
    case "$1" in
        --apply) APPLY=true ;;
        --embed) EMBED=true ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
    shift
done

if [ ! -d "$SOURCE_DIR" ]; then
    echo -e "${RED}ERROR: Source directory not found: $SOURCE_DIR${NC}"
    exit 1
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE} BotCleaner → KB Sync${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "Source: $SOURCE_DIR"
echo -e "Target: $KB_DIR"
echo -e "Mode:   $( [ "$APPLY" = true ] && echo -e "${GREEN}APPLY${NC}" || echo -e "${YELLOW}DRY RUN${NC}" )"
echo ""

# Step 1: Find new/changed files
echo -e "${BLUE}Step 1: Scanning for new/changed files ...${NC}"

NEW_FILES=0
CHANGED_FILES=0
UNCHANGED_FILES=0
FILES_TO_SYNC=()

while IFS= read -r -d '' src_file; do
    # Get relative path from source directory
    rel_path="${src_file#$SOURCE_DIR/}"

    # Skip non-JSON files
    [[ "$rel_path" != *.json ]] && continue
    # Skip embeddings cache
    [[ "$rel_path" == *embeddings_cache* ]] && continue

    dst_file="$KB_DIR/$rel_path"

    if [ ! -f "$dst_file" ]; then
        NEW_FILES=$((NEW_FILES + 1))
        FILES_TO_SYNC+=("$rel_path")
        echo -e "  ${GREEN}NEW${NC}     $rel_path"
    elif ! diff -q "$src_file" "$dst_file" > /dev/null 2>&1; then
        CHANGED_FILES=$((CHANGED_FILES + 1))
        FILES_TO_SYNC+=("$rel_path")
        echo -e "  ${YELLOW}CHANGED${NC} $rel_path"
    else
        UNCHANGED_FILES=$((UNCHANGED_FILES + 1))
    fi
done < <(find "$SOURCE_DIR" -name "*.json" -print0)

TOTAL_SYNC=${#FILES_TO_SYNC[@]}
echo ""
echo -e "  New: ${GREEN}$NEW_FILES${NC}  |  Changed: ${YELLOW}$CHANGED_FILES${NC}  |  Unchanged: $UNCHANGED_FILES"
echo ""

if [ "$TOTAL_SYNC" -eq 0 ]; then
    echo -e "${GREEN}Everything up to date. Nothing to sync.${NC}"
    exit 0
fi

# Step 2: Copy files
if [ "$APPLY" = true ]; then
    echo -e "${BLUE}Step 2: Copying $TOTAL_SYNC files ...${NC}"
    for rel_path in "${FILES_TO_SYNC[@]}"; do
        src_file="$SOURCE_DIR/$rel_path"
        dst_file="$KB_DIR/$rel_path"
        mkdir -p "$(dirname "$dst_file")"
        cp "$src_file" "$dst_file"
    done
    echo -e "  ${GREEN}Done.${NC}"
    echo ""

    # Step 3: Run text cleanup on new files
    echo -e "${BLUE}Step 3: Running text cleanup ...${NC}"
    "$VENV_PYTHON" "$SCRIPT_DIR/kb_text_cleanup.py" --apply 2>&1 | tail -20
    echo ""

    # Step 4: Run quality audit
    echo -e "${BLUE}Step 4: Running quality audit ...${NC}"
    "$VENV_PYTHON" "$SCRIPT_DIR/kb_quality_audit.py" --top 10 --fix-candidates 2>&1 | tail -30
    echo ""

    # Step 5: Optionally regenerate embeddings
    if [ "$EMBED" = true ]; then
        echo -e "${BLUE}Step 5: Regenerating embeddings (incremental) ...${NC}"
        "$VENV_PYTHON" "$SCRIPT_DIR/generate_embeddings_cache.py" --incremental
        echo ""
    else
        echo -e "${YELLOW}Step 5: Skipping embeddings. Run with --embed to update, or:${NC}"
        echo -e "  $VENV_PYTHON $SCRIPT_DIR/generate_embeddings_cache.py --incremental"
    fi
else
    echo -e "${YELLOW}Dry run complete. Run with --apply to sync these files.${NC}"
    echo -e "  $0 $SOURCE_DIR --apply"
fi

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE} Done${NC}"
echo -e "${BLUE}========================================${NC}"
