# Dev Deployment Script

## Overview

`dev-deploy.sh` is a deployment script for the Pocket Dev Guild backend that handles:
- Checking if the uvicorn server is running
- Checking for active jobs (running or queued)
- Gracefully stopping and restarting the server
- Logging to `/tmp/pdg-uvicorn.log`
- Dry-run mode for testing

## Usage

### Basic Deployment

```bash
./dev-deploy.sh
```

This will:
1. Check if uvicorn is running
   - If not: start it with nohup and exit
   - If yes: proceed to step 2
2. Check for running or queued jobs via the API
   - If jobs exist: bail out with an error
   - If no jobs: proceed to step 3
3. Stop the current server gracefully (SIGTERM, then SIGKILL if needed)
4. Start a new server instance with nohup
5. Verify the server is healthy

### Dry-Run Mode

Test what the script would do without making any changes:

```bash
./dev-deploy.sh --dry-run
```

This shows all the steps that would be executed.

### Force Mode

Force restart even if jobs are running (use with caution):

```bash
./dev-deploy.sh --force
```

**Warning**: This will interrupt any running jobs!

### Combined Flags

Test a forced restart:

```bash
./dev-deploy.sh --dry-run --force
```

## Requirements

- `bash`
- `pgrep` (process checking)
- `lsof` (port checking)
- `curl` (API health checks)
- `jq` (JSON parsing for job checks)

## Configuration

The script uses these locations (can be customized by editing the script):

- **Log file**: `/tmp/pdg-uvicorn.log`
- **PID file**: `/tmp/pdg-uvicorn.pid`
- **API URL**: `http://localhost:8000`

## Exit Codes

- `0`: Success
- `1`: Error (server has running jobs, couldn't start, etc.)

## Examples

### Scenario 1: Server not running

```bash
$ ./dev-deploy.sh
📋 Checking server status...
📋 Server is not running
📋 Starting server with nohup...
📋 Starting uvicorn server...
📋 Server started with PID: 12345
📋 Logs: /tmp/pdg-uvicorn.log
📋 Waiting for server to be ready...
📋 ✅ Server is healthy and responding
```

### Scenario 2: Server running, no active jobs

```bash
$ ./dev-deploy.sh
📋 Checking server status...
📋 Server is running
📋 Checking for running jobs...
📋 No active jobs found
📋 Current server PID: 12345
📋 Stopping uvicorn server (PID: 12345)...
📋 Server stopped
📋 Starting uvicorn server...
📋 Server started with PID: 12346
📋 Logs: /tmp/pdg-uvicorn.log
📋 Waiting for server to be ready...
📋 ✅ Server is healthy and responding
📋 ✅ Deployment complete!
```

### Scenario 3: Server running with active jobs

```bash
$ ./dev-deploy.sh
📋 Checking server status...
📋 Server is running
📋 Checking for running jobs...
📋 Found 2 running job(s)
❌ ERROR: Server has running or queued jobs!
❌ ERROR: Cannot deploy while jobs are active.
❌ ERROR: Please wait for jobs to complete or cancel them.
❌ ERROR: Or use --force to restart anyway (may interrupt jobs)
```

## Troubleshooting

### jq not installed

If you get an error about `jq` not being installed:

```bash
# Ubuntu/Debian
sudo apt-get install jq

# macOS
brew install jq
```

### Server won't start

Check the logs:

```bash
tail -f /tmp/pdg-uvicorn.log
```

### Port already in use

If port 8000 is already in use by another process:

```bash
# Find what's using port 8000
lsof -i :8000

# Kill it if needed
kill -9 <PID>
```

## Integration with CI/CD

You can use this script in automated deployments:

```bash
# In your CI/CD pipeline
./dev-deploy.sh --force  # Force restart regardless of jobs
```

Or more conservatively:

```bash
# Check first, deploy only if safe
if ./dev-deploy.sh --dry-run; then
    ./dev-deploy.sh
else
    echo "Deployment blocked by active jobs"
    exit 1
fi
```
