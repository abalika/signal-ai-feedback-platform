# 前端工作台

React + TypeScript + Vite 前端。请先按项目根目录与 `server/README.md` 启动后端。

```powershell
npm install
npm run dev
```

默认后端地址为 `http://127.0.0.1:8000`。要改地址，在 `app/.env.local` 写入 `VITE_API_URL=...`。模型密钥只配置在后端；前端不保存密钥，也不构造虚假的 AI 分析结果。

`npm run build` 检查 TypeScript 并生成静态前端；`npm run lint` 检查代码。试点项目和演示资料可用根目录 `examples/seed_demo.py` 导入。

界面包含工作台总览、反馈收件箱、技术工单、产品资料库和评测中心，使用浅灰与森林绿主题，并支持手机布局、反馈搜索、题集筛选和键盘弹窗操作。设计规范位于 `design-system/signal/MASTER.md`。

评测中心目前读取仓库内的历史 JSON 快照，支持查看 36 道固定题、参考答案、历史检索排名和导出历史报告。本轮未重跑评测；费用、延迟和四类失败统计等待后续接入。检索集的 30 题属于 36 道固定题，不重复计数。
