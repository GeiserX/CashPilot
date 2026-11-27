---
source_hash: e99e2c0c80bb
---
# 应用商店 { #app-stores }

你可以从多种家庭服务器系统的应用商店安装 CashPilot。
每个上架包都会安装仪表板（`drumsergio/cashpilot`）和工作节点
（`drumsergio/cashpilot-worker`），工作节点负责启动和停止服务
容器。只有本仓库中的 CasaOS 和 Runtipi 软件包还会
安装 `docker-compose.yml` 中的 Docker socket 代理，所以它们的工作节点
从不持有原始的 Docker socket。Unraid 模板、TrueNAS 应用以及
CasaOS 应用商店中尚未合并的拉取请求里的软件包，仍然直接在工作节点中挂载 Docker
socket。

无论使用哪个商店，都请把仪表板留在你的 LAN 或 VPN 内。它可以指挥
工作节点，而工作节点在主机上驱动 Docker。如果工作节点自己持有
socket，那就相当于主机上的 root。

## 目前已上架 { #listed-today }

### Unraid Community Applications { #unraid-community-applications }

在 Apps 标签页中搜索 **CashPilot**，并安装两个模板：
`cashpilot`（仪表板）和 `cashpilot-worker`。在两者上设置相同的
`CASHPILOT_API_KEY`。

这些模板来自 https://github.com/GeiserX/docker-templates ，并跟随
`latest` 镜像标签，所以 Community Applications 用户无需修改模板
就能获得每个新版本。

### TrueNAS SCALE { #truenas-scale }

CashPilot 位于 TrueNAS 的 **community** train（应用渠道）中。打开 Apps，再打开 Discover Apps，
然后搜索 **CashPilot**。

应用定义维护在
https://github.com/truenas/apps/tree/master/ix-dev/community/cashpilot ，并固定
一个确切的镜像摘要。由 TrueNAS 自己的机器人把它更新到新版本，所以它可能
比最新的 CashPilot 落后几个版本。

## 等待审核 { #waiting-for-review }

### CasaOS { #casaos }

一个提交到 CasaOS 应用商店的拉取请求已经开启：
https://github.com/IceWhaleTech/CasaOS-AppStore/pull/1088

在它合并之前，请把它作为自定义应用安装：在 CasaOS 中选择 App Store，
然后选 Custom Install，再选 Import，并粘贴以下文件的内容：
https://github.com/GeiserX/CashPilot/blob/main/contrib/app-stores/casaos/CashPilot/docker-compose.yml

它需要 CasaOS 0.4.5 或更高版本：从该版本起，它的应用管理器基于
Docker Compose 2.23，能从文件中读取 socket 代理的策略。
更早的版本会丢弃该策略，于是工作节点无法访问 Docker。

该文件固定了一个确切的版本。导入之前，请把两个镜像标签
（`drumsergio/cashpilot` 和 `drumsergio/cashpilot-worker`）都设为
https://github.com/GeiserX/CashPilot/releases 上的最新版本。文件中的代理策略
跟随 `main`；如果工作节点的状态页显示其策略
已过时，请重新导入该文件。

## 已准备，尚未提交 { #prepared-not-yet-submitted }

### Runtipi { #runtipi }

软件包已在
https://github.com/GeiserX/CashPilot/tree/main/contrib/app-stores/runtipi/cashpilot
准备好，但还没有进入 Runtipi 应用商店。要现在就使用它，请按照 Runtipi 文档，
把它添加到你自己管理的自定义应用商店：
https://runtipi.io/docs/guides/create-your-own-app-store

## 未提供 { #not-offered }

Umbrel 需要不同的工作节点设计，因为 Umbrel 应用是通过一个
Docker-in-Docker 容器访问 Docker，而不是通过主机 socket。我们还没有
测试过，所以目前没有 Umbrel 软件包。

对于其他任何系统，请使用仓库中的 `docker-compose.yml`，做法见
[快速入门](getting-started.md)。
