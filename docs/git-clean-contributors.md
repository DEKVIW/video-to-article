# 去掉 clone 来源作者（Contributors 只留自己）

## 现象

从别人的仓库 `git clone` 后，改到自己的 GitHub 并推送，Insights → **Contributors** 里仍出现原作者（例如 `tiandaren`）。

## 原因

1. **Contributors 看的是 commit 的 Author**，不是仓库 Owner，也不是 `git remote` 指向谁。  
2. clone 会带上**完整提交历史**，旧 Author 会一直统计进去。  
3. 只改 `origin`、甚至做「孤儿分支 + force push」，**GitHub 网页贡献者缓存有时仍会 residual 显示旧贡献者**（延迟数小时到更久，个别情况删仓前列表像“粘住”）。  
4. 因此：**想稳定、干净地「当自己首发」→ 删远程空仓重建 + 本地 `git init` 全新推送 最稳。**

| 做法 | 能否清掉历史 | Contributors 是否一定立刻干净 |
| --- | --- | --- |
| 只改 remote 再 push | 否 | 否 |
| orphan 分支 + `push -f` | 本地/远程分支历史可清 | **不保证立刻**（缓存） |
| **删 GitHub 仓 → 同名新建 → 本地 `git init` 再推** | 远程从零开始 | **最稳** |

## 推荐流程（已按此思路处理本仓库）

前提：代码工作区就是你要开源的内容；个人密钥、`config.json`、`dist/` 等已在 `.gitignore` 中。

### 1. GitHub：删除旧仓库并新建同名空库

1. 删除旧的 `https://github.com/<你>/video-to-article`（或你的仓库名）。  
2. **New repository**，同名即可。  
3. **不要**勾选 README / License / .gitignore（保持完全空）。  
4. 复制 HTTPS 地址，例如：  
   `https://github.com/DEKVIW/video-to-article.git`

### 2. 本地：丢掉旧 `.git`，重新初始化

在项目根目录（PowerShell）：

```powershell
cd "你的项目根目录"

# 确认没有未保存的工作需要备份
# 然后删除本地 Git 元数据（只删版本库，不删源码文件）
Remove-Item -Recurse -Force .git

git init -b main
git add -A
git status   # 确认无 config.json、.venv、dist、models 等

git commit -m "Initial commit"

git remote add origin https://github.com/DEKVIW/video-to-article.git
git push -u origin main
```

提交说明用规范短句即可：

```text
Initial commit
```

### 3. 验证

```powershell
git log --oneline
# 应只有 1 条

git log --format="%an <%ae> %s"
# Author 只有你自己
```

浏览器打开仓库 → Insights → Contributors：

- 新建空仓后首次 push，一般**只有你**；  
- 若仍异常，硬刷新或换无密窗口，等几分钟后再看。

## 为何不优先用 orphan？

孤儿分支在**技术上**也能得到「仅一条自己的 commit」：

```powershell
git checkout --orphan clean-main
git add -A
git commit -m "Initial commit"
git branch -M main
git push -f origin main
```

本仓库实践中：远程历史已变成你的提交后，**网页 Contributors 仍可能暂时显示旧作者**。  
所以文档结论改为：

- **以「删仓 + `git init` + 推到新空库」为可靠方案**；  
- orphan 仅作「不删远程仓」时的备选，且不保证 UI 立刻干净。

## 注意

- `Remove-Item .git` **不可恢复**旧提交历史；执行前确认不需要旧 SHA。  
- 不要对**别人的**仓库 force push。  
- 邮箱尽量用已绑定到你 GitHub 账号的地址（`git config user.email`），否则 Contributors 可能显示成「未关联用户」或匿名。

## 本项目相关路径

| 项 | 说明 |
| --- | --- |
| 开源仓库 | https://github.com/DEKVIW/video-to-article |
| 产品 | 一览成文 / YilanChengWen |
| Python 包 | `video_to_article` |
| 本说明 | `docs/git-clean-contributors.md`（入库） |
