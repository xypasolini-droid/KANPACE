# 本地三维依赖

- Three.js 0.180.0：官方 npm `three@0.180.0` 包中的未改动 module/core、OrbitControls、STLLoader、OBJLoader、GLTFLoader、BufferGeometryUtils。许可证保存在 `vendor/three/LICENSE`。项目与对应源码：https://github.com/mrdoob/three.js/tree/r180 。
- occt-import-js 0.0.23：官方 npm `occt-import-js@0.0.23` 中的未改动 JS/WASM。许可证及 Open CASCADE 许可证分别在 `vendor/occt/LICENSE.md`、`vendor/occt/license.occt-import-js.txt`、`vendor/occt/license.occt.txt`。对应发布包含 C++ 接口源码及构建说明，可从 https://www.npmjs.com/package/occt-import-js/v/0.0.23 获取；源码项目 https://github.com/kovacsv/occt-import-js 。本应用没有更改这些库，WASM通过独立Worker按本机路径加载，可替换独立库文件。

内置 showcase-demo.glb 为本项目自主生成的几何测试样本，不是客户图纸。客户资料与衍生预览保留在本机 data 目录，不纳入通用源码包。
