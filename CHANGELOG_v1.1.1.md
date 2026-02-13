# 音译家 AI 音效管理工具 v1.1.1 更新说明

**发布日期**：2026-02-07

---

## 修复

- **导入大量文件时报错「too many SQL variables」**  
  导入几万条音效时，已改为分批写入数据库，不再出现该错误。

- **安装到 Program Files 后导入时报「attempt to write a readonly database」**  
  当软件安装在系统盘 Program Files 时，数据库与配置会自动使用用户目录（`%APPDATA%\Transcriptionist`），保证可正常写入。

---

v1.1.1 为问题修复版本，无新功能。若你当前使用正常，可按需选择是否更新。
