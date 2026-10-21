这里放启用的可选站点（`*.caddy`），Caddyfile 末尾 `import sites-enabled/*.caddy`。目录为空时 Caddy 照常启动。
启用统计：`cp ../stats.caddy.example stats.caddy`，并在 `deploy/.env` 设 `STATS_DOMAIN`。
