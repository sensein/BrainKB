# Oxygraph with Nginx

1. Create a directory
```bash
sudo mkdir -p /srv/oxigraph-tmp
sudo chmod 1777 /srv/oxigraph-tmp
```
2. Run the `docker-compose command`.
Make sure you update the default username and password.
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