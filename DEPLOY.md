# 部署到 Render + Firebase Firestore（全免费）

部署完成后你会得到一个固定网址，比如 `https://syllabus2cal.onrender.com`。任何网络下的手机都能打开和订阅，电脑关机也不影响。

总共 4 步，大约 30–40 分钟。

---

## 第 1 步：Firebase —— 建数据库、拿密钥（约 10 分钟）

1. 打开 https://console.firebase.google.com ，用 Google 账号登录。
2. **创建项目**（Create a project），名字随便填，比如 `syllabus2cal`。Google Analytics 可以关掉。
3. 左侧菜单 **Build → Firestore Database** → **Create database**：
   - 位置（location）选 `nam5 (United States)` 或者离你近的。
   - 模式选 **Production mode**。我们只通过服务器端的密钥访问，所以不用改安全规则。
4. 左上角齿轮 ⚙ → **Project settings** → **Service accounts** 标签页 → 点 **Generate new private key** → 确认下载。
   - 会下载一个 `xxx-firebase-adminsdk-xxxx.json` 文件。
   - ⚠️ **这个文件就是数据库的钥匙：不要提交到 git，不要发给别人**。项目里的 `.gitignore` 已经把这类文件排除掉了。

先在本地试一下（可选，但建议做）：
```bash
export FIREBASE_CREDENTIALS="$(cat ~/Downloads/你下载的文件名.json)"
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
终端里出现 `[storage] using firestore` 就说明连上了。在网页上建一个日历，然后到 Firebase 控制台的 Firestore 页面，应该能看到 `calendars` 集合里多了一条记录。

---

## 第 2 步：把代码推到 GitHub（约 5 分钟）

Render 是从 GitHub 拉代码来部署的。

1. 在 https://github.com/new 新建一个仓库，比如 `syllabus2cal`（Public、Private 都可以）。
2. 在 Git Bash 里查一下你的 git 仓库根目录在哪：
   ```bash
   git rev-parse --show-toplevel
   ```
   - 如果输出的是 `.../Downloads/syllabus2cal/syllabus2cal`，说明项目文件就在仓库根目录，第 3 步的 **Root Directory 留空**。
   - 如果输出的是 `.../Downloads/syllabus2cal`，说明代码在仓库的子文件夹里，第 3 步的 **Root Directory 填 `syllabus2cal`**。
3. 提交并推送（把 `你的用户名` 换掉）：
   ```bash
   git status            # 先确认列表里没有 firebase 的 .json 密钥文件！
   git add -A
   git commit -m "deploy: firestore storage"
   git branch -M main
   git remote add origin https://github.com/你的用户名/syllabus2cal.git
   git push -u origin main
   ```
   如果提示 `remote origin already exists`，把 `git remote add` 那行跳过，直接运行 `git push`。

---

## 第 3 步：Render —— 建 Web Service（约 10 分钟）

1. 打开 https://render.com ，用 GitHub 账号登录。
2. **New + → Web Service** → 选你的 `syllabus2cal` 仓库 → Connect。
3. 按下面填写：

| 设置项 | 填什么 |
|---|---|
| Name | `syllabus2cal`（会成为网址的一部分） |
| Region | Oregon 或 Virginia 都行 |
| Branch | `main` |
| Root Directory | 按第 2 步的结果：留空，或填 `syllabus2cal` |
| Runtime | **Python 3** |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Instance Type | **Free** |

4. 往下找到 **Environment Variables**，添加：

| Key | Value |
|---|---|
| `GEMINI_API_KEY` | 你的 Gemini key |
| `FIREBASE_CREDENTIALS` | 用记事本打开下载的 Firebase `.json` 文件，**全选复制整个内容**粘贴进来 |
| `PYTHON_VERSION` | `3.11.9` |

   不用设置 `PUBLIC_BASE_URL`：程序会自动读取 Render 提供的网址。

5. 点 **Deploy Web Service**。第一次构建大约需要 3–5 分钟，日志里出现 `[storage] using firestore` 和 `Application startup complete` 就成功了。

---

## 第 4 步：检查

- 打开 `https://你的服务名.onrender.com/api/status`，应该看到 `"storage":"firestore"`，`"demo_mode"` 是 `false`。
- 打开首页，上传一份 syllabus，然后用手机**关掉 Wi-Fi、用 4G** 扫码订阅。能加上就说明全部通了。

---

## 以后怎么更新

改完代码后运行 `git add -A && git commit -m "..." && git push`，Render 会自动重新部署。日历数据存在 Firestore 里，部署不会让数据丢失。

## 注意事项

- **免费版 15 分钟没人访问就会休眠**，下次打开要等大约 1 分钟。**Demo 开始前先打开一次网站**，把它唤醒。
- 手机来同步日历时如果正好碰上休眠，可能会超时，下一次同步会自动补上。
- 部署失败的话，把 Render 的 **Logs** 页面截图发给我。
