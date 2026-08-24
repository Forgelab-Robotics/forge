# forge-policy

通用 Policy Operator 节点协议与 Dora runner。具体算法只需要实现 `PolicyAdapter` 插件接口，并提供关节动作构造函数和输入映射；runner 负责处理 `tick`、`proprio_state`、图像缓存、`PolicyCommand` 生命周期命令和可选的 `PolicyCommandStatus` 输出。

这里的 `PolicyAdapter` 是 Operator 节点内部的算法插件名称，不表示该 Dora 节点属于 Adapter 类别。Forge 的节点分类见仓库根目录 [Forge Node Model](https://github.com/Forgelab-Robotics/forge/blob/master/README.md#forge-node-model)。
