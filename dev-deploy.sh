#!/usr/bin/env bash
# Dev deployment script for Pocket Dev Guild backend
# Handles checking for running server, active jobs, and graceful restarts
#
# Usage:
#     ./dev-deploy.sh                 # Normal deploy
#     ./dev-deploy.sh --dry-run       # Dry-run mode (show what would happen)
#     ./dev-deploy.sh --force         # Force restart even if jobs are running
#     ./dev-deploy.sh --dry-run --force

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
API_URL="http://localhost:8000"
LOG_FILE="/tmp/pdg-uvicorn.log"
PID_FILE="/tmp/pdg-uvicorn.pid"
MAIN_BRANCH="main"
DRY_RUN=false
FORCE=false

# Parse arguments
for arg in "$@"; do
    case "$arg" in
        --dry-run)
            DRY_RUN=true
            ;;
        --force)
            FORCE=true
            ;;
        *)
            echo "Unknown argument: $arg"
            echo "Usage: $0 [--dry-run] [--force]"
            exit 1
            ;;
    esac
done

if [[ "$DRY_RUN" == "true" ]]; then
    echo "🔍 DRY-RUN MODE - No changes will be made"
fi
if [[ "$FORCE" == "true" ]]; then
    echo "⚠️  FORCE MODE - Will restart even if jobs are running"
fi
if [[ "$DRY_RUN" == "true" ]] || [[ "$FORCE" == "true" ]]; then
    echo ""
fi

# Helper functions
log() {
    echo "📋 $*"
}

error() {
    echo "❌ ERROR: $*" >&2
}

dry_run_exec() {
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "   [DRY-RUN] Would execute: $*"
    else
        eval "$@"
    fi
}

# Check if uvicorn is running
check_server_running() {
    # Try to find uvicorn process
    if pgrep -f "uvicorn main:app" > /dev/null 2>&1; then
        return 0
    fi
    
    # Also check if port 8000 is bound
    if lsof -i :8000 -t > /dev/null 2>&1; then
        return 0
    fi
    
    return 1
}

# Get PID of running uvicorn
get_server_pid() {
    pgrep -f "uvicorn main:app" || true
}

# Check for running jobs via API
check_running_jobs() {
    local count

    # Check if jq is available
    if ! command -v jq &> /dev/null; then
        error "jq is not installed - cannot check for running jobs"
        error "Install jq or skip this check"
        return 1
    fi

    # Query API for jobs with status=running or status=queued
    count=$(curl -s "${API_URL}/api/jobs?status=running&limit=1" 2>/dev/null | jq -r '.total // 0' || echo "0")
    if [[ "$count" != "0" ]]; then
        log "Found $count running job(s)"
        return 0  # Has running jobs
    fi

    count=$(curl -s "${API_URL}/api/jobs?status=queued&limit=1" 2>/dev/null | jq -r '.total // 0' || echo "0")
    if [[ "$count" != "0" ]]; then
        log "Found $count queued job(s)"
        return 0  # Has queued jobs
    fi

    return 1  # No active jobs
}

# Check if server is healthy (responds to API)
check_server_health() {
    local status_code
    status_code=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}/api/docs" 2>/dev/null || echo "000")
    if [[ "$status_code" == "200" ]]; then
        return 0
    fi
    return 1
}

# Start the server
start_server() {
    log "Starting uvicorn server..."
    dry_run_exec "cd \"$SCRIPT_DIR\" && nohup ./run-dev.sh > \"$LOG_FILE\" 2>&1 &"

    if [[ "$DRY_RUN" == "false" ]]; then
        # Save PID
        sleep 2
        local pid
        pid=$(get_server_pid)
        if [[ -n "$pid" ]]; then
            echo "$pid" > "$PID_FILE"
            log "Server started with PID: $pid"
            log "Logs: $LOG_FILE"

            # Wait for server to be healthy
            log "Waiting for server to be ready..."
            local count=0
            while ! check_server_health && [[ $count -lt 10 ]]; do
                sleep 1
                count=$((count + 1))
            done

            if check_server_health; then
                log "✅ Server is healthy and responding"
            else
                error "Server started but not responding to health checks"
            fi
        else
            error "Failed to start server (no PID found)"
            return 1
        fi
    fi
}

# Stop the server
stop_server() {
    local pid="$1"
    log "Stopping uvicorn server (PID: $pid)..."
    
    dry_run_exec "kill -TERM $pid"
    
    if [[ "$DRY_RUN" == "false" ]]; then
        # Wait for graceful shutdown (max 10 seconds)
        local count=0
        while kill -0 "$pid" 2>/dev/null && [[ $count -lt 10 ]]; do
            sleep 1
            count=$((count + 1))
        done
        
        # Force kill if still running
        if kill -0 "$pid" 2>/dev/null; then
            log "Forcing shutdown..."
            kill -KILL "$pid" 2>/dev/null || true
        fi
        
        log "Server stopped"
        rm -f "$PID_FILE"
    fi
}

# Check git branch and freshness against origin
check_git_state() {
    local current_branch
    current_branch=$(git -C "$SCRIPT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")

    if [[ -z "$current_branch" ]]; then
        log "⚠️  Not a git repository or no current branch - skipping git checks"
        return
    fi

    if [[ "$current_branch" != "$MAIN_BRANCH" ]]; then
        log "⚠️  WARNING: Current branch is '$current_branch', not '$MAIN_BRANCH'"
    else
        log "On branch '$current_branch'"
    fi

    log "Fetching from origin..."
    if ! git -C "$SCRIPT_DIR" fetch origin "$MAIN_BRANCH" 2>/dev/null; then
        log "⚠️  WARNING: git fetch failed - cannot verify remote state"
        return
    fi

    local local_sha remote_sha
    local_sha=$(git -C "$SCRIPT_DIR" rev-parse "$MAIN_BRANCH" 2>/dev/null || echo "")
    remote_sha=$(git -C "$SCRIPT_DIR" rev-parse "origin/$MAIN_BRANCH" 2>/dev/null || echo "")

    if [[ -z "$local_sha" ]] || [[ -z "$remote_sha" ]]; then
        log "⚠️  WARNING: Could not resolve '$MAIN_BRANCH' or 'origin/$MAIN_BRANCH'"
        return
    fi

    if [[ "$local_sha" != "$remote_sha" ]]; then
        local behind ahead
        behind=$(git -C "$SCRIPT_DIR" rev-list --count "$MAIN_BRANCH..origin/$MAIN_BRANCH" 2>/dev/null || echo "?")
        ahead=$(git -C "$SCRIPT_DIR" rev-list --count "origin/$MAIN_BRANCH..$MAIN_BRANCH" 2>/dev/null || echo "?")
        log "⚠️  WARNING: '$MAIN_BRANCH' is not in sync with 'origin/$MAIN_BRANCH' (behind: $behind, ahead: $ahead)"
    else
        log "'$MAIN_BRANCH' is up to date with 'origin/$MAIN_BRANCH'"
    fi
}

# Main deployment logic
main() {
    check_git_state

    log "Checking server status..."
    
    if ! check_server_running; then
        log "Server is not running"
        log "Starting server with nohup..."
        start_server
        exit 0
    fi
    
    log "Server is running"

    # Check for active jobs (unless forced)
    if [[ "$FORCE" != "true" ]]; then
        log "Checking for running jobs..."
        if check_running_jobs; then
            error "Server has running or queued jobs!"
            error "Cannot deploy while jobs are active."
            error "Please wait for jobs to complete or cancel them."
            error "Or use --force to restart anyway (may interrupt jobs)"
            exit 1
        fi

        log "No active jobs found"
    else
        log "Skipping job check (--force mode)"
    fi
    
    # Get current PID
    local pid
    pid=$(get_server_pid)
    if [[ -z "$pid" ]]; then
        error "Could not determine server PID"
        exit 1
    fi
    
    log "Current server PID: $pid"
    
    # Stop and restart
    stop_server "$pid"
    sleep 1
    start_server
    
    log "✅ Deployment complete!"
}

# Run main
main
