# Google 登录：一次性配置（约 10 分钟）

配好以后：你和你邀请的人打开 DealDesk，点“使用 Google 账号登录”就能进，不再需要访问令牌。
**只有在“设置 → 用户”里登记过 Google 邮箱的人能进**（邀请制，没有公开注册）。

## 1. 在 Google 建一个 OAuth 客户端

1. 打开 <https://console.cloud.google.com/>，左上角新建一个项目，名字随意（如 `DealDesk`）。
2. 左侧菜单 **APIs & Services → OAuth consent screen**（或新版的 **Google Auth Platform → Branding**）：
   - User type 选 **External**；App name 填 `DealDesk`；User support email 与 Developer contact 填你自己的 Gmail。
   - Scopes 不用加（只用默认的 email / profile / openid）。
   - 在 **Audience** 里点 **Publish app**（发布为 In production）。只用这三个基础权限，Google 不要求审核；
     不发布的话，只有手动加进 Test users 的人能登录。
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**：
   - Application type：**Web application**；Name：`DealDesk`。
   - **Authorized redirect URIs** 加这两条（两个域名都在用，就都加上）：
     - `https://vertciti-dealdesk.vercel.app/api/v2/auth/google/callback`
     - `https://dealdesk.vercel.app/api/v2/auth/google/callback`
   - 点 Create，记下弹出的 **Client ID** 和 **Client secret**。

## 2. 把它填进 Vercel（项目 `vertciti-dealdesk` → Settings → Environment Variables → Production）

| 变量 | 值 |
|---|---|
| `DEALDESK_GOOGLE_CLIENT_ID` | 上一步的 Client ID（以 `.apps.googleusercontent.com` 结尾） |
| `DEALDESK_GOOGLE_CLIENT_SECRET` | 上一步的 Client secret |
| `DEALDESK_OWNER_EMAIL` | 你自己的 Gmail。你第一次用 Google 登录时，系统自动给你建董事长账号 |
| `DEALDESK_SESSION_HOURS` | 可选，登录有效小时数，默认 12 |

`DEALDESK_PUBLIC_URL` **不要设**：两个域名都能登录，回调地址按你打开的域名自动拼。
Client secret 只填在 Vercel 里，**不要**贴进聊天、代码或日志。填完后重新部署一次。

## 3. 用起来

1. 打开 DealDesk → 点 **使用 Google 账号登录** → 选你的 Gmail。第一次进来就是董事长。
2. 邀请别人：**设置 → 用户 → 邀请用户**，填对方的 Gmail、一个用户名、角色（董事长 / 分析 / 只读）→ 邀请。
   对方打开 DealDesk 点“使用 Google 账号登录”即可。
3. 撤销：在用户列表里清空对方的邮箱点“保存邮箱”，或点“停用”（停用后已登录的会话立即失效）。
4. 右上角 **退出登录** 作废当前会话。

## 原理与安全（给运维）

- 标准 OpenID Connect 授权码流程：`/api/v2/auth/google/start` → Google → `/api/v2/auth/google/callback`。
  state 与 nonce 放在只对 `/api/v2/auth` 生效的 HttpOnly cookie 里防 CSRF 与重放；授权码由服务器带 client secret 换 id_token，
  再由 Google tokeninfo 校验签名与有效期，并核对 aud（本应用）、iss、nonce、邮箱已验证。
- 登录成功后签发会话令牌（`dds_…`，只存 sha256，默认 12 小时过期），通过 URL 片段 `/app/#auth=…` 交给前端；
  片段不会发给服务器、不进访问日志，前端读出后立刻从地址栏抹掉。之后照常以 Bearer 头发送，服务端仍不读业务 cookie。
- 长期访问令牌（`dd_…`）照常可用，留给脚本与管理员。
- 代码：`app/services/v2/google_auth.py`、`app/api/v2/auth.py`；测试：`tests/test_v2_google_login.py`；迁移 0003。
