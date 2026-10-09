# 项目效果图缓存

`build_project_renders.py` 根据经过人工核验的选择清单，把原图生成到当前工厂 `data/drawing-previews/`。

```sh
python3 tools/build_project_renders.py --source-dir /path/to/authorized-order-files --selection /path/to/reviewed-selection.json
```

需要 Pillow；PDF 转页还需要 Poppler 的 `pdftoppm`。通用源码中的 `project-render-selection.json` 是空模板，客户的项目、路径和原文件哈希由所属工厂自行保存。已有项目用 `order_key` 匹配，选择项固定原文件 SHA-256、PDF 页码或 Excel 图片成员；源文件变化后必须重新核验。

- `scope: project` 表示项目/区域整体效果；`scope: cabinet` 表示柜体参考。
- `source_category: effect_file` 表示原效果文件；`concept` 表示概念方案；`spreadsheet_cabinet` 表示表格里的柜体参考。
- `reference_note` 保留版本疑问和人工核验说明。

效果图用于查看整体；生产拆解依据施工图和经过确认的工程数据。本工具不从效果图推断制造尺寸。历史客户选择清单与统计保留在原工厂，不随通用代码交付。
