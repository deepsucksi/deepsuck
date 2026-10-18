# 0004 静态站点放 GitHub Pages，实时服务放单台 VPS

状态：已采纳

## 背景

项目是开源公益项目，预算小。主站要稳定、免费、能被任何人 fork 自建；语音演示需要长连接、UDP 媒体和密钥，只能放服务器。

## 决策

- `site/` 由 `.github/workflows/pages.yml` 在推送 `main` 时发布到 GitHub Pages（deepsuck.si），先跑 `npm test`。
- 实时服务（proxy、voice、可选 coturn、Asterisk）用 `deploy/docker-compose.yml` 部署在阿里云香港一台 2C2G 服务器（live.deepsuck.si），caddy 负责 TLS。
- 站点通过 `live-config.js` 发现实时服务；地址为空时纯静态运行。

## 后果

- 主站零运维；实时服务挂了不影响主站。
- 单点：服务器宕机即语音演示不可用；小盘需要监控录音与日志占用（#18）。
- 香港 IP 在大陆部分网络被阻断，大陆访问需要另行决策（#16）。
- 开发与部署分离：在服务器开发目录提交，生产目录只部署，不直接改。
