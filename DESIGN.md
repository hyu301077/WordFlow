---
version: alpha
name: WordFlow
description: 面向 Windows 的本地英语词汇学习桌面应用。
colors:
  primary: "#004EA1"
  canvas: "#FFFFFF"
  text: "#1E2430"
  dark-primary: "#818CF8"
  dark-canvas: "#0E1320"
  dark-text: "#E8EDF7"
typography:
  interface:
    fontFamily: "Microsoft YaHei UI, Segoe UI, sans-serif"
    fontSize: 14px
  metrics:
    fontFamily: "Segoe UI, Microsoft YaHei UI, sans-serif"
    fontSize: 48px
rounded:
  control: 10px
  card: 16px
spacing:
  dashboard-section: 16px
  dashboard-column: 12px
components:
  sidebar: {}
  dashboard: {}
  card: {}
  button: {}
---

# WordFlow 界面设计

## Overview

沿用 `backend` 的蓝色栏目和白色内容区。用户打开首页即可看到待复习词数，并在同一张卡片里进入复习、学习或摸底。界面使用简体中文，单词、原句和发音按原文显示。

`wordflow/ui/theme.py` 是 Qt 样式与主题色的来源。`wordflow/ui/common.py` 提供页面标题、区块标题、卡片和导航图标。

## Colors

浅色主题用蓝色侧栏标出导航区域。深色主题使用深蓝灰画布和浅蓝紫强调色。选中的导航项同时有底色、文字和字重变化。进度、答题反馈与禁用状态保留文字提示。

支持标题栏着色的 Windows 使用与侧栏同色的标题栏，保留系统窗口按钮。

## Typography

中文控件采用微软雅黑，数字和英文可回退到 Segoe UI。首页待复习词数用大号数字，表格、按钮和例句保持常规字号。设置说明和例句允许换行。

## Layout

侧栏按学习、资料、词库和更多分组，导航列表独立纵向滚动，词典状态固定在底部。每个页面在自己的内容区滚动。首页内容宽度达到 780 个 Qt 逻辑像素时并排显示两张图表。空间变窄时，图表上下排列。设置分为学习偏好、语音、词库与数据、快捷键。

首页根据当前学习范围显示主要操作。统计页上方显示近 30 天练习量、正确率和已掌握词数，下面展示逐日学习量、摸底成绩和常错词。计划统计包含该计划词汇在各个练习入口的作答。同一张趋势图保留全部数据点，日期标签随可用宽度减少。没有评分时显示破折号，有评分且全部答错时显示 0%。

## Elevation & Depth

卡片主要用细边框和表面色区分。首页待复习卡片使用轻微阴影。图表和表格使用浅色刻度、明确标题和数值标签。

## Shapes

按钮与输入框采用 10px 圆角，常规卡片采用 16px 圆角。复习卡片使用较大的圆角和居中的内容区。

## Components

主要操作使用实色按钮。导航图标与中文标签同时显示。键盘焦点沿用 Qt 的原生交互，并显示可见边线。复习题显示当前题号与进度，设置项用原生输入控件和文字标签。

## Do's and Don'ts

- 用原有卡片和页面标题组织新内容。
- 页面缩小时优先换行和纵向滚动，保留操作入口。
