# Cloudflare 域名配置教程(wafer.echeng.xyz)

> 目标:让 `https://wafer.echeng.xyz` 指向你的服务器并带上 HTTPS 绿锁。
> 全程只在你自己的 Cloudflare 后台点几下,5 分钟;不花钱、不买新域名。
> 前提:`echeng.xyz` 这个域已经托管在你的 Cloudflare(你的 echeng.xyz 站点就是这种情况)。

## 第 1 步:登录 Cloudflare,选中域名

1. 浏览器打开 [dash.cloudflare.com](https://dash.cloudflare.com),登录你的账号;
2. 首页域名列表里点 **echeng.xyz** 进入这个域的管理页。

## 第 2 步:添加 DNS 记录

1. 左侧菜单点 **DNS → Records**(中文界面:DNS → 记录);
2. 点 **+ Add record**(添加记录),按下表填写:

| 字段 | 填什么 | 说明 |
|---|---|---|
| Type(类型) | **A** | 指向 IPv4 地址 |
| Name(名称) | **wafer** | 只填这一段,CF 会自动补成 wafer.echeng.xyz |
| IPv4 address | 你服务器的**公网 IP** | 腾讯云控制台实例详情页能看到,和 SSH 用的同一个 IP |
| Proxy status(代理状态) | **Proxied(橙色云,务必开启)** | 流量走 CF,隐藏真实 IP,自动带 HTTPS 和防护 |
| TTL | Auto | 默认即可 |

3. 点 **Save**(保存)。列表里出现 `wafer  A  <你的IP>  Proxied` 即成功。

## 第 3 步:确认 SSL 模式(一般不用动)

1. 左侧菜单 **SSL/TLS → Overview**;
2. 看加密模式:你的 echeng.xyz 已经 https 正常,说明这里早已配好(推荐 **Full** 或
   **Full (strict)**),子域名自动继承整套设置,**什么都不用改**;
3. 仅当服务器 AI 汇报"需要源站证书"时才进来:**SSL/TLS → Origin Server**。现有 echeng.xyz
   在用的那张源站证书默认覆盖 `*.echeng.xyz`(含 wafer 子域,15 年有效),让服务器 AI 直接
   复用即可;真要新签才会用到 **Create Certificate**。

## 第 4 步:验证

1. 等 1~5 分钟(DNS 生效);
2. 浏览器打开 `https://wafer.echeng.xyz/health`:
   - **部署完成前**显示 502/503 —— 正常,nginx 已接客但后端服务还没数据启动;
   - 服务器数据就位 + 我这边触发部署后,应看到 `{"ok":true,"images":510,...}` 即大功告成;
3. 顺手验证:浏览器地址栏是 🔒 绿锁,点开证书颁发者是 Cloudflare。

## 常见坑(避开就行)

- **Proxy 必须开橙色云**:灰云(DNS only)的话浏览器直连源站 IP,没有 CF 的 HTTPS 和防护;
- **SSH 不要用 wafer.echeng.xyz**:开了橙云后这个域名解析到的是 Cloudflare 的 IP,SSH 会
  被挡。GitHub Secrets 里的 `SSH_HOST` 和 WinSCP 的主机名都填**服务器真实 IP**;
- 记录类型选 A(指向 IP),别选 CNAME;
- 改完没生效?等 5 分钟再试,或换浏览器无痕模式(DNS 有缓存)。
