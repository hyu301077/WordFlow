# WordFlow（词流）

把自己的英文音视频、截图和文档变成学习材料的 Windows 桌面程序。英文录音和视频可以逐句听原声，截图可以按熟词本生成练习句。每份素材的词汇、原文和音频都能从同一个学习计划打开。

安装、启动和打包见 [使用说明.md](使用说明.md)。

按英文句子剪 MP3 的工作流见 [TED 视频剪辑 Skill](skill/ted-video-to-sentence-clips/SKILL.md)。

在 Windows 上安装 Python 3.11 或以上版本后，从仓库根目录运行：

```powershell
.\scripts\run.ps1
```

可选本地词典可通过 `.\scripts\fetch_dict.ps1` 下载。运行 `.\scripts\build.ps1` 可生成 `dist\WordFlow\WordFlow.exe`。

## 许可证

WordFlow 的原创代码和文档采用 [MIT 许可证](LICENSE)。第三方依赖、词典和语音识别模型遵循各自的许可证。
