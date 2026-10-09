# 独立演示的合成资料

此目录只含为 KANPACE 独立演示绘制的示意图。没有读取、复制或改绘任何客户订单、图纸、照片、数据库或品牌素材。

| 文件 | 用途 | 数据来源 |
| --- | --- | --- |
| `showcase-render.png` | 璞玉展柜效果示意 | `kanpace/application/bootstrap.py` 的内置虚构 seed，辅以说明性构图 |
| `showcase-drawing.png` | 璞玉展柜构件和施工示意 | 同一内置 seed 中明确的材料、尺寸及数量 |
| `sample-render.png` | 澄光展柜效果示意 | 虚构合成构图；外观不承担工程尺寸依据 |
| `sample-drawing.png` | 澄光展柜清单和施工示意 | `samples/showcase-bom.csv` 的公开合成字段 |

四张 PNG 均为 1600 × 1000，图内固定标注“合成演示”“非真实订单”“未经工程校核”“不可用于加工”。来源字段中的尺寸用于演示清单与图纸的关联，不代表完整工程设计。说明性视图不按比例；孔位、罩体拼接、连接、电气布线、安装公差等均未定义。不能从重复视图或示意层板推算用量。

`tools/demo_fixture.py` 首次初始化专用空演示库时，以标准库复制这些 PNG，写入 `drawing-previews/assets/<sha256>.png`，并按应用原有 `drawing_media.project_media()` 数据契约登记 `renders`、`sources` 和部件的 `parts` 关联。图片通过 `/api/drawing-media/assets/<sha256>.png` 在现有项目界面显示；没有假设用户机器上的绝对路径，也没有将示意图指定为工程主模型。

同一初始化会复用内置 `Store.seed()`，并经 `Store.import_file()` 导入两份合成 CSV 场景：一份保留待审核状态，一份经 `review_part()`、`generate()`、`release()` 和 `auto_assign()` 建立可操作任务。实际开工、暂停和恢复仍经过原业务规则。所有初始项目、部件、任务、人员和导入文档都标为 `demo=True`，审核/发布说明清楚限定为软件流程演示。

独立演示运行只需要 Python 标准库及应用源码。开发者若要重新生成图片，可在装有 Pillow 和 macOS 中文字体的开发机器运行 `python3 static/demo-assets/build_assets.py`；该开发脚本不在演示启动路径中执行。所有生成参数和矢量绘图代码均保留于此，方便追溯。
