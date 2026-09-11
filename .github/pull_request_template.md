## 目的

说明本次变更解决的具体工程问题，以及目标用户的判断或操作。

## 事实层影响

- [ ] 不修改事实，只修改派生模型或投影
- [ ] 修改 Catalog / Scan / Diff / Review / Effective / Release 事实（说明契约变化）

## 投影影响

- [ ] 不影响 HTML/Web
- [ ] 影响 Version Detail / Catalog / Web（列出 RenderImpact 范围）

## 兼容性

- [ ] CLI 参数和退出码保持兼容
- [ ] 历史配置和证据仍可读取
- [ ] 如有迁移，已提供版本和迁移说明

## 验证

- [ ] `python -m compileall -q src`
- [ ] `python -m unittest discover -s src/lib_guard/test -p 'test*.py' -q`
- [ ] CLI help 和目标工作区 smoke 已验证
