# 本地 Linux 服务器使用说明

本文记录如何从 Mac 管理运行在 UOS 笔记本中的 Debian 虚拟机。文档包含私有网络地址，因此已加入项目 `.gitignore`，不要提交到 Git 仓库。

## 1. 当前架构

```text
Mac
 └─ Tailscale
     └─ Debian 虚拟机：100.117.112.75
         ├─ SSH：22
         ├─ 1Panel：18080
         └─ Docker / Docker Compose

UOS 宿主机
 └─ libvirt NAT：192.168.122.0/24
     └─ Debian 虚拟机：192.168.122.247
```

Debian 虚拟机配置：

- 名称：`debian-server`
- 系统：Debian GNU/Linux 13 (trixie)
- CPU：6 vCPU
- 内存：16 GiB
- 虚拟磁盘：700 GB（根文件系统约 689 GB）
- 用户：`admin`
- Tailscale 地址：`100.117.112.75`
- libvirt 内网地址：`192.168.122.247`
- Docker：26.1.5
- Docker Compose：2.26.1
- 1Panel：v2.2.5

## 2. 日常连接方式

### 2.1 前置条件

1. UOS 笔记本已开机、未休眠并能访问互联网。
2. Debian 虚拟机处于运行状态。
3. UOS 和 Debian 中的相关服务设置为开机启动。
4. Mac 上的 Tailscale 已连接到与 Debian 相同的 Tailnet。
5. 其他 VPN 或代理没有抢占 Tailscale 的 `100.64.0.0/10` 路由。

### 2.2 SSH 登录 Debian

当前临时密钥路径：

```text
/private/tmp/codex-uos-admin.XN6W0j/id_ed25519
```

登录命令：

```bash
ssh -i /private/tmp/codex-uos-admin.XN6W0j/id_ed25519 \
  admin@100.117.112.75
```

`/private/tmp` 中的文件可能在重启或系统清理后消失。应尽快生成长期使用的密钥，并把公钥加入 Debian 的 `~/.ssh/authorized_keys`：

```bash
ssh-keygen -t ed25519 -f ~/.ssh/debian-server_ed25519
```

在临时密钥仍有效时安装新公钥：

```bash
cat ~/.ssh/debian-server_ed25519.pub | \
  ssh -i /private/tmp/codex-uos-admin.XN6W0j/id_ed25519 \
  admin@100.117.112.75 \
  'umask 077; mkdir -p ~/.ssh; cat >> ~/.ssh/authorized_keys'
```

之后使用：

```bash
ssh -i ~/.ssh/debian-server_ed25519 admin@100.117.112.75
```

### 2.3 打开 1Panel

浏览器访问：

```text
http://100.117.112.75:18080/panelEntrance
```

- 用户名：`panelAdmin`
- 密码不写入本文。可登录 Debian 后运行 `sudo 1pctl user-info` 查看当前面板登录信息。
- 首次登录后应立即修改初始密码。

如果 Codex 内置浏览器提示“无法访问此站点”，优先使用系统 Safari、Chrome 或 Firefox。内置浏览器可能无法继承 macOS 的 Tailscale 路由。

## 3. VPN 冲突处理

已验证服务器和 1Panel 本身可以通过 Tailscale 访问。如果连接另一个 VPN 后网页打不开，通常是该 VPN 抢占了 `100.x` 路由。

先临时关闭其他 VPN 再测试：

```bash
ssh -i ~/.ssh/debian-server_ed25519 admin@100.117.112.75
curl -I http://100.117.112.75:18080/panelEntrance/
```

若关闭 VPN 后恢复，在该 VPN 或代理软件中加入分流规则：

```text
100.64.0.0/10 -> DIRECT / 绕过代理 / 不走该 VPN
```

这段地址必须交给 Tailscale 的网络接口处理。可在 Mac 上检查系统选择的路由：

```bash
route -n get 100.117.112.75
```

## 4. 校园网 IPv6 备用连接

当 Tailscale 不可用、但 Mac 能访问校园网 IPv6 时，可以通过 UOS 宿主机跳转。

UOS 地址可能随校园网变化，历史地址为：

```text
240c:c001:1014:d8eb:dd3b:e6e9:b68c:4986
```

SSH 跳转到 Debian：

```bash
ssh -i /private/tmp/codex-uos-admin.XN6W0j/id_ed25519 \
  -o 'ProxyCommand=ssh -6 -i /private/tmp/codex-uos-admin.XN6W0j/id_ed25519 -W %h:%p admin@240c:c001:1014:d8eb:dd3b:e6e9:b68c:4986' \
  admin@192.168.122.247
```

为 1Panel 建立本地端口转发：

```bash
ssh -6 -N \
  -L 18080:192.168.122.247:18080 \
  -i /private/tmp/codex-uos-admin.XN6W0j/id_ed25519 \
  admin@240c:c001:1014:d8eb:dd3b:e6e9:b68c:4986
```

保持终端窗口运行，然后访问：

```text
http://127.0.0.1:18080/panelEntrance
```

## 5. 常用服务命令

在 Debian 中查看服务状态：

```bash
systemctl status tailscaled
systemctl status docker
systemctl status 1panel-core
systemctl status 1panel-agent
```

查看 Tailscale 状态：

```bash
tailscale status
tailscale ip -4
tailscale netcheck
```

查看 Docker：

```bash
docker version
docker compose version
docker ps
docker compose ps
```

查看磁盘和内存：

```bash
df -h /
free -h
lsblk
```

## 6. 在 UOS 上管理虚拟机

以下命令在 UOS 宿主机执行，需要 `sudo`：

```bash
sudo virsh list --all
sudo virsh start debian-server
sudo virsh shutdown debian-server
sudo virsh reboot debian-server
sudo virsh dominfo debian-server
sudo virsh domifaddr debian-server --source agent
```

虚拟机磁盘及相关文件位于：

```text
/data/vm/
```

备份系统盘前应先正常关闭虚拟机，避免得到不一致的磁盘镜像。

## 7. 故障排查顺序

1. 确认 UOS 笔记本已开机、联网且未休眠。
2. 确认 Mac 上 Tailscale 已连接。
3. 暂停其他 VPN，排除 `100.64.0.0/10` 路由冲突。
4. 测试 `ssh admin@100.117.112.75`。
5. SSH 成功后检查 `docker`、`1panel-core` 和 `1panel-agent`。
6. Tailscale 不通时，改用校园网 IPv6 跳板检查 UOS 和 Debian。
7. 虚拟机地址变化时，在 UOS 执行 `sudo virsh domifaddr debian-server --source agent`。

## 8. 安全建议

- 不要把 SSH 私钥、1Panel 密码或 Tailscale 授权密钥提交到 Git。
- 用长期 SSH 密钥替换 `/private/tmp` 下的临时密钥，完成后删除临时公钥授权。
- 只通过 Tailscale 访问 SSH 和 1Panel，不要把管理端口直接暴露到公网。
- 定期更新 Debian、Docker、Tailscale 和 1Panel。
- 为重要容器数据配置独立备份；虚拟磁盘不是备份。
