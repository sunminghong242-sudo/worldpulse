# WORLD PULSE 🌍 全球脉搏

手机友好的中文全球新闻站，包含全球焦点、年轻人热议、演唱会雷达（香港、深圳、广州及国际巡演）、科技 AI、VALORANT/CS2 电竞游戏、影视音乐、财经、体育。

## 网站
https://sunminghong242-sudo.github.io/worldpulse/

> 网址只有在 GitHub Pages 启用并成功完成第一次工作流后才能使用。

## 只需设置一次
1. 打开仓库 **Settings → Pages → Build and deployment → Source**，选择 **GitHub Actions**。
2. 打开 **Settings → Actions → General → Workflow permissions**，选择 **Read and write permissions** 并保存。
3. 打开 **Actions → WorldPulse · Update news and publish → Run workflow**，手动执行一次。
4. Actions 工作流显示绿色勾后，打开上方网址。手机浏览器可“添加到主屏幕”。

## 每日更新
GitHub Actions 每天香港时间 **09:00 和 21:00**（UTC 01:00、13:00）尝试抓取 GDELT DOC 2.0 新闻索引并重新发布。定时触发可能延迟，新闻质量和来源取决于新闻 API。初始 JSON 是明确标记的空演示状态，首次成功抓取后才会出现真实报道。新闻只展示标题、媒体名称和跳转原文，不代表真实社交平台阅读量热度，也不提供可靠票务库存。GDELT 搜索收录时间不一定是文章发布时间。

## 文件
- `index.html`：完整静态手机网站，响应式页面、分类、搜索和本机收藏
- `scripts/update_news.py`：无 API key 的公开新闻检索与去重
- `data/news.json`：自动生成的新闻快照
- `.github/workflows/publish.yml`：计划任务、新闻保存、GitHub Pages 部署

如想更改栏目或歌手关键词，可以编辑 `scripts/update_news.py` 内的 `QUERIES`。
