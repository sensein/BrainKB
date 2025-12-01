# Automatic servers.json Generation for Docker Compose

This guide shows you how to automatically generate `servers.json` whenever you run `docker-compose up`.

## Option 1: Use the Wrapper Script (Recommended)

Use the provided wrapper script instead of `docker-compose` directly:

```bash
./docker-compose-wrapper.sh -f docker-compose.unified.yml up -d
```

## Option 2: Create an Alias (Most Convenient - Recommended)

**Quick Setup:**

1. Get your project path:
   ```bash
   cd /Users/tekrajchhetri/Documents/brainypedia_codes_design/BrainKB
   pwd  # Copy this path
   ```

2. Add this to your `~/.bashrc` or `~/.zshrc` (replace `YOUR_PROJECT_PATH` with the path from step 1):

   ```bash
   # Auto-generate servers.json before docker-compose
   alias docker-compose='cd YOUR_PROJECT_PATH && ./docker-compose-wrapper.sh'
   ```

   Example:
   ```bash
   alias docker-compose='cd /Users/tekrajchhetri/Documents/brainypedia_codes_design/BrainKB && ./docker-compose-wrapper.sh'
   ```

Then reload your shell:
```bash
source ~/.bashrc  # or source ~/.zshrc
```

Now you can use `docker-compose` normally and it will auto-generate `servers.json`:

```bash
docker-compose -f docker-compose.unified.yml up -d
docker-compose -f docker-compose.unified.yml down
docker-compose -f docker-compose.unified.yml logs -f
# etc.
```

## Option 3: Use Make

The Makefile automatically generates `servers.json`:

```bash
make up          # Generates servers.json and starts services
make up-build    # Generates servers.json, builds, and starts services
```

## Option 4: Manual (One-time Setup)

If you prefer manual control, generate it once:

```bash
bash pgadmin-init/generate-servers-json.sh pgadmin-init
docker-compose -f docker-compose.unified.yml up -d
```

## How It Works

The wrapper script:
1. Checks if `servers.json` exists and is up-to-date
2. If not, generates it from your `.env` file
3. Then runs the actual `docker-compose` command

This ensures `servers.json` is always current with your environment variables.

