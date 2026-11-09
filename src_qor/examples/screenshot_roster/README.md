# 截图格式的模拟清单

这里的 `ipall.list` 与 `formal_files.list` 是合成示例，不是实际项目的完整清单。业务 IP 每行一个；正式文件使用 `#业务IP#` 分组，每条记录是文件名和相对正式阶段的目录。

从仓库根目录生成测试数据，目标目录必须不存在：

```bash
python3 src_qor/examples/screenshot_roster/make_demo.py --out work/my_screenshot_demo
PYTHONPATH=src_qor python3 -m lib_guard.ip_file_history \
  --config work/my_screenshot_demo/roster_config.json \
  --out work/my_screenshot_demo/results
```

工作台“发现 / 登记 RAW”页的四个输入分别指向生成目录里的 `ipall.list`、`formal_files.list`、`RAW` 和 `lib_NL_demo`。点击“保存并测试关联”可以查看结果。

示例预期：5 个 IP 中，两个通过正式链接关联到不同名称的 Library，一个通过唯一同名关联，两个未关联。SerDes 的 LEF 在 V01 和 V03 出现，正式链接指向 V03；FF Liberty 正式链接指向 V01、其最新出现版本为 V03；SS Liberty 在清单中但正式文件缺失。`MXCML2CMOS` 正式文件是复制件，不能据此确认 RAW 来源。DB、GDS、CDL 和 NDM 示例只用于文件盘点，不是有效的工艺库文件。

这些数据没有配置 FULL/PATCH 和项目 Corner 规则；一键质量检查可以生成报告，但覆盖状态可能不完整，不应据此认定真实 IP 通过检查。
