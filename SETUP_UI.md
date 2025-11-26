# Deploying BrainKB UI Separately

This guide explains how to deploy the BrainKB UI separately after the backend services are up and running.

**Important:** The UI is not included in the unified docker-compose deployment. Deploy the backends first, then configure and deploy the UI separately.

## Default Behavior: Always Pull Latest UI

**By default, the Dockerfile will always pull the latest UI from the `main` branch** during each build. This means:
- ✅ No git submodule needed
- ✅ Always gets the latest UI code
- ✅ Simple deployment - just rebuild

**To use this (default):**
- Just build normally - no setup needed!
- The UI will be cloned from GitHub during the build

**To disable and use git submodule instead:**
Set `PULL_LATEST_UI=false` in your `.env` file

## Option 1: Git Submodule (For Version Pinning)

If you want to pin to a specific UI version for production:

**Steps:**

1. **Add the submodule:**
   ```bash
   git submodule add https://github.com/sensein/brainkb-ui.git brainkb-ui
   ```

2. **Set in `.env` file:**
   ```bash
   PULL_LATEST_UI=false
   ```

3. **Initialize submodules:**
   ```bash
   git submodule update --init --recursive
   ```

**Note:** 
- This approach pins to a specific commit
- More reproducible builds
- Recommended for production when you need version stability

## Option 3: Manual Clone (For Development)

For local development, you can manually clone the UI:

```bash
git clone https://github.com/sensein/brainkb-ui.git
```

Then ensure the `brainkb-ui` directory exists in the project root before building.

## Verifying Setup

After adding the submodule, verify it's set up correctly:

```bash
# Check submodule status
git submodule status

# Should show something like:
# abc1234... brainkb-ui (v1.0.0)
```

## Deploying UI Separately

After the backend services are running, deploy the UI:

### Option A: Using Docker Compose (Recommended)

Use the provided `docker-compose.ui.yml`:

```bash
# Make sure backend services are running first
docker-compose -f docker-compose.unified.yml up -d

# Then deploy the UI
docker-compose -f docker-compose.ui.yml up -d --build
```

The UI will connect to the existing `brainkb-network` and can communicate with the backend services.

### Option B: Standalone Docker Build

```bash
# Build the UI image
docker build -f Dockerfile.ui -t brainkb-ui:latest .

# Run the UI container
docker run -d \
  --name brainkb-ui \
  --network brainkb-network \
  -p 3000:3000 \
  --env-file .env \
  brainkb-ui:latest
```

## Troubleshooting

### Submodule appears empty
```bash
git submodule update --init --recursive
```

### Need to update UI to latest version
```bash
cd brainkb-ui
git checkout main
git pull origin main
cd ..
git add brainkb-ui
git commit -m "Update UI to latest"
```

### Remove submodule (if needed)
```bash
git submodule deinit -f brainkb-ui
git rm -f brainkb-ui
rm -rf .git/modules/brainkb-ui
```

## Environment Variables

Make sure to configure UI environment variables in your `.env` file. See `env.template` for all required variables.

Key variables for UI:
- `NEXTAUTH_SECRET` - Secret for NextAuth.js
- `NEXTAUTH_URL` - URL where UI is accessible
- `NEXT_PUBLIC_*` - Public API endpoints (adjust based on your deployment)

