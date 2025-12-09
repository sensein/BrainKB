# Oxigraph with Nginx

## Local Development

For local development, the docker-compose configuration uses Docker named volumes by default. Simply run:

```bash
docker-compose up
```

Make sure you update the default username and password in the `.env` file or directly in the docker-compose file.

## Production Deployment with Custom Paths

If you need to use custom paths for data storage (e.g., shared storage):

1. Set environment variables in `.env`:
   ```bash
   OXIGRAPH_DATA_PATH=/fsx/brainkb-kg-repo
   OXIGRAPH_TMP_PATH=/srv/oxigraph-tmp
   ```

2. Create the directories with appropriate permissions:
   ```bash
   sudo mkdir -p /srv/oxigraph-tmp
   sudo chmod 1777 /srv/oxigraph-tmp
   sudo mkdir -p /fsx/brainkb-kg-repo
   sudo chown -R $(whoami):$(whoami) /fsx/brainkb-kg-repo
   ```

3. Run docker-compose:
   ```bash
   docker-compose up
   ```

## Weekly cleanup unused volume
```bash
sudo bash -c 'cat <<EOF > /etc/cron.weekly/docker-prune
#!/bin/bash
/usr/bin/docker system prune -f --volumes
EOF'
sudo chmod +x /etc/cron.weekly/docker-prune
```